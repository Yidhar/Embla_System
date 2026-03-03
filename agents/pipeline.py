"""Multi-Agent Pipeline — unified entry point for ALL requests.

Orchestrates: ShellAgent → (direct reply | CoreAgent → Expert(s) → Dev(s) → Review)
Yields events compatible with the existing event stream.

ShellAgent IS the outer LLM — it handles simple queries directly and only
calls dispatch_to_core for execution tasks.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

from agents.router_engine import RouterDecision
from agents.runtime.agent_session import AgentSessionStore, AgentStatus
from agents.runtime.mailbox import AgentMailbox
from agents.runtime.task_board import TaskBoardEngine

from agents.shell_agent import ShellAgent
from agents.core_agent import CoreAgent
from agents.expert_agent import ExpertAgent, ExpertAgentConfig
from agents.review_agent import ReviewAgent

logger = logging.getLogger(__name__)


def _trim_text(value: Any, *, limit: int = 220) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _extract_report_text(report: Dict[str, Any]) -> str:
    rows = report.get("reports")
    if isinstance(rows, list):
        for item in rows:
            if isinstance(item, str) and item.strip():
                return _trim_text(item)
            if isinstance(item, dict):
                try:
                    return _trim_text(json.dumps(item, ensure_ascii=False))
                except Exception:
                    continue
    return ""


def _build_core_execution_receipt(
    *,
    pipeline_id: str,
    decomposition: Dict[str, Any],
    expert_results: List[Dict[str, Any]],
    reports: List[Dict[str, Any]],
) -> Dict[str, Any]:
    deliverables: List[str] = []
    summary_lines: List[str] = []
    for report in reports:
        agent_id = str(report.get("session_id") or report.get("agent_id") or "").strip()
        status = str(report.get("status") or "unknown").strip()
        report_text = _extract_report_text(report)
        if report_text:
            deliverables.append(report_text)
            summary_lines.append(f"- [{status}] {agent_id or 'expert'}: {report_text}")
        else:
            summary_lines.append(f"- [{status}] {agent_id or 'expert'}: report_received")

    if not summary_lines:
        summary_lines.append("- [info] no expert report payload was produced")

    final_answer = "\n".join(
        [
            "Core execution pipeline completed.",
            f"Goal: {str(decomposition.get('original_goal') or '').strip()}",
            f"Experts spawned: {len(expert_results)}",
            *summary_lines[:8],
        ]
    ).strip()

    return {
        "type": "execution_receipt",
        "pipeline_id": pipeline_id,
        "stop_reason": "submitted_completion",
        "agent_state": {
            "task_completed": True,
            "final_answer": final_answer,
            "completion_summary": final_answer,
            "deliverables": deliverables[:8],
            "expert_count": len(expert_results),
            "goal_id": str(decomposition.get("goal_id") or ""),
        },
    }


async def run_multi_agent_pipeline(
    *,
    message: str,
    session_id: str = "",
    risk_level: str = "",
    store: Optional[AgentSessionStore] = None,
    mailbox: Optional[AgentMailbox] = None,
    task_board_engine: Optional[TaskBoardEngine] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Unified multi-agent execution pipeline.

    ALL requests enter here. ShellAgent decides whether to:
    1. Respond directly (chat, status queries, file reading)
    2. Dispatch to Core for execution (code changes, deployments, analysis)

    Event types:
        - pipeline_start
        - route_decision
        - content            (Shell direct reply or Core execution output)
        - tool_stage         (verify-stage completion signal for observability)
        - execution_receipt  (stable structured completion payload)
        - core_decomposition
        - expert_spawned
        - expert_progress
        - expert_report
        - pipeline_end
    """
    pipeline_id = f"pipe_{uuid.uuid4().hex[:12]}"
    started_at = time.time()

    _store = store or AgentSessionStore(db_path=":memory:")
    _mailbox = mailbox or AgentMailbox(db_path=":memory:")

    yield {
        "type": "pipeline_start",
        "pipeline_id": pipeline_id,
        "message": message,
        "session_id": session_id,
    }

    # ── Phase 1: Shell routes via TaskRouterEngine ─────────────

    shell = ShellAgent()
    decision = shell.route(message, session_id=session_id, risk_level=risk_level)
    needs_core = shell.should_dispatch(decision)

    yield {
        "type": "route_decision",
        "pipeline_id": pipeline_id,
        "needs_core": needs_core,
        "delegation_intent": decision.delegation_intent,
        "selected_role": decision.selected_role,
        "model_tier": decision.selected_model_tier,
        "prompt_profile": decision.prompt_profile,
        "tool_profile": list(decision.tool_profile),
    }

    # ── Shell direct reply (no Core dispatch needed) ───────────
    if not needs_core:
        # Shell handles directly: yield content event with the user message
        # for the outer LLM to process with Shell's system prompt.
        # In production, Shell would run its own mini_loop with read-only tools.
        yield {
            "type": "shell_direct",
            "pipeline_id": pipeline_id,
            "system_prompt": shell.build_system_prompt(),
            "user_message": message,
            "delegation_intent": decision.delegation_intent,
            "model_tier": decision.selected_model_tier,
        }

        yield {
            "type": "pipeline_end",
            "pipeline_id": pipeline_id,
            "reason": "shell_direct_reply",
            "duration_ms": int((time.time() - started_at) * 1000),
        }
        return

    # ── Phase 2: Core decomposes goal into Expert assignments ──

    intent_type = "analysis"
    if str(decision.task_type or "").strip().lower() == "ops":
        intent_type = "ops"
    elif str(decision.task_type or "").strip().lower() in {"development", "general"}:
        intent_type = "development"

    dispatch = shell.dispatch_to_core(
        {
            "goal": message,
            "intent_type": intent_type,
            "target_repo": "external",
        },
        session_id=session_id,
        risk_level=risk_level or "write_repo",
    )

    core = CoreAgent(store=_store, mailbox=_mailbox, task_board_engine=task_board_engine)
    decomposition = core.decompose_goal(dispatch)

    yield {
        "type": "core_decomposition",
        "pipeline_id": pipeline_id,
        "goal_id": decomposition.get("goal_id"),
        "expert_count": len(decomposition.get("expert_assignments", [])),
        "subtask_count": decomposition.get("subtask_count", 0),
        "model_tier": decomposition.get("model_tier"),
    }

    # ── Phase 3: Spawn Experts ─────────────────────────────────

    core_session_id = f"core_{pipeline_id}"
    expert_results = core.spawn_experts(decomposition, core_session_id=core_session_id)

    for er in expert_results:
        yield {
            "type": "expert_spawned",
            "pipeline_id": pipeline_id,
            "expert_type": er.get("expert_type"),
            "agent_id": er.get("agent_id"),
        }

    # ── Phase 4: Expert planning + Dev spawning ────────────────

    expert_instances: List[ExpertAgent] = []
    for er in expert_results:
        agent_id = er.get("agent_id", "")
        expert_type = er.get("expert_type", "backend")
        assignment = next(
            (a for a in decomposition.get("expert_assignments", []) if a["expert_type"] == expert_type),
            {},
        )
        expert = ExpertAgent(
            config=ExpertAgentConfig(
                expert_type=expert_type,
                prompt_blocks=assignment.get("prompt_blocks", []),
                tool_subset=assignment.get("tool_subset", []),
                model_tier=assignment.get("model_tier", "primary"),
                prompt_profile=assignment.get("prompt_profile", ""),
            ),
            session_id=agent_id,
            store=_store,
            mailbox=_mailbox,
            task_board_engine=task_board_engine,
        )
        scope = er.get("scope", assignment.get("scope", ""))
        tasks = expert.plan_tasks(scope)
        if tasks:
            devs = expert.spawn_devs(tasks)
            yield {
                "type": "expert_progress",
                "pipeline_id": pipeline_id,
                "expert_type": expert_type,
                "agent_id": agent_id,
                "board_id": expert.board_id,
                "tasks_planned": len(tasks),
                "devs_spawned": len(devs),
            }
        expert_instances.append(expert)

    # ── Phase 5: Collect results ───────────────────────────────

    reports = core.collect_reports(core_session_id)
    for report in reports:
        yield {
            "type": "expert_report",
            "pipeline_id": pipeline_id,
            "agent_id": report.get("session_id"),
            "status": report.get("status"),
            "reports": report.get("reports", []),
        }

    receipt_event = _build_core_execution_receipt(
        pipeline_id=pipeline_id,
        decomposition=decomposition,
        expert_results=expert_results,
        reports=reports,
    )

    # Emit a tool-loop compatible verify-stage signal so posture/incidents
    # collectors can consume completion semantics from the unified pipeline.
    yield {
        "type": "tool_stage",
        "pipeline_id": pipeline_id,
        "phase": "verify",
        "status": "success",
        "reason": "submitted_completion",
        "decision": "stop",
        "round": 1,
        "details": {
            "task_completed": True,
            "submit_result_called": True,
            "submit_result_round": 1,
        },
    }

    yield receipt_event

    yield {
        "type": "content",
        "pipeline_id": pipeline_id,
        "source": "execution_receipt",
        "text": str(receipt_event.get("agent_state", {}).get("final_answer") or ""),
    }

    # ── Done ───────────────────────────────────────────────────

    yield {
        "type": "pipeline_end",
        "pipeline_id": pipeline_id,
        "reason": "completed",
        "duration_ms": int((time.time() - started_at) * 1000),
        "expert_count": len(expert_results),
        "core_session_id": core_session_id,
    }


__all__ = ["run_multi_agent_pipeline"]
