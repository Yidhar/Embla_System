"""Lightweight ReAct tool-loop for child agents (Dev, Review, Expert).

Extracted from the full agentic loop (agents/tool_loop.py) with only
the essential features needed for child agent operation:
  - Independent LLM session
  - Configurable tool subset (parent-defined)
  - Interrupt flag checking (parent-initiated terminate)
  - Parent message polling
  - Automatic status reporting
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from agents.runtime.agent_session import AgentSessionStore, AgentStatus
from agents.runtime.child_tools import handle_child_tool_call
from agents.runtime.mailbox import AgentMailbox

logger = logging.getLogger(__name__)


@dataclass
class MiniLoopConfig:
    """Configuration for a child agent's tool loop.

    No hard limits by design — the parent agent decides when to terminate.
    These are soft hints that the child can use for self-regulation.
    """

    max_rounds: int = 500         # soft hint, not enforced
    poll_parent_every_n: int = 5  # check parent messages every N rounds
    model_name: str = ""          # override model; empty = use default
    include_child_tools: bool = True  # disable for parent/core loops


@dataclass
class MiniLoopState:
    """Runtime state for a single mini loop execution."""

    round_num: int = 0
    total_tool_calls: int = 0
    tool_errors: int = 0
    stop_reason: str = ""
    started_at: float = 0.0
    elapsed_seconds: float = 0.0


# Type alias for the LLM call function
# Signature: (messages, tools, model) -> dict with {content, tool_calls}
LLMCallFn = Callable[
    [List[Dict[str, Any]], List[Dict[str, Any]], str],
    Any,  # coroutine returning dict
]

# Type alias for tool executor
# Signature: (tool_name, arguments) -> dict (result)
ToolExecutorFn = Callable[
    [str, Dict[str, Any]],
    Any,  # coroutine returning dict
]


# ── Child Tools (built-in) ─────────────────────────────────────

_CHILD_TOOL_NAMES = {
    "report_to_parent",
    "read_parent_messages",
    "update_my_task_status",
    "send_message_to_agent",
    "read_agent_messages",
}


# ── Mini Loop ──────────────────────────────────────────────────

async def run_mini_loop(
    *,
    session_id: str,
    store: AgentSessionStore,
    mailbox: AgentMailbox,
    llm_call: LLMCallFn,
    tool_executor: ToolExecutorFn,
    tool_definitions: List[Dict[str, Any]],
    system_prompt: str = "",
    initial_task: str = "",
    config: Optional[MiniLoopConfig] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Run a lightweight ReAct tool loop for a child agent.

    Yields events for observability:
        {"type": "round_start", "round": N}
        {"type": "tool_call", "name": ..., "arguments": ...}
        {"type": "tool_result", "name": ..., "result": ...}
        {"type": "content", "text": ...}
        {"type": "loop_end", "reason": ..., "state": ...}

    The loop stops when:
        1. The child calls report_to_parent(type="completed") → status → Waiting
        2. The parent sets interrupt flag → child notices and yields control
        3. LLM returns content without tool calls (natural stop)
        4. Session is no longer Running
    """
    cfg = config or MiniLoopConfig()
    state = MiniLoopState(started_at=time.monotonic())

    session = store.get(session_id)
    if not session:
        yield {"type": "loop_end", "reason": "session_not_found", "state": {}}
        return

    # Build initial messages
    messages: List[Dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if initial_task:
        messages.append({"role": "user", "content": initial_task})

    # Restore previous messages if resuming
    if session.messages:
        messages = list(session.messages)

    # Merge child built-in tools with configured tool subset.
    all_tool_defs = list(tool_definitions)
    if bool(cfg.include_child_tools):
        from agents.runtime.child_tools import get_child_tool_definitions

        all_tool_defs.extend(get_child_tool_definitions())

    for round_num in range(1, cfg.max_rounds + 1):
        state.round_num = round_num

        # ── Check interrupt ────────────────────────────────────
        session = store.get(session_id)
        if not session or session.status != AgentStatus.RUNNING:
            state.stop_reason = "session_not_running"
            break

        if session.interrupt_requested:
            state.stop_reason = "parent_interrupted"
            store.update_status(session_id, AgentStatus.WAITING)
            break

        # ── Poll parent messages (every N rounds) ──────────────
        if round_num > 1 and round_num % cfg.poll_parent_every_n == 0:
            parent_msgs = mailbox.read(session_id, since_seq=0)
            parent_only = [m for m in parent_msgs if m.from_id == session.parent_id]
            if parent_only:
                latest = parent_only[-1]
                # Inject as a system message
                messages.append({
                    "role": "system",
                    "content": f"[Parent message] {latest.content}",
                })

        yield {"type": "round_start", "round": round_num}

        # ── LLM call ──────────────────────────────────────────
        try:
            response = await llm_call(messages, all_tool_defs, cfg.model_name)
        except Exception as exc:
            logger.exception("LLM call failed in mini loop round %d", round_num)
            state.tool_errors += 1
            state.stop_reason = f"llm_error: {exc}"
            break

        # Parse response
        content = response.get("content", "")
        tool_calls = response.get("tool_calls", [])

        if content:
            yield {"type": "content", "text": content}
            messages.append({"role": "assistant", "content": content})

        # ── No tool calls → natural stop ──────────────────────
        if not tool_calls:
            state.stop_reason = "no_tool_calls"
            break

        # ── Process tool calls ────────────────────────────────
        # Add assistant message with tool calls
        assistant_msg: Dict[str, Any] = {"role": "assistant"}
        if content:
            assistant_msg["content"] = content
        assistant_msg["tool_calls"] = [
            {
                "id": tc.get("id", f"call_{round_num}_{i}"),
                "type": "function",
                "function": {
                    "name": tc.get("name", ""),
                    "arguments": json.dumps(tc.get("arguments", {}), ensure_ascii=False),
                },
            }
            for i, tc in enumerate(tool_calls)
        ]
        # Replace the content-only message if we added one
        if content and messages[-1].get("role") == "assistant":
            messages[-1] = assistant_msg
        else:
            messages.append(assistant_msg)

        stop_after_tools = False

        for tc in tool_calls:
            tool_name = tc.get("name", "")
            tool_args = tc.get("arguments", {})
            tool_id = tc.get("id", f"call_{round_num}")

            if isinstance(tool_args, str):
                try:
                    tool_args = json.loads(tool_args)
                except json.JSONDecodeError:
                    tool_args = {"raw": tool_args}

            state.total_tool_calls += 1
            yield {"type": "tool_call", "name": tool_name, "arguments": tool_args}

            # Route to correct handler
            try:
                if bool(cfg.include_child_tools) and tool_name in _CHILD_TOOL_NAMES:
                    result = handle_child_tool_call(
                        tool_name,
                        tool_args,
                        child_session_id=session_id,
                        store=store,
                        mailbox=mailbox,
                    )
                else:
                    result = await tool_executor(tool_name, tool_args)
            except Exception as exc:
                logger.exception("Tool %s failed", tool_name)
                state.tool_errors += 1
                result = {"error": str(exc)}

            yield {"type": "tool_result", "name": tool_name, "result": result}

            # Add tool result to messages
            messages.append({
                "role": "tool",
                "tool_call_id": tool_id,
                "content": json.dumps(result, ensure_ascii=False, default=str),
            })

            # Stop only when a completed report was accepted by the child-tool handler.
            if (
                tool_name == "report_to_parent"
                and tool_args.get("type") == "completed"
                and isinstance(result, dict)
                and not result.get("error")
                and bool(result.get("reported"))
                and str(result.get("status") or "").strip().lower() == "waiting"
            ):
                stop_after_tools = True

        if stop_after_tools:
            state.stop_reason = "child_reported_completed"
            break

    # ── Finalize ──────────────────────────────────────────────
    state.elapsed_seconds = time.monotonic() - state.started_at

    if not state.stop_reason:
        state.stop_reason = "max_rounds_reached"

    # Save conversation history for resume
    store.save_messages(session_id, messages)

    yield {
        "type": "loop_end",
        "reason": state.stop_reason,
        "state": {
            "rounds": state.round_num,
            "total_tool_calls": state.total_tool_calls,
            "tool_errors": state.tool_errors,
            "elapsed_seconds": round(state.elapsed_seconds, 2),
        },
    }


__all__ = ["MiniLoopConfig", "MiniLoopState", "run_mini_loop"]
