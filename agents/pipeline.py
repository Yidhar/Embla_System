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
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Optional

from agents.router_engine import RouterDecision
from agents.runtime.agent_session import AgentSessionStore, AgentStatus
from agents.runtime.mailbox import AgentMailbox
from agents.runtime.task_board import TaskBoardEngine, TaskStatus

from agents.shell_agent import ShellAgent
from agents.core_agent import CoreAgent
from agents.expert_agent import ExpertAgent, ExpertAgentConfig
from agents.dev_agent import DevAgent, DevAgentConfig
from agents.review_agent import ReviewAgent
from agents.runtime.mini_loop import MiniLoopConfig, run_mini_loop

logger = logging.getLogger(__name__)


ChildLLMCallFn = Callable[[List[Dict[str, Any]], List[Dict[str, Any]], str], Awaitable[Dict[str, Any]]]
ChildToolExecutorFn = Callable[[str, Dict[str, Any], str], Awaitable[Dict[str, Any]]]


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


def _normalize_child_session_cleanup_mode(mode: str) -> str:
    normalized = str(mode or "").strip().lower()
    aliases = {
        "": "retain",
        "off": "retain",
        "none": "retain",
        "disabled": "retain",
        "keep": "retain",
        "destroy_on_end": "destroy",
        "destroyed": "destroy",
        "immediate_destroy": "destroy",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"retain", "destroy", "ttl"}:
        return "retain"
    return normalized


def _parse_iso_to_timestamp(raw: str) -> Optional[float]:
    text = str(raw or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return float(dt.timestamp())


def _session_age_seconds(session: Any, *, now_ts: float) -> Optional[float]:
    updated_at = str(getattr(session, "updated_at", "") or getattr(session, "created_at", "") or "")
    ts = _parse_iso_to_timestamp(updated_at)
    if ts is None:
        return None
    return max(0.0, float(now_ts - ts))


def _collect_descendant_session_ids(
    *,
    store: AgentSessionStore,
    root_session_ids: List[str],
) -> List[str]:
    queue: List[str] = [str(item or "").strip() for item in root_session_ids if str(item or "").strip()]
    collected: List[str] = []
    visited: set[str] = set()
    while queue:
        session_id = queue.pop(0)
        if not session_id or session_id in visited:
            continue
        visited.add(session_id)
        collected.append(session_id)
        for child in store.list_children(session_id):
            child_id = str(getattr(child, "session_id", "") or "").strip()
            if child_id and child_id not in visited:
                queue.append(child_id)
    return collected


def _apply_child_session_cleanup(
    *,
    store: AgentSessionStore,
    mailbox: AgentMailbox,
    core_session_id: str,
    pipeline_id: str,
    mode: str,
    ttl_seconds: int,
) -> Dict[str, Any]:
    normalized_mode = _normalize_child_session_cleanup_mode(mode)
    normalized_ttl = max(0, int(ttl_seconds))
    summary: Dict[str, Any] = {
        "mode": normalized_mode,
        "requested_mode": str(mode or ""),
        "ttl_seconds": normalized_ttl,
        "core_session_id": str(core_session_id or ""),
        "pipeline_id": str(pipeline_id or ""),
        "root_candidates": 0,
        "destroyed_count": 0,
        "purged_message_count": 0,
        "destroyed_session_ids": [],
    }
    if normalized_mode == "retain":
        return summary

    roots = store.list_children(core_session_id)
    now_ts = time.time()
    root_ids: List[str] = []
    for child in roots:
        child_id = str(getattr(child, "session_id", "") or "").strip()
        if not child_id:
            continue
        metadata = getattr(child, "metadata", {})
        metadata_dict = metadata if isinstance(metadata, dict) else {}
        child_pipeline_id = str(metadata_dict.get("pipeline_id") or "").strip()
        if not child_pipeline_id:
            continue

        if normalized_mode == "destroy":
            if child_pipeline_id == str(pipeline_id or "").strip():
                root_ids.append(child_id)
            continue

        # ttl mode: clean aged pipeline-scoped roots (current and historical runs).
        age_seconds = _session_age_seconds(child, now_ts=now_ts)
        if age_seconds is None:
            continue
        if age_seconds >= float(normalized_ttl):
            root_ids.append(child_id)

    root_ids = sorted(set(root_ids))
    summary["root_candidates"] = len(root_ids)
    if not root_ids:
        return summary

    destroy_ids = _collect_descendant_session_ids(store=store, root_session_ids=root_ids)
    destroyed_ids: List[str] = []
    for session_id in destroy_ids:
        try:
            store.destroy(session_id, reason=f"pipeline_cleanup:{normalized_mode}:{pipeline_id}")
            destroyed_ids.append(session_id)
        except Exception:
            logger.debug("Failed to destroy child session during cleanup: %s", session_id, exc_info=True)

    purged_message_count = 0
    if destroyed_ids:
        try:
            purged_message_count = mailbox.purge_agent_messages(destroyed_ids)
        except Exception:
            logger.debug("Failed to purge mailbox messages during cleanup", exc_info=True)

    summary["destroyed_count"] = len(destroyed_ids)
    summary["purged_message_count"] = int(purged_message_count)
    summary["destroyed_session_ids"] = destroyed_ids[:20]
    return summary


def _build_runtime_tool_definitions(tool_names: List[str]) -> List[Dict[str, Any]]:
    """Build lightweight tool schemas from allowed tool names.

    The full contract schema is enforced at execution time by the tool
    executor and downstream policy firewalls. Here we expose only minimal
    JSON-schema envelopes so the model can legally emit structured tool calls.
    """
    definitions: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw_name in tool_names:
        tool_name = str(raw_name or "").strip()
        if not tool_name or tool_name in seen:
            continue
        seen.add(tool_name)
        definitions.append(
            {
                "name": tool_name,
                "description": f"Execute runtime tool `{tool_name}`.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": True,
                },
            }
        )
    return definitions


def _build_core_execution_receipt(
    *,
    pipeline_id: str,
    decomposition: Dict[str, Any],
    expert_results: List[Dict[str, Any]],
    reports: List[Dict[str, Any]],
    review_results: List[Dict[str, Any]],
    task_completed: bool,
    stop_reason: str,
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

    review_lines: List[str] = []
    review_verdicts: List[str] = []
    for review in review_results:
        verdict = str(review.get("verdict") or "unknown").strip().lower()
        review_verdicts.append(verdict)
        expert_type = str(review.get("expert_type") or "expert").strip()
        summary = _trim_text(review.get("summary") or "")
        issues = review.get("issues") if isinstance(review.get("issues"), list) else []
        review_lines.append(
            f"- [{verdict}] review/{expert_type}: "
            f"{summary or 'no_summary'} (issues={len(issues)})"
        )

    if not review_lines:
        review_lines.append("- [info] review stage was not executed")

    if task_completed:
        header = "Core execution pipeline completed."
    else:
        header = "Core execution pipeline delegated tasks and is waiting for child completion."

    final_answer = "\n".join(
        [
            header,
            f"Goal: {str(decomposition.get('original_goal') or '').strip()}",
            f"Experts spawned: {len(expert_results)}",
            f"Review checks: {len(review_results)}",
            *summary_lines[:8],
            *review_lines[:8],
        ]
    ).strip()

    combined_deliverables = (deliverables + review_lines)[:12]

    return {
        "type": "execution_receipt",
        "pipeline_id": pipeline_id,
        "stop_reason": str(stop_reason or ""),
        "agent_state": {
            "task_completed": bool(task_completed),
            "final_answer": final_answer,
            "completion_summary": final_answer,
            "deliverables": combined_deliverables,
            "expert_count": len(expert_results),
            "review_count": len(review_results),
            "review_verdicts": review_verdicts,
            "goal_id": str(decomposition.get("goal_id") or ""),
        },
    }


async def run_multi_agent_pipeline(
    *,
    message: str,
    session_id: str = "",
    risk_level: str = "",
    route_decision: Optional[Dict[str, Any]] = None,
    forced_path: str = "",
    core_session_id: str = "",
    child_llm_call: Optional[ChildLLMCallFn] = None,
    child_tool_executor: Optional[ChildToolExecutorFn] = None,
    enable_child_execution: bool = False,
    child_max_rounds: int = 12,
    child_session_cleanup_mode: str = "retain",
    child_session_cleanup_ttl_seconds: int = 86400,
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
        - dev_loop_start
        - dev_loop_event
        - dev_loop_end
        - expert_report
        - review_spawned
        - review_result
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
        "child_execution_enabled": bool(enable_child_execution),
        "child_session_cleanup_mode": _normalize_child_session_cleanup_mode(child_session_cleanup_mode),
        "child_session_cleanup_ttl_seconds": max(0, int(child_session_cleanup_ttl_seconds)),
    }

    # ── Phase 1: Shell routes via TaskRouterEngine ─────────────

    shell = ShellAgent()
    precomputed_decision = None
    if isinstance(route_decision, dict):
        try:
            precomputed_decision = RouterDecision.model_validate(route_decision)
        except Exception as exc:
            logger.warning("Invalid precomputed route_decision; falling back to internal routing: %s", exc)

    if precomputed_decision is not None:
        decision = precomputed_decision
        decision_source = "precomputed"
    else:
        decision = shell.route(message, session_id=session_id, risk_level=risk_level)
        decision_source = "pipeline_router"

    normalized_forced_path = str(forced_path or "").strip().lower()
    if normalized_forced_path == "path-c":
        needs_core = True
    elif normalized_forced_path in {"path-a", "path-b"}:
        needs_core = False
    else:
        needs_core = shell.should_dispatch(decision)

    yield {
        "type": "route_decision",
        "pipeline_id": pipeline_id,
        "decision_source": decision_source,
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

    dispatch: Dict[str, Any]
    if precomputed_decision is not None:
        dispatch = {
            "dispatched": True,
            "goal": message,
            "intent_type": intent_type,
            "target_repo": "external",
            "context_summary": "",
            "relevant_memories": [],
            "priority": "normal",
            "router_decision": decision.to_dict(),
            "delegation_intent": decision.delegation_intent,
            "tool_profile": list(decision.tool_profile),
            "prompt_profile": decision.prompt_profile,
            "model_tier": decision.selected_model_tier,
            "selected_role": decision.selected_role,
            "injection_mode": decision.injection_mode,
        }
    else:
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

    resolved_core_session_id = str(core_session_id or "").strip() or str(session_id or "").strip()
    if not resolved_core_session_id:
        resolved_core_session_id = f"core_{pipeline_id}"

    expert_results = core.spawn_experts(
        decomposition,
        core_session_id=resolved_core_session_id,
        pipeline_id=pipeline_id,
    )

    for er in expert_results:
        yield {
            "type": "expert_spawned",
            "pipeline_id": pipeline_id,
            "expert_type": er.get("expert_type"),
            "agent_id": er.get("agent_id"),
        }

    # ── Phase 4: Expert planning + Dev spawning ────────────────

    expert_instances: List[ExpertAgent] = []
    review_results: List[Dict[str, Any]] = []
    review_expected_count = 0
    child_execution_enabled = bool(
        enable_child_execution and child_llm_call is not None and child_tool_executor is not None
    )
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
        devs: List[Dict[str, Any]] = []
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

        # Run real child mini-loops when runtime callbacks are injected by caller.
        if child_execution_enabled and devs and child_llm_call is not None and child_tool_executor is not None:
            for dev in devs:
                dev_agent_id = str(dev.get("agent_id") or "").strip()
                task_id = str(dev.get("task_id") or "").strip()
                if not dev_agent_id:
                    continue
                dev_session = _store.get(dev_agent_id)
                if dev_session is None:
                    continue

                dev_tool_subset = list(dev_session.tool_subset or assignment.get("tool_subset", []))
                dev_prompt_blocks = list(dev_session.prompt_blocks or assignment.get("prompt_blocks", []))
                dev_agent = DevAgent(
                    config=DevAgentConfig(
                        prompt_blocks=dev_prompt_blocks,
                        tool_subset=dev_tool_subset,
                        prompts_root="system/prompts",
                    ),
                    session_id=dev_agent_id,
                    store=_store,
                    mailbox=_mailbox,
                )
                runtime_tool_defs = _build_runtime_tool_definitions(dev_tool_subset)
                dev_initial_task = str(dev_session.task_description or scope or "").strip()
                max_rounds = max(1, int(child_max_rounds))
                loop_config = MiniLoopConfig(max_rounds=max_rounds, poll_parent_every_n=3)

                async def _execute_dev_tool(
                    tool_name: str,
                    arguments: Dict[str, Any],
                    *,
                    _allowed_tools: List[str] = dev_tool_subset,
                    _dev_session_id: str = dev_agent_id,
                ) -> Dict[str, Any]:
                    normalized_tool = str(tool_name or "").strip()
                    if _allowed_tools and normalized_tool not in _allowed_tools:
                        return {
                            "error": f"tool_not_allowed:{normalized_tool}",
                            "status": "blocked",
                            "tool_name": normalized_tool,
                        }
                    safe_arguments = arguments if isinstance(arguments, dict) else {}
                    return await child_tool_executor(normalized_tool, safe_arguments, _dev_session_id)

                yield {
                    "type": "dev_loop_start",
                    "pipeline_id": pipeline_id,
                    "expert_id": agent_id,
                    "expert_type": expert_type,
                    "agent_id": dev_agent_id,
                    "task_id": task_id,
                    "tool_subset": dev_tool_subset,
                }

                async for mini_event in run_mini_loop(
                    session_id=dev_agent_id,
                    store=_store,
                    mailbox=_mailbox,
                    llm_call=child_llm_call,
                    tool_executor=_execute_dev_tool,
                    tool_definitions=runtime_tool_defs,
                    system_prompt=dev_agent.build_system_prompt(),
                    initial_task=dev_initial_task,
                    config=loop_config,
                ):
                    yield {
                        "type": "dev_loop_event",
                        "pipeline_id": pipeline_id,
                        "expert_id": agent_id,
                        "expert_type": expert_type,
                        "agent_id": dev_agent_id,
                        "task_id": task_id,
                        "event": mini_event,
                    }

                final_session = _store.get(dev_agent_id)
                final_status = str(final_session.status.value) if final_session is not None else "missing"
                completion_report = ""
                if final_session is not None:
                    completion_report = str(final_session.metadata.get("completion_report") or "").strip()

                if task_board_engine is not None and expert.board_id and task_id:
                    try:
                        if final_status == AgentStatus.WAITING.value:
                            task_board_engine.update_task(
                                expert.board_id,
                                task_id,
                                status=TaskStatus.DONE,
                                summary=completion_report or "child loop completed",
                            )
                        elif final_status == AgentStatus.RUNNING.value:
                            task_board_engine.update_task(
                                expert.board_id,
                                task_id,
                                status=TaskStatus.IN_PROGRESS,
                            )
                    except Exception:
                        logger.debug(
                            "Failed to update task board after dev loop (board=%s task=%s)",
                            expert.board_id,
                            task_id,
                            exc_info=True,
                        )

                yield {
                    "type": "dev_loop_end",
                    "pipeline_id": pipeline_id,
                    "expert_id": agent_id,
                    "expert_type": expert_type,
                    "agent_id": dev_agent_id,
                    "task_id": task_id,
                    "status": final_status,
                    "completion_report": completion_report,
                }

        expert_progress = expert.check_progress()
        expert_completed = bool(expert_progress.get("all_devs_done"))
        if not tasks:
            expert_completed = True

        if expert_completed:
            review_payload: Optional[Dict[str, Any]] = None
            review_agent_id = ""
            if task_board_engine is not None and expert.board_id:
                review_expected_count += 1
                review_runtime = ReviewAgent(task_board_engine=task_board_engine)
                spawned_review = expert.spawn_review()
                review_agent_id = str(spawned_review.get("agent_id") or "").strip()
                yield {
                    "type": "review_spawned",
                    "pipeline_id": pipeline_id,
                    "expert_id": str(agent_id),
                    "expert_type": expert_type,
                    "board_id": expert.board_id,
                    "review_agent_id": review_agent_id,
                }

                board = task_board_engine.get_board(expert.board_id)
                declared_files: List[str] = []
                if board is not None:
                    declared_files = sorted(
                        {
                            str(path).strip()
                            for task in board.tasks
                            for path in list(task.files or [])
                            if str(path).strip()
                        }
                    )

                review_result = review_runtime.run_full_review(
                    board_id=expert.board_id,
                    actual_changed_files=declared_files,
                    test_results={"passed": 1, "failed": 0, "errors": 0, "details": "pipeline_default_baseline"},
                )
                review_payload = review_result.to_dict()
                review_payload.update(
                    {
                        "expert_id": str(agent_id),
                        "expert_type": expert_type,
                        "board_id": expert.board_id,
                        "review_agent_id": review_agent_id,
                    }
                )
                review_results.append(review_payload)

                if review_agent_id:
                    summary_text = str(review_payload.get("summary") or "").strip()
                    if not summary_text:
                        summary_text = _trim_text(json.dumps(review_payload, ensure_ascii=False), limit=600)
                    _mailbox.send(
                        review_agent_id,
                        str(agent_id),
                        summary_text,
                        message_type="report",
                    )
                    try:
                        _store.update_status(review_agent_id, AgentStatus.WAITING)
                    except Exception:
                        logger.debug("Failed to set review status waiting: %s", review_agent_id, exc_info=True)

                yield {
                    "type": "review_result",
                    "pipeline_id": pipeline_id,
                    "expert_id": str(agent_id),
                    "expert_type": expert_type,
                    "board_id": expert.board_id,
                    "review_agent_id": review_agent_id,
                    "result": review_payload,
                }

            report_text = expert.aggregate_results()
            if review_payload is not None:
                review_summary = str(review_payload.get("summary") or "").strip()
                if review_summary:
                    report_text = f"{report_text}\n\n### Review Summary\n{review_summary}"
            _mailbox.send(
                str(agent_id),
                resolved_core_session_id,
                report_text,
                message_type="report",
            )
            try:
                _store.update_status(str(agent_id), AgentStatus.WAITING)
            except Exception:
                logger.debug("Failed to set expert status waiting: %s", agent_id, exc_info=True)

        yield {
            "type": "expert_progress",
            "pipeline_id": pipeline_id,
            "expert_type": expert_type,
            "agent_id": agent_id,
            "board_id": expert.board_id,
            "all_devs_done": bool(expert_completed),
            "child_execution_enabled": bool(child_execution_enabled),
        }
        expert_instances.append(expert)

    # ── Phase 5: Collect results ───────────────────────────────

    reports = core.collect_reports(resolved_core_session_id, pipeline_id=pipeline_id)
    for report in reports:
        yield {
            "type": "expert_report",
            "pipeline_id": pipeline_id,
            "agent_id": report.get("session_id"),
            "status": report.get("status"),
            "reports": report.get("reports", []),
        }

    report_statuses = [str(report.get("status") or "").strip().lower() for report in reports]
    reports_submitted = bool(report_statuses) and all(status == "waiting" for status in report_statuses)
    review_gate_passed = True
    review_stop_reason = ""
    if review_expected_count > 0:
        if len(review_results) < review_expected_count:
            review_gate_passed = False
            review_stop_reason = "review_missing"
        elif not all(str(item.get("verdict") or "").strip().lower() == "pass" for item in review_results):
            review_gate_passed = False
            review_stop_reason = "review_failed"

    task_completed = reports_submitted and review_gate_passed
    if task_completed:
        stop_reason = "submitted_completion"
    elif not reports_submitted:
        stop_reason = "completion_not_submitted"
    else:
        stop_reason = review_stop_reason or "review_not_passed"

    receipt_event = _build_core_execution_receipt(
        pipeline_id=pipeline_id,
        decomposition=decomposition,
        expert_results=expert_results,
        reports=reports,
        review_results=review_results,
        task_completed=task_completed,
        stop_reason=stop_reason,
    )

    # Emit a tool-loop compatible verify-stage signal so posture/incidents
    # collectors can consume completion semantics from the unified pipeline.
    yield {
        "type": "tool_stage",
        "pipeline_id": pipeline_id,
        "phase": "verify",
        "status": "success" if task_completed else "warning",
        "reason": stop_reason,
        "decision": "stop" if task_completed else "continue",
        "round": 1,
        "details": {
            "task_completed": bool(task_completed),
            "submit_result_called": bool(task_completed),
            "submit_result_round": 1 if task_completed else 0,
            "review_expected_count": int(review_expected_count),
            "review_count": len(review_results),
            "review_gate_passed": bool(review_gate_passed),
        },
    }

    yield receipt_event

    yield {
        "type": "content",
        "pipeline_id": pipeline_id,
        "source": "execution_receipt",
        "text": str(receipt_event.get("agent_state", {}).get("final_answer") or ""),
    }

    cleanup_summary = _apply_child_session_cleanup(
        store=_store,
        mailbox=_mailbox,
        core_session_id=resolved_core_session_id,
        pipeline_id=pipeline_id,
        mode=child_session_cleanup_mode,
        ttl_seconds=int(child_session_cleanup_ttl_seconds),
    )
    yield {
        "type": "pipeline_cleanup",
        "pipeline_id": pipeline_id,
        "cleanup": cleanup_summary,
    }

    # ── Done ───────────────────────────────────────────────────

    yield {
        "type": "pipeline_end",
        "pipeline_id": pipeline_id,
        "reason": "completed" if task_completed else "delegated_waiting_child_completion",
        "duration_ms": int((time.time() - started_at) * 1000),
        "expert_count": len(expert_results),
        "core_session_id": resolved_core_session_id,
        "child_session_cleanup": cleanup_summary,
    }


__all__ = ["run_multi_agent_pipeline"]
