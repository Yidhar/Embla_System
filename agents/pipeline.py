"""Multi-Agent Pipeline — unified entry point for ALL requests.

Orchestrates: ShellAgent → (direct reply | CoreAgent → Expert(s) → Dev(s) → Review)
Yields events compatible with the existing event stream.

ShellAgent IS the shell-side LLM — it handles simple queries directly and only
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
from agents.memory.memory_tools import get_memory_tool_definitions, handle_memory_tool, is_memory_tool
from agents.runtime.agent_session import AgentSessionStore, AgentStatus
from agents.runtime.mailbox import AgentMailbox
from agents.runtime.task_board import TaskBoardEngine, TaskStatus

from agents.shell_agent import ShellAgent
from agents.core_agent import CoreAgent
from agents.expert_agent import ExpertAgent, ExpertAgentConfig
from agents.dev_agent import DevAgent, DevAgentConfig
from agents.review_agent import ReviewAgent, ReviewAgentConfig
from agents.runtime.mini_loop import MiniLoopConfig, run_mini_loop
from agents.runtime.parent_tools import get_parent_tool_definitions, handle_parent_tool_call
from system.git_worktree_sandbox import apply_workspace_path_overrides

logger = logging.getLogger(__name__)


ChildLLMCallFn = Callable[[List[Dict[str, Any]], List[Dict[str, Any]], str], Awaitable[Dict[str, Any]]]
ChildToolExecutorFn = Callable[[str, Dict[str, Any], str], Awaitable[Dict[str, Any]]]

_CORE_PARENT_TOOL_ALLOWLIST = {
    "spawn_child_agent",
    "poll_child_status",
    "resume_child_agent",
    "destroy_child_agent",
}

_CORE_SPAWN_ROLE_ALLOWLIST = {"dev", "expert", "review"}
_FAST_TRACK_BLOCKED_TOOLS = {
    "run_command",
    "exec_shell",
    "run_cmd",
    "os_bash",
    "python_repl",
    "write_config",
    "delete_file",
    "workspace_txn_apply",
    "git_checkout_file",
}
_FAST_TRACK_PROTECTED_PREFIXES = (
    "core/security/",
    "system/dna/",
)
_FAST_TRACK_PROTECTED_EXACT = {
    ".env",
    "config.json",
}
_MAX_REVIEW_REMEDIATION_CYCLES = 3
_MAX_REVIEW_REJECT_RESPAWNS = 1


def _trim_text(value: Any, *, limit: int = 220) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _extract_report_text(report: Dict[str, Any]) -> str:
    rows = report.get("reports")
    if isinstance(rows, list):
        for item in reversed(rows):
            if isinstance(item, str) and item.strip():
                return _trim_text(item)
            if isinstance(item, dict):
                try:
                    return _trim_text(json.dumps(item, ensure_ascii=False))
                except Exception:
                    continue
    return ""


def _normalize_changed_files(raw_files: Any) -> List[str]:
    if not isinstance(raw_files, list):
        return []
    return sorted({str(item).strip() for item in raw_files if str(item).strip()})


def _prepare_child_tool_arguments(
    *,
    store: AgentSessionStore,
    child_session_id: str,
    tool_name: str,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    session = store.get(child_session_id)
    if session is None:
        return dict(arguments) if isinstance(arguments, dict) else {}
    workspace_root = str(session.metadata.get("workspace_root") or "").strip()
    if not workspace_root:
        return dict(arguments) if isinstance(arguments, dict) else {}
    return apply_workspace_path_overrides(tool_name, arguments, workspace_root)


def _collect_expert_dev_artifacts(store: AgentSessionStore, expert_id: str) -> List[Dict[str, Any]]:
    artifacts: List[Dict[str, Any]] = []
    for child in store.list_children(expert_id):
        if str(child.role or "").strip().lower() != "dev":
            continue
        verification_report = child.metadata.get("verification_report")
        if not isinstance(verification_report, dict):
            verification_report = {}
        changed_files = _normalize_changed_files(
            verification_report.get("changed_files") if verification_report else child.metadata.get("changed_files")
        )
        artifacts.append(
            {
                "agent_id": child.session_id,
                "status": str(child.status.value),
                "completion_report": str(child.metadata.get("completion_report") or "").strip(),
                "verification_report": dict(verification_report),
                "changed_files": changed_files,
                "task_updates": dict(child.metadata.get("task_updates") or {}),
            }
        )
    return artifacts


def _build_aggregate_test_results(dev_artifacts: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "passed": sum(
            int((((artifact.get("verification_report") or {}).get("tests") or {}).get("passed", 0)) or 0)
            for artifact in dev_artifacts
        ),
        "failed": sum(
            int((((artifact.get("verification_report") or {}).get("tests") or {}).get("failed", 0)) or 0)
            for artifact in dev_artifacts
        ),
        "errors": sum(
            int((((artifact.get("verification_report") or {}).get("tests") or {}).get("errors", 0)) or 0)
            for artifact in dev_artifacts
        ),
        "details": "aggregated_from_dev_verification_reports",
    }


def _build_review_rework_instruction(
    *,
    original_task: str,
    review_payload: Dict[str, Any],
    review_cycle: int,
) -> str:
    issues = [str(item).strip() for item in list(review_payload.get("issues") or []) if str(item).strip()]
    suggestions = [str(item).strip() for item in list(review_payload.get("suggestions") or []) if str(item).strip()]
    summary = str(review_payload.get("summary") or "").strip()
    parts = [
        f"Review cycle {max(1, int(review_cycle))} requested changes.",
        "Please address the reviewer feedback, rerun your self-verification, and report completed again with an updated verification_report.",
    ]
    if original_task:
        parts.append(f"Original task:\n{original_task}")
    if summary:
        parts.append(f"Review summary:\n{summary}")
    if issues:
        parts.append("Issues to fix:\n" + "\n".join(f"- {item}" for item in issues))
    if suggestions:
        parts.append("Reviewer suggestions:\n" + "\n".join(f"- {item}" for item in suggestions))
    return "\n\n".join(part for part in parts if part).strip()


def _inject_system_instruction(store: AgentSessionStore, session_id: str, content: str) -> None:
    text = str(content or "").strip()
    if not text:
        return
    session = store.get(session_id)
    if session is None:
        return
    messages = list(session.messages or [])
    messages.append({"role": "system", "content": f"[Parent resume instruction] {text}"})
    store.save_messages(session_id, messages)


def _is_review_reject_recoverable(review_payload: Dict[str, Any]) -> bool:
    verdict = str(review_payload.get("verdict") or "").strip().lower()
    if verdict != "reject":
        return False
    corpus_parts = [
        str(review_payload.get("summary") or ""),
        *(str(item) for item in list(review_payload.get("issues") or [])),
        *(str(item) for item in list(review_payload.get("suggestions") or [])),
    ]
    corpus = " ".join(part.strip().lower() for part in corpus_parts if str(part).strip())
    unrecoverable_markers = (
        "review agent did not emit a valid review_result",
        "no valid review_result",
        "malformed review_result",
        "missing review_result",
        "insufficient context to review",
        "no dev agents were available",
    )
    return not any(marker in corpus for marker in unrecoverable_markers)


def _select_reject_respawn_task_ids(tasks: List[Any], changed_files: List[str]) -> List[str]:
    normalized_changed_files = {str(path).strip() for path in changed_files if str(path).strip()}
    if not normalized_changed_files:
        return [str(getattr(task, "task_id", "") or "").strip() for task in tasks if str(getattr(task, "task_id", "") or "").strip()]
    selected: List[str] = []
    for task in tasks:
        task_id = str(getattr(task, "task_id", "") or "").strip()
        task_files = {str(path).strip() for path in list(getattr(task, "files", []) or []) if str(path).strip()}
        if task_id and (not task_files or task_files & normalized_changed_files):
            selected.append(task_id)
    return selected or [str(getattr(task, "task_id", "") or "").strip() for task in tasks if str(getattr(task, "task_id", "") or "").strip()]


def _build_review_reject_respawn_instruction(
    *,
    original_task: str,
    review_payload: Dict[str, Any],
    review_cycle: int,
) -> str:
    issues = [str(item).strip() for item in list(review_payload.get("issues") or []) if str(item).strip()]
    suggestions = [str(item).strip() for item in list(review_payload.get("suggestions") or []) if str(item).strip()]
    summary = str(review_payload.get("summary") or "").strip()
    parts = [
        f"Review cycle {max(1, int(review_cycle))} rejected the current implementation.",
        "Start a fresh remediation pass. Re-evaluate the approach, do not blindly preserve the previous solution, and complete full self-verification before reporting completed.",
    ]
    if original_task:
        parts.append(f"Original task:\n{original_task}")
    if summary:
        parts.append(f"Review rejection summary:\n{summary}")
    if issues:
        parts.append("Blocking issues:\n" + "\n".join(f"- {item}" for item in issues))
    if suggestions:
        parts.append("Reviewer suggestions:\n" + "\n".join(f"- {item}" for item in suggestions))
    return "\n\n".join(part for part in parts if part).strip()


def _normalize_fast_track_tool_name(raw: str) -> str:
    text = str(raw or "").strip().lower()
    aliases = {
        "os_bash": "run_cmd",
        "command": "run_cmd",
        "cmd": "run_cmd",
        "search": "search_keyword",
        "grep": "search_keyword",
        "file_ast": "file_ast_skeleton",
    }
    return aliases.get(text, text)


def _normalize_fast_track_path(raw_path: str) -> str:
    return str(raw_path or "").strip().replace("\\", "/").lstrip("./").lower()


def _is_fast_track_protected_path(raw_path: str) -> bool:
    normalized = _normalize_fast_track_path(raw_path)
    if not normalized:
        return False
    if normalized in _FAST_TRACK_PROTECTED_EXACT:
        return True
    return any(normalized.startswith(prefix) for prefix in _FAST_TRACK_PROTECTED_PREFIXES)


def _extract_tool_path(arguments: Dict[str, Any]) -> str:
    if not isinstance(arguments, dict):
        return ""
    for key in ("path", "file_path", "target_path"):
        value = arguments.get(key)
        if value:
            return str(value)
    return ""


def _build_fast_track_execution_receipt(
    *,
    pipeline_id: str,
    goal: str,
    reports: List[Dict[str, Any]],
    task_completed: bool,
    stop_reason: str,
    fast_track_agent_id: str,
    complexity_hint: str,
    guard_blocked_count: int,
    touched_files: List[str],
) -> Dict[str, Any]:
    summary_lines: List[str] = []
    deliverables: List[str] = []
    for report in reports:
        status = str(report.get("status") or "unknown").strip()
        agent_id = str(report.get("session_id") or report.get("agent_id") or "").strip() or "fast_track_dev"
        report_text = _extract_report_text(report)
        if report_text:
            summary_lines.append(f"- [{status}] {agent_id}: {report_text}")
            deliverables.append(report_text)
        else:
            summary_lines.append(f"- [{status}] {agent_id}: report_received")

    if not summary_lines:
        summary_lines.append("- [info] no fast-track report payload was produced")

    if task_completed:
        header = "Core fast-track execution completed."
    else:
        header = "Core fast-track execution did not reach completed state."

    final_answer = "\n".join(
        [
            header,
            f"Goal: {str(goal or '').strip()}",
            f"Fast-track agent: {fast_track_agent_id or 'unknown'}",
            f"Complexity hint: {complexity_hint}",
            f"Guard blocked calls: {int(guard_blocked_count)}",
            f"Touched files: {', '.join(touched_files) if touched_files else '(none)'}",
            *summary_lines[:8],
        ]
    ).strip()

    return {
        "type": "execution_receipt",
        "pipeline_id": pipeline_id,
        "stop_reason": str(stop_reason or ""),
        "agent_state": {
            "task_completed": bool(task_completed),
            "final_answer": final_answer,
            "completion_summary": final_answer,
            "deliverables": deliverables[:12],
            "execution_mode": "fast_track",
            "fast_track_agent_id": str(fast_track_agent_id or ""),
            "goal_id": "",
            "review_count": 0,
            "review_verdicts": [],
            "guard_blocked_count": int(guard_blocked_count),
            "touched_files": list(touched_files),
        },
    }


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
    core_execution_session_id: str,
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
        "core_execution_session_id": str(core_execution_session_id or ""),
        "pipeline_id": str(pipeline_id or ""),
        "root_candidates": 0,
        "destroyed_count": 0,
        "purged_message_count": 0,
        "destroyed_session_ids": [],
    }
    if normalized_mode == "retain":
        return summary

    roots = store.list_children(core_execution_session_id)
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
        if is_memory_tool(tool_name):
            definitions.extend(get_memory_tool_definitions([tool_name]))
            continue
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


def _ensure_core_runtime_session(
    *,
    store: AgentSessionStore,
    core_execution_session_id: str,
    goal: str,
    pipeline_id: str,
) -> None:
    existing = store.get(core_execution_session_id)
    if existing is None:
        metadata = {"pipeline_id": str(pipeline_id or "").strip()}
        store.create(
            session_id=core_execution_session_id,
            role="core",
            parent_id="",
            task_description=str(goal or "").strip(),
            metadata=metadata,
        )
        return
    if existing.status != AgentStatus.RUNNING:
        try:
            store.update_status(core_execution_session_id, AgentStatus.RUNNING)
        except Exception:
            logger.debug("Failed to set core runtime session running: %s", core_execution_session_id, exc_info=True)
    try:
        store.update_metadata(core_execution_session_id, {"pipeline_id": str(pipeline_id or "").strip()})
    except Exception:
        logger.debug("Failed to update core runtime session metadata: %s", core_execution_session_id, exc_info=True)


def _build_core_parent_tool_definitions() -> List[Dict[str, Any]]:
    allowed = set(_CORE_PARENT_TOOL_ALLOWLIST)
    definitions: List[Dict[str, Any]] = []
    for item in get_parent_tool_definitions():
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name in allowed:
            definitions.append(dict(item))
    return definitions


def _collect_core_descendant_status_snapshot(
    *,
    store: AgentSessionStore,
    core_execution_session_id: str,
) -> List[Dict[str, Any]]:
    root_children = store.list_children(core_execution_session_id)
    root_ids = [str(getattr(item, "session_id", "") or "").strip() for item in root_children]
    descendant_ids = _collect_descendant_session_ids(
        store=store,
        root_session_ids=[item for item in root_ids if item],
    )
    snapshot: List[Dict[str, Any]] = []
    for session_id in descendant_ids:
        session = store.get(session_id)
        if session is None:
            continue
        row = session.to_status_summary()
        row["parent_id"] = str(session.parent_id or "")
        snapshot.append(row)
    return snapshot


def _build_core_loop_initial_task(
    *,
    message: str,
    core_execution_session_id: str,
    pipeline_id: str,
    children_snapshot: List[Dict[str, Any]],
) -> str:
    roster_lines: List[str] = []
    for child in children_snapshot[:36]:
        child_id = str(child.get("agent_id") or "").strip()
        role = str(child.get("role") or "").strip()
        status = str(child.get("status") or "").strip()
        parent_id = str(child.get("parent_id") or "").strip()
        task_desc = _trim_text(child.get("task_description") or "", limit=120)
        parent_text = f" | parent={parent_id}" if parent_id else ""
        roster_lines.append(f"- {child_id} | role={role} | status={status}{parent_text} | task={task_desc}")

    if not roster_lines:
        roster_lines.append("- no_active_children")

    return "\n".join(
        [
            "You are the Core lifecycle orchestrator for this pipeline run.",
            (
                "Decide child lifecycle using only parent tools: "
                "spawn_child_agent / poll_child_status / resume_child_agent / destroy_child_agent."
            ),
            "Allowed spawn roles in this phase: dev, expert, review.",
            "For expert/review spawns, runtime may defer execution to later requests.",
            "Do not use any other tools.",
            f"Pipeline ID: {pipeline_id}",
            f"Core Session ID: {core_execution_session_id}",
            f"Goal: {str(message or '').strip()}",
            "Current descendant roster:",
            *roster_lines,
            "If no action is needed, return without tool calls.",
        ]
    ).strip()


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
    forced_route_semantic: str = "",
    core_execution_session_id: str = "",
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
        - dev_review_resume_start
        - dev_review_resume_event
        - dev_review_resume_end
        - expert_report
        - expert_blocked
        - review_spawned
        - review_loop_start
        - review_loop_event
        - review_loop_end
        - review_rework_requested
        - review_reject_respawn
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

    normalized_forced_route_semantic = str(forced_route_semantic or "").strip().lower()
    if normalized_forced_route_semantic == "core_execution":
        needs_core = True
    elif normalized_forced_route_semantic in {"shell_readonly", "shell_clarify"}:
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
        "complexity_hint": str(getattr(decision, "complexity_hint", "") or ""),
        "core_route": str(getattr(decision, "core_route", "") or ""),
        "fast_track_candidate": bool(getattr(decision, "fast_track_candidate", False)),
    }

    # ── Shell direct reply (no Core dispatch needed) ───────────
    if not needs_core:
        # Shell handles directly: yield content event with the user message
        # for the shell-side LLM to process with Shell's system prompt.
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
            "complexity_hint": str(getattr(decision, "complexity_hint", "") or ""),
            "core_route": str(getattr(decision, "core_route", "") or ""),
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
    core_route_plan = core.plan_execution_route(dispatch)
    dispatch["complexity_hint"] = str(core_route_plan.get("complexity_hint") or "standard")
    dispatch["core_route"] = str(core_route_plan.get("route") or "standard")

    yield {
        "type": "core_route_selected",
        "pipeline_id": pipeline_id,
        "core_route": str(core_route_plan.get("route") or "standard"),
        "complexity_hint": str(core_route_plan.get("complexity_hint") or "standard"),
        "fast_track_eligible": bool(core_route_plan.get("fast_track_eligible")),
        "reason_codes": list(core_route_plan.get("reason_codes") or []),
        "max_files": int(core_route_plan.get("max_files") or 1),
        "max_changed_lines": int(core_route_plan.get("max_changed_lines") or 10),
    }

    # ── Phase 2A: Fast-Track direct execution ─────────────────

    resolved_core_execution_session_id = str(core_execution_session_id or "").strip() or str(session_id or "").strip()
    if not resolved_core_execution_session_id:
        resolved_core_execution_session_id = f"core_{pipeline_id}"
    _ensure_core_runtime_session(
        store=_store,
        core_execution_session_id=resolved_core_execution_session_id,
        goal=message,
        pipeline_id=pipeline_id,
    )
    runtime_child_execution_enabled = bool(
        enable_child_execution and child_llm_call is not None and child_tool_executor is not None
    )

    if str(core_route_plan.get("route") or "") == "fast_track":
        if not runtime_child_execution_enabled:
            yield {
                "type": "fast_track_fallback",
                "pipeline_id": pipeline_id,
                "reason": "fast_track_runtime_unavailable",
                "target_route": "standard",
            }
        else:
            fast_track_tools = list(core_route_plan.get("tool_subset") or [])
            max_files = max(1, int(core_route_plan.get("max_files") or 1))
            max_changed_lines = max(1, int(core_route_plan.get("max_changed_lines") or 10))

            fast_track_spawn_args = {
                "role": "dev",
                "task_description": str(dispatch.get("goal") or message),
                "prompt_blocks": [],
                "tool_subset": fast_track_tools,
                "metadata": {
                    "pipeline_id": str(pipeline_id),
                    "execution_mode": "fast_track",
                },
            }
            if str(dispatch.get("target_repo") or "").strip().lower() == "self":
                fast_track_spawn_args["workspace_mode"] = "worktree"
            spawn_result = handle_parent_tool_call(
                "spawn_child_agent",
                fast_track_spawn_args,
                parent_session_id=resolved_core_execution_session_id,
                store=_store,
                mailbox=_mailbox,
            )
            fast_track_agent_id = str(spawn_result.get("agent_id") or "").strip()
            if not fast_track_agent_id:
                yield {
                    "type": "fast_track_fallback",
                    "pipeline_id": pipeline_id,
                    "reason": "fast_track_spawn_failed",
                    "target_route": "standard",
                    "spawn_result": spawn_result,
                }
            else:
                touched_files: set[str] = set()
                guard_blocked_details: List[Dict[str, Any]] = []

                async def _execute_fast_track_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
                    normalized_tool = _normalize_fast_track_tool_name(tool_name)
                    safe_arguments = dict(arguments) if isinstance(arguments, dict) else {}
                    if normalized_tool in _FAST_TRACK_BLOCKED_TOOLS:
                        reason = "blocked_tool"
                        guard_blocked_details.append({"tool_name": normalized_tool, "reason": reason})
                        return {
                            "error": "fast_track_guard_blocked",
                            "reason": reason,
                            "tool_name": normalized_tool,
                        }
                    if fast_track_tools and normalized_tool not in set(fast_track_tools):
                        reason = "tool_not_in_fast_track_profile"
                        guard_blocked_details.append({"tool_name": normalized_tool, "reason": reason})
                        return {
                            "error": "fast_track_guard_blocked",
                            "reason": reason,
                            "tool_name": normalized_tool,
                        }

                    candidate_path = _extract_tool_path(safe_arguments)
                    normalized_path = _normalize_fast_track_path(candidate_path)
                    mutating_tools = {"write_file", "workspace_txn_apply", "git_checkout_file"}
                    if normalized_tool in mutating_tools and normalized_path:
                        if _is_fast_track_protected_path(normalized_path):
                            reason = "protected_path"
                            guard_blocked_details.append(
                                {"tool_name": normalized_tool, "reason": reason, "path": normalized_path}
                            )
                            return {
                                "error": "fast_track_guard_blocked",
                                "reason": reason,
                                "tool_name": normalized_tool,
                                "path": normalized_path,
                            }
                        touched_files.add(normalized_path)
                        if len(touched_files) > max_files:
                            reason = "multi_file_limit_exceeded"
                            guard_blocked_details.append({"tool_name": normalized_tool, "reason": reason})
                            return {
                                "error": "fast_track_guard_blocked",
                                "reason": reason,
                                "tool_name": normalized_tool,
                                "max_files": max_files,
                            }

                    if normalized_tool == "write_file":
                        content = str(safe_arguments.get("content") or "")
                        changed_lines = len(content.splitlines())
                        if changed_lines > max_changed_lines:
                            reason = "line_limit_exceeded"
                            guard_blocked_details.append(
                                {
                                    "tool_name": normalized_tool,
                                    "reason": reason,
                                    "changed_lines": changed_lines,
                                    "max_changed_lines": max_changed_lines,
                                }
                            )
                            return {
                                "error": "fast_track_guard_blocked",
                                "reason": reason,
                                "tool_name": normalized_tool,
                                "changed_lines": changed_lines,
                                "max_changed_lines": max_changed_lines,
                            }

                    prepared_arguments = _prepare_child_tool_arguments(store=_store, child_session_id=fast_track_agent_id, tool_name=normalized_tool, arguments=safe_arguments)
                    return await child_tool_executor(normalized_tool, prepared_arguments, fast_track_agent_id)

                dev_agent = DevAgent(
                    config=DevAgentConfig(
                        prompt_blocks=[],
                        tool_subset=fast_track_tools,
                        prompts_root="system/prompts",
                    ),
                    session_id=fast_track_agent_id,
                    store=_store,
                    mailbox=_mailbox,
                )
                fast_track_loop_config = MiniLoopConfig(
                    max_rounds=max(1, min(int(child_max_rounds), 6)),
                    poll_parent_every_n=3,
                )

                yield {
                    "type": "fast_track_start",
                    "pipeline_id": pipeline_id,
                    "core_execution_session_id": resolved_core_execution_session_id,
                    "agent_id": fast_track_agent_id,
                    "tool_subset": list(fast_track_tools),
                    "max_files": max_files,
                    "max_changed_lines": max_changed_lines,
                }

                async for mini_event in run_mini_loop(
                    session_id=fast_track_agent_id,
                    store=_store,
                    mailbox=_mailbox,
                    llm_call=child_llm_call,
                    tool_executor=_execute_fast_track_tool,
                    tool_definitions=_build_runtime_tool_definitions(fast_track_tools),
                    system_prompt=dev_agent.build_system_prompt(),
                    initial_task=str(dispatch.get("goal") or message),
                    config=fast_track_loop_config,
                ):
                    yield {
                        "type": "fast_track_event",
                        "pipeline_id": pipeline_id,
                        "core_execution_session_id": resolved_core_execution_session_id,
                        "agent_id": fast_track_agent_id,
                        "event": mini_event,
                    }

                fast_track_session = _store.get(fast_track_agent_id)
                fast_track_status = (
                    str(fast_track_session.status.value) if fast_track_session is not None else "missing"
                )
                fast_track_completed = fast_track_status == AgentStatus.WAITING.value
                stop_reason = "submitted_completion" if fast_track_completed else "completion_not_submitted"
                if guard_blocked_details and not fast_track_completed:
                    stop_reason = "fast_track_guard_blocked"

                reports = core.collect_reports(resolved_core_execution_session_id, pipeline_id=pipeline_id)
                receipt_event = _build_fast_track_execution_receipt(
                    pipeline_id=pipeline_id,
                    goal=str(dispatch.get("goal") or message),
                    reports=reports,
                    task_completed=fast_track_completed,
                    stop_reason=stop_reason,
                    fast_track_agent_id=fast_track_agent_id,
                    complexity_hint=str(core_route_plan.get("complexity_hint") or "standard"),
                    guard_blocked_count=len(guard_blocked_details),
                    touched_files=sorted(touched_files),
                )

                yield {
                    "type": "tool_stage",
                    "pipeline_id": pipeline_id,
                    "phase": "verify",
                    "status": "success" if fast_track_completed else "warning",
                    "reason": stop_reason,
                    "decision": "stop" if fast_track_completed else "continue",
                    "round": 1,
                    "details": {
                        "task_completed": bool(fast_track_completed),
                        "submit_result_called": bool(fast_track_completed),
                        "submit_result_round": 1 if fast_track_completed else 0,
                        "execution_mode": "fast_track",
                        "guard_blocked_count": len(guard_blocked_details),
                    },
                }
                yield receipt_event
                yield {
                    "type": "content",
                    "pipeline_id": pipeline_id,
                    "source": "execution_receipt",
                    "text": str(receipt_event.get("agent_state", {}).get("final_answer") or ""),
                }
                yield {
                    "type": "fast_track_summary",
                    "pipeline_id": pipeline_id,
                    "core_execution_session_id": resolved_core_execution_session_id,
                    "agent_id": fast_track_agent_id,
                    "status": fast_track_status,
                    "guard_blocked_count": len(guard_blocked_details),
                    "guard_blocked_details": guard_blocked_details[:10],
                    "touched_files": sorted(touched_files),
                }

                cleanup_summary = _apply_child_session_cleanup(
                    store=_store,
                    mailbox=_mailbox,
                    core_execution_session_id=resolved_core_execution_session_id,
                    pipeline_id=pipeline_id,
                    mode=child_session_cleanup_mode,
                    ttl_seconds=int(child_session_cleanup_ttl_seconds),
                )
                yield {
                    "type": "pipeline_cleanup",
                    "pipeline_id": pipeline_id,
                    "cleanup": cleanup_summary,
                }
                yield {
                    "type": "pipeline_end",
                    "pipeline_id": pipeline_id,
                    "reason": "completed" if fast_track_completed else "delegated_waiting_child_completion",
                    "duration_ms": int((time.time() - started_at) * 1000),
                    "expert_count": 0,
                    "core_execution_session_id": resolved_core_execution_session_id,
                    "child_session_cleanup": cleanup_summary,
                    "execution_mode": "fast_track",
                }
                return

    # ── Phase 2B: Standard route (decompose + experts) ────────

    decomposition = core.decompose_goal(dispatch)

    yield {
        "type": "core_decomposition",
        "pipeline_id": pipeline_id,
        "goal_id": decomposition.get("goal_id"),
        "expert_count": len(decomposition.get("expert_assignments", [])),
        "subtask_count": decomposition.get("subtask_count", 0),
        "model_tier": decomposition.get("model_tier"),
        "core_route": "standard",
    }

    # ── Phase 3: Spawn Experts ─────────────────────────────────

    expert_results = core.spawn_experts(
        decomposition,
        core_execution_session_id=resolved_core_execution_session_id,
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
        dev_task_map: Dict[str, str] = {}
        if tasks:
            devs = expert.spawn_devs(tasks)
            dev_task_map = {
                str(item.get("agent_id") or "").strip(): str(item.get("task_id") or "").strip()
                for item in devs
                if str(item.get("agent_id") or "").strip()
            }
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
                    if is_memory_tool(normalized_tool):
                        return handle_memory_tool(normalized_tool, safe_arguments)
                    prepared_arguments = _prepare_child_tool_arguments(store=_store, child_session_id=_dev_session_id, tool_name=normalized_tool, arguments=safe_arguments)
                    return await child_tool_executor(normalized_tool, prepared_arguments, _dev_session_id)

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
                verification_report: Dict[str, Any] = {}
                changed_files: List[str] = []
                if final_session is not None:
                    completion_report = str(final_session.metadata.get("completion_report") or "").strip()
                    raw_verification_report = final_session.metadata.get("verification_report")
                    if isinstance(raw_verification_report, dict):
                        verification_report = dict(raw_verification_report)
                    changed_files = _normalize_changed_files(
                        verification_report.get("changed_files") if verification_report else final_session.metadata.get("changed_files")
                    )

                if task_board_engine is not None and expert.board_id and task_id:
                    try:
                        if final_status == AgentStatus.WAITING.value:
                            task_board_engine.update_task(
                                expert.board_id,
                                task_id,
                                status=TaskStatus.DONE,
                                summary=completion_report or "child loop completed",
                                files_changed=changed_files if changed_files else None,
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
                    "verification_report": verification_report,
                    "changed_files": changed_files,
                }

        expert_progress = expert.check_progress()
        expert_completed = bool(expert_progress.get("all_devs_done"))
        if not tasks:
            expert_completed = True

        if expert_completed:
            review_payload: Optional[Dict[str, Any]] = None
            final_review_payload: Optional[Dict[str, Any]] = None
            review_agent_id = ""
            if task_board_engine is not None and expert.board_id:
                review_expected_count += 1
                original_task_text = str(decomposition.get("original_goal") or message)
                review_cycle_limit = _MAX_REVIEW_REMEDIATION_CYCLES if child_execution_enabled else 1
                reject_respawn_budget = _MAX_REVIEW_REJECT_RESPAWNS if child_execution_enabled else 0
                reject_respawn_count = 0
                expert_blocked_reason = ""
                for review_cycle in range(1, review_cycle_limit + 1):
                    review_payload = None
                    review_agent_id = ""
                    dev_artifacts = _collect_expert_dev_artifacts(_store, str(agent_id))
                    changed_files = sorted(
                        {
                            path
                            for artifact in dev_artifacts
                            for path in list(artifact.get("changed_files") or [])
                            if str(path).strip()
                        }
                    )
                    aggregate_test_results = _build_aggregate_test_results(dev_artifacts)
                    spawned_review = expert.spawn_review(
                        original_task=original_task_text,
                        changed_files=changed_files,
                        verification_reports=dev_artifacts,
                        cycle=review_cycle,
                    )
                    review_agent_id = str(spawned_review.get("agent_id") or "").strip()
                    yield {
                        "type": "review_spawned",
                        "pipeline_id": pipeline_id,
                        "expert_id": str(agent_id),
                        "expert_type": expert_type,
                        "board_id": expert.board_id,
                        "review_agent_id": review_agent_id,
                        "review_cycle": review_cycle,
                    }

                    if child_execution_enabled and child_llm_call is not None and child_tool_executor is not None and review_agent_id:
                        review_session = _store.get(review_agent_id)
                        review_tool_subset = list(review_session.tool_subset or []) if review_session is not None else []
                        review_prompt_blocks = list(review_session.prompt_blocks or []) if review_session is not None else []
                        review_memory_hints = []
                        if review_session is not None:
                            raw_hints = review_session.metadata.get("memory_hints")
                            if isinstance(raw_hints, list):
                                review_memory_hints = [str(item).strip() for item in raw_hints if str(item).strip()]
                        review_runtime = ReviewAgent(
                            config=ReviewAgentConfig(
                                prompt_blocks=review_prompt_blocks,
                                memory_hints=review_memory_hints,
                                prompts_root="system/prompts",
                            ),
                            task_board_engine=task_board_engine,
                        )
                        review_runtime_tool_defs = _build_runtime_tool_definitions(review_tool_subset)
                        review_allowed_tools = {str(item).strip() for item in review_tool_subset if str(item).strip()}
                        review_initial_task = "Review the completed work and produce a structured review_result."
                        if review_session is not None and str(review_session.task_description or "").strip():
                            review_initial_task = str(review_session.task_description or "").strip()
                        review_loop_config = MiniLoopConfig(
                            max_rounds=max(1, min(int(child_max_rounds), 6)),
                            poll_parent_every_n=3,
                        )

                        async def _execute_review_tool(tool_name, arguments, _review_session_id=review_agent_id):
                            normalized_tool = str(tool_name or "").strip()
                            if normalized_tool not in review_allowed_tools:
                                return {
                                    "error": f"tool_not_allowed:{normalized_tool}",
                                    "status": "blocked",
                                    "tool_name": normalized_tool,
                                }
                            safe_arguments = arguments if isinstance(arguments, dict) else {}
                            if is_memory_tool(normalized_tool):
                                return handle_memory_tool(normalized_tool, safe_arguments)
                            prepared_arguments = _prepare_child_tool_arguments(store=_store, child_session_id=_review_session_id, tool_name=normalized_tool, arguments=safe_arguments)
                            return await child_tool_executor(normalized_tool, prepared_arguments, _review_session_id)

                        yield {
                            "type": "review_loop_start",
                            "pipeline_id": pipeline_id,
                            "expert_id": str(agent_id),
                            "expert_type": expert_type,
                            "board_id": expert.board_id,
                            "review_agent_id": review_agent_id,
                            "tool_subset": review_tool_subset,
                            "review_cycle": review_cycle,
                        }
                        async for mini_event in run_mini_loop(
                            session_id=review_agent_id,
                            store=_store,
                            mailbox=_mailbox,
                            llm_call=child_llm_call,
                            tool_executor=_execute_review_tool,
                            tool_definitions=review_runtime_tool_defs,
                            system_prompt=review_runtime.build_system_prompt(),
                            initial_task=review_initial_task,
                            config=review_loop_config,
                        ):
                            yield {
                                "type": "review_loop_event",
                                "pipeline_id": pipeline_id,
                                "expert_id": str(agent_id),
                                "expert_type": expert_type,
                                "board_id": expert.board_id,
                                "review_agent_id": review_agent_id,
                                "review_cycle": review_cycle,
                                "event": mini_event,
                            }

                        final_review_session = _store.get(review_agent_id)
                        final_review_status = str(final_review_session.status.value) if final_review_session is not None else "missing"
                        review_completion_report = ""
                        if final_review_session is not None:
                            review_completion_report = str(final_review_session.metadata.get("completion_report") or "").strip()
                            raw_review_payload = final_review_session.metadata.get("review_result")
                            if isinstance(raw_review_payload, dict):
                                review_payload = dict(raw_review_payload)
                        if not isinstance(review_payload, dict):
                            review_payload = {
                                "verdict": "reject",
                                "requirement_alignment": [],
                                "code_quality": {"status": "failed", "summary": "Review agent did not emit a valid review_result."},
                                "regression_risk": {"level": "high", "summary": "No valid review_result was produced."},
                                "test_coverage": {"status": "unknown", "summary": "No valid review_result was produced.", "missing_cases": []},
                                "issues": ["Review agent completed without a valid review_result payload."],
                                "suggestions": ["Rerun the independent review with a valid structured completion payload."],
                                "summary": review_completion_report or "Review agent failed to produce a valid structured review result.",
                            }
                        yield {
                            "type": "review_loop_end",
                            "pipeline_id": pipeline_id,
                            "expert_id": str(agent_id),
                            "expert_type": expert_type,
                            "board_id": expert.board_id,
                            "review_agent_id": review_agent_id,
                            "review_cycle": review_cycle,
                            "status": final_review_status,
                            "completion_report": review_completion_report,
                            "result": review_payload,
                        }
                    else:
                        review_runtime = ReviewAgent(task_board_engine=task_board_engine)
                        review_result = review_runtime.run_full_review(
                            board_id=expert.board_id,
                            actual_changed_files=changed_files,
                            test_results=aggregate_test_results,
                        )
                        review_payload = review_result.to_dict()
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

                    if isinstance(review_payload, dict):
                        review_payload.update(
                            {
                                "expert_id": str(agent_id),
                                "expert_type": expert_type,
                                "board_id": expert.board_id,
                                "review_agent_id": review_agent_id,
                                "review_cycle": review_cycle,
                            }
                        )
                        yield {
                            "type": "review_result",
                            "pipeline_id": pipeline_id,
                            "expert_id": str(agent_id),
                            "expert_type": expert_type,
                            "board_id": expert.board_id,
                            "review_agent_id": review_agent_id,
                            "review_cycle": review_cycle,
                            "result": review_payload,
                        }

                    verdict = str((review_payload or {}).get("verdict") or "").strip().lower()
                    if verdict == "approve":
                        final_review_payload = dict(review_payload or {})
                        break

                    if verdict == "reject":
                        recoverable_reject = _is_review_reject_recoverable(review_payload or {})
                        can_respawn = bool(recoverable_reject and reject_respawn_count < reject_respawn_budget and child_execution_enabled)
                        if not can_respawn:
                            expert_blocked_reason = "review_rejected_unrecoverable" if not recoverable_reject else "review_rejected_respawn_exhausted"
                            final_review_payload = dict(review_payload or {})
                            yield {
                                "type": "expert_blocked",
                                "pipeline_id": pipeline_id,
                                "expert_id": str(agent_id),
                                "expert_type": expert_type,
                                "board_id": expert.board_id,
                                "reason": expert_blocked_reason,
                                "review_cycle": review_cycle,
                                "review_agent_id": review_agent_id,
                                "result": final_review_payload,
                            }
                            break

                        respawn_task_ids = _select_reject_respawn_task_ids(tasks, changed_files)
                        if not respawn_task_ids:
                            expert_blocked_reason = "review_rejected_no_respawn_tasks"
                            final_review_payload = dict(review_payload or {})
                            yield {
                                "type": "expert_blocked",
                                "pipeline_id": pipeline_id,
                                "expert_id": str(agent_id),
                                "expert_type": expert_type,
                                "board_id": expert.board_id,
                                "reason": expert_blocked_reason,
                                "review_cycle": review_cycle,
                                "review_agent_id": review_agent_id,
                                "result": final_review_payload,
                            }
                            break

                        reject_respawn_count += 1
                        respawn_instruction = _build_review_reject_respawn_instruction(
                            original_task=original_task_text,
                            review_payload=review_payload or {},
                            review_cycle=review_cycle,
                        )
                        respawned_devs = expert.spawn_retry_devs(
                            tasks,
                            task_ids=respawn_task_ids,
                            review_feedback=respawn_instruction,
                            prompt_blocks=assignment.get("prompt_blocks", []),
                        )
                        if not respawned_devs:
                            expert_blocked_reason = "review_rejected_respawn_failed"
                            final_review_payload = dict(review_payload or {})
                            yield {
                                "type": "expert_blocked",
                                "pipeline_id": pipeline_id,
                                "expert_id": str(agent_id),
                                "expert_type": expert_type,
                                "board_id": expert.board_id,
                                "reason": expert_blocked_reason,
                                "review_cycle": review_cycle,
                                "review_agent_id": review_agent_id,
                                "result": final_review_payload,
                            }
                            break

                        for spawned_dev in respawned_devs:
                            spawned_dev_id = str(spawned_dev.get("agent_id") or "").strip()
                            spawned_task_id = str(spawned_dev.get("task_id") or "").strip()
                            if spawned_dev_id:
                                dev_task_map[spawned_dev_id] = spawned_task_id
                        yield {
                            "type": "review_reject_respawn",
                            "pipeline_id": pipeline_id,
                            "expert_id": str(agent_id),
                            "expert_type": expert_type,
                            "board_id": expert.board_id,
                            "review_cycle": review_cycle,
                            "review_agent_id": review_agent_id,
                            "task_ids": list(respawn_task_ids),
                            "respawn_dev_count": len(respawned_devs),
                            "reject_respawn_count": reject_respawn_count,
                        }

                        reject_respawn_failed = False
                        for spawned_dev in respawned_devs:
                            spawned_dev_id = str(spawned_dev.get("agent_id") or "").strip()
                            spawned_task_id = str(spawned_dev.get("task_id") or "").strip()
                            if not spawned_dev_id:
                                reject_respawn_failed = True
                                continue
                            spawned_dev_session = _store.get(spawned_dev_id)
                            if spawned_dev_session is None:
                                reject_respawn_failed = True
                                continue

                            dev_tool_subset = list(spawned_dev_session.tool_subset or assignment.get("tool_subset", []))
                            dev_prompt_blocks = list(spawned_dev_session.prompt_blocks or assignment.get("prompt_blocks", []))
                            respawned_dev_agent = DevAgent(
                                config=DevAgentConfig(
                                    prompt_blocks=dev_prompt_blocks,
                                    tool_subset=dev_tool_subset,
                                    prompts_root="system/prompts",
                                ),
                                session_id=spawned_dev_id,
                                store=_store,
                                mailbox=_mailbox,
                            )
                            runtime_tool_defs = _build_runtime_tool_definitions(dev_tool_subset)
                            dev_initial_task = str(spawned_dev_session.task_description or scope or "").strip()
                            max_rounds = max(1, int(child_max_rounds))
                            loop_config = MiniLoopConfig(max_rounds=max_rounds, poll_parent_every_n=3)

                            async def _execute_reject_respawn_dev_tool(
                                tool_name: str,
                                arguments: Dict[str, Any],
                                *,
                                _allowed_tools: List[str] = dev_tool_subset,
                                _dev_session_id: str = spawned_dev_id,
                            ) -> Dict[str, Any]:
                                normalized_tool = str(tool_name or "").strip()
                                if _allowed_tools and normalized_tool not in _allowed_tools:
                                    return {
                                        "error": f"tool_not_allowed:{normalized_tool}",
                                        "status": "blocked",
                                        "tool_name": normalized_tool,
                                    }
                                safe_arguments = arguments if isinstance(arguments, dict) else {}
                                if is_memory_tool(normalized_tool):
                                    return handle_memory_tool(normalized_tool, safe_arguments)
                                prepared_arguments = _prepare_child_tool_arguments(store=_store, child_session_id=_dev_session_id, tool_name=normalized_tool, arguments=safe_arguments)
                                return await child_tool_executor(normalized_tool, prepared_arguments, _dev_session_id)

                            yield {
                                "type": "dev_loop_start",
                                "pipeline_id": pipeline_id,
                                "expert_id": str(agent_id),
                                "expert_type": expert_type,
                                "agent_id": spawned_dev_id,
                                "task_id": spawned_task_id,
                                "tool_subset": dev_tool_subset,
                                "review_cycle": review_cycle,
                                "recovery_mode": "reject_respawn",
                            }
                            async for mini_event in run_mini_loop(
                                session_id=spawned_dev_id,
                                store=_store,
                                mailbox=_mailbox,
                                llm_call=child_llm_call,
                                tool_executor=_execute_reject_respawn_dev_tool,
                                tool_definitions=runtime_tool_defs,
                                system_prompt=respawned_dev_agent.build_system_prompt(),
                                initial_task=dev_initial_task,
                                config=loop_config,
                            ):
                                yield {
                                    "type": "dev_loop_event",
                                    "pipeline_id": pipeline_id,
                                    "expert_id": str(agent_id),
                                    "expert_type": expert_type,
                                    "agent_id": spawned_dev_id,
                                    "task_id": spawned_task_id,
                                    "review_cycle": review_cycle,
                                    "recovery_mode": "reject_respawn",
                                    "event": mini_event,
                                }

                            final_session = _store.get(spawned_dev_id)
                            final_status = str(final_session.status.value) if final_session is not None else "missing"
                            completion_report = ""
                            verification_report: Dict[str, Any] = {}
                            respawn_changed_files: List[str] = []
                            if final_session is not None:
                                completion_report = str(final_session.metadata.get("completion_report") or "").strip()
                                raw_verification_report = final_session.metadata.get("verification_report")
                                if isinstance(raw_verification_report, dict):
                                    verification_report = dict(raw_verification_report)
                                respawn_changed_files = _normalize_changed_files(
                                    verification_report.get("changed_files") if verification_report else final_session.metadata.get("changed_files")
                                )
                            if task_board_engine is not None and expert.board_id and spawned_task_id:
                                try:
                                    if final_status == AgentStatus.WAITING.value:
                                        task_board_engine.update_task(
                                            expert.board_id,
                                            spawned_task_id,
                                            status=TaskStatus.DONE,
                                            summary=completion_report or "child loop completed",
                                            files_changed=respawn_changed_files if respawn_changed_files else None,
                                        )
                                    elif final_status == AgentStatus.RUNNING.value:
                                        task_board_engine.update_task(
                                            expert.board_id,
                                            spawned_task_id,
                                            status=TaskStatus.IN_PROGRESS,
                                        )
                                except Exception:
                                    logger.debug(
                                        "Failed to update task board after reject respawn dev loop (board=%s task=%s)",
                                        expert.board_id,
                                        spawned_task_id,
                                        exc_info=True,
                                    )
                            if final_status != AgentStatus.WAITING.value:
                                reject_respawn_failed = True
                            yield {
                                "type": "dev_loop_end",
                                "pipeline_id": pipeline_id,
                                "expert_id": str(agent_id),
                                "expert_type": expert_type,
                                "agent_id": spawned_dev_id,
                                "task_id": spawned_task_id,
                                "status": final_status,
                                "completion_report": completion_report,
                                "verification_report": verification_report,
                                "changed_files": respawn_changed_files,
                                "review_cycle": review_cycle,
                                "recovery_mode": "reject_respawn",
                            }

                        refreshed_progress = expert.check_progress()
                        if reject_respawn_failed or not bool(refreshed_progress.get("all_devs_done")):
                            expert_blocked_reason = "review_rejected_respawn_incomplete"
                            final_review_payload = dict(review_payload or {})
                            yield {
                                "type": "expert_blocked",
                                "pipeline_id": pipeline_id,
                                "expert_id": str(agent_id),
                                "expert_type": expert_type,
                                "board_id": expert.board_id,
                                "reason": expert_blocked_reason,
                                "review_cycle": review_cycle,
                                "review_agent_id": review_agent_id,
                                "result": final_review_payload,
                            }
                            break
                        continue

                    if verdict != "request_changes":
                        final_review_payload = dict(review_payload or {})
                        break

                    if review_cycle >= review_cycle_limit:
                        if isinstance(review_payload, dict):
                            issues = list(review_payload.get("issues") or [])
                            issues.append("Review requested changes but the remediation cycle limit was reached.")
                            review_payload["issues"] = issues
                            summary_text = str(review_payload.get("summary") or "").strip()
                            review_payload["summary"] = (
                                f"{summary_text} | remediation limit reached" if summary_text else "Review requested changes but the remediation cycle limit was reached."
                            )
                        final_review_payload = dict(review_payload or {})
                        break

                    resumable_devs = [
                        child
                        for child in _store.list_children(str(agent_id))
                        if str(child.role or "").strip().lower() == "dev" and child.status == AgentStatus.WAITING
                    ]
                    if not resumable_devs:
                        if isinstance(review_payload, dict):
                            issues = list(review_payload.get("issues") or [])
                            issues.append("Review requested changes but no waiting dev agents were available for remediation.")
                            review_payload["issues"] = issues
                        final_review_payload = dict(review_payload or {})
                        break

                    review_instruction = _build_review_rework_instruction(
                        original_task=original_task_text,
                        review_payload=review_payload or {},
                        review_cycle=review_cycle,
                    )
                    yield {
                        "type": "review_rework_requested",
                        "pipeline_id": pipeline_id,
                        "expert_id": str(agent_id),
                        "expert_type": expert_type,
                        "board_id": expert.board_id,
                        "review_agent_id": review_agent_id,
                        "review_cycle": review_cycle,
                        "dev_count": len(resumable_devs),
                        "issues": list((review_payload or {}).get("issues") or []),
                    }

                    remediation_failed = False
                    for resumed_dev in resumable_devs:
                        resumed_dev_id = str(resumed_dev.session_id or "").strip()
                        resumed_task_id = str(dev_task_map.get(resumed_dev_id) or "").strip()
                        if not resumed_dev_id:
                            remediation_failed = True
                            continue
                        resume_result = handle_parent_tool_call(
                            "resume_child_agent",
                            {"agent_id": resumed_dev_id, "instruction": review_instruction},
                            parent_session_id=str(agent_id),
                            store=_store,
                            mailbox=_mailbox,
                        )
                        if resume_result.get("error"):
                            remediation_failed = True
                            yield {
                                "type": "dev_review_resume_end",
                                "pipeline_id": pipeline_id,
                                "expert_id": str(agent_id),
                                "expert_type": expert_type,
                                "agent_id": resumed_dev_id,
                                "task_id": resumed_task_id,
                                "review_cycle": review_cycle,
                                "status": "resume_failed",
                                "error": str(resume_result.get("error") or ""),
                            }
                            continue

                        _inject_system_instruction(_store, resumed_dev_id, review_instruction)
                        resumed_dev_session = _store.get(resumed_dev_id)
                        if resumed_dev_session is None or resumed_dev_session.status != AgentStatus.RUNNING:
                            remediation_failed = True
                            yield {
                                "type": "dev_review_resume_end",
                                "pipeline_id": pipeline_id,
                                "expert_id": str(agent_id),
                                "expert_type": expert_type,
                                "agent_id": resumed_dev_id,
                                "task_id": resumed_task_id,
                                "review_cycle": review_cycle,
                                "status": "not_running",
                            }
                            continue

                        dev_tool_subset = list(resumed_dev_session.tool_subset or assignment.get("tool_subset", []))
                        dev_prompt_blocks = list(resumed_dev_session.prompt_blocks or assignment.get("prompt_blocks", []))
                        resumed_dev_agent = DevAgent(
                            config=DevAgentConfig(
                                prompt_blocks=dev_prompt_blocks,
                                tool_subset=dev_tool_subset,
                                prompts_root="system/prompts",
                            ),
                            session_id=resumed_dev_id,
                            store=_store,
                            mailbox=_mailbox,
                        )
                        runtime_tool_defs = _build_runtime_tool_definitions(dev_tool_subset)
                        dev_initial_task = str(resumed_dev_session.task_description or scope or "").strip()
                        max_rounds = max(1, int(child_max_rounds))
                        loop_config = MiniLoopConfig(max_rounds=max_rounds, poll_parent_every_n=3)

                        async def _execute_resumed_review_dev_tool(
                            tool_name: str,
                            arguments: Dict[str, Any],
                            *,
                            _allowed_tools: List[str] = dev_tool_subset,
                            _dev_session_id: str = resumed_dev_id,
                        ) -> Dict[str, Any]:
                            normalized_tool = str(tool_name or "").strip()
                            if _allowed_tools and normalized_tool not in _allowed_tools:
                                return {
                                    "error": f"tool_not_allowed:{normalized_tool}",
                                    "status": "blocked",
                                    "tool_name": normalized_tool,
                                }
                            safe_arguments = arguments if isinstance(arguments, dict) else {}
                            if is_memory_tool(normalized_tool):
                                return handle_memory_tool(normalized_tool, safe_arguments)
                            prepared_arguments = _prepare_child_tool_arguments(store=_store, child_session_id=_dev_session_id, tool_name=normalized_tool, arguments=safe_arguments)
                            return await child_tool_executor(normalized_tool, prepared_arguments, _dev_session_id)

                        yield {
                            "type": "dev_review_resume_start",
                            "pipeline_id": pipeline_id,
                            "expert_id": str(agent_id),
                            "expert_type": expert_type,
                            "agent_id": resumed_dev_id,
                            "task_id": resumed_task_id,
                            "review_cycle": review_cycle,
                            "tool_subset": dev_tool_subset,
                        }
                        async for mini_event in run_mini_loop(
                            session_id=resumed_dev_id,
                            store=_store,
                            mailbox=_mailbox,
                            llm_call=child_llm_call,
                            tool_executor=_execute_resumed_review_dev_tool,
                            tool_definitions=runtime_tool_defs,
                            system_prompt=resumed_dev_agent.build_system_prompt(),
                            initial_task=dev_initial_task,
                            config=loop_config,
                        ):
                            yield {
                                "type": "dev_review_resume_event",
                                "pipeline_id": pipeline_id,
                                "expert_id": str(agent_id),
                                "expert_type": expert_type,
                                "agent_id": resumed_dev_id,
                                "task_id": resumed_task_id,
                                "review_cycle": review_cycle,
                                "event": mini_event,
                            }

                        final_session = _store.get(resumed_dev_id)
                        final_status = str(final_session.status.value) if final_session is not None else "missing"
                        completion_report = ""
                        verification_report: Dict[str, Any] = {}
                        resumed_changed_files: List[str] = []
                        if final_session is not None:
                            completion_report = str(final_session.metadata.get("completion_report") or "").strip()
                            raw_verification_report = final_session.metadata.get("verification_report")
                            if isinstance(raw_verification_report, dict):
                                verification_report = dict(raw_verification_report)
                            resumed_changed_files = _normalize_changed_files(
                                verification_report.get("changed_files") if verification_report else final_session.metadata.get("changed_files")
                            )
                        if task_board_engine is not None and expert.board_id and resumed_task_id:
                            try:
                                if final_status == AgentStatus.WAITING.value:
                                    task_board_engine.update_task(
                                        expert.board_id,
                                        resumed_task_id,
                                        status=TaskStatus.DONE,
                                        summary=completion_report or "child loop completed",
                                        files_changed=resumed_changed_files if resumed_changed_files else None,
                                    )
                                elif final_status == AgentStatus.RUNNING.value:
                                    task_board_engine.update_task(
                                        expert.board_id,
                                        resumed_task_id,
                                        status=TaskStatus.IN_PROGRESS,
                                    )
                            except Exception:
                                logger.debug(
                                    "Failed to update task board after dev review resume loop (board=%s task=%s)",
                                    expert.board_id,
                                    resumed_task_id,
                                    exc_info=True,
                                )
                        if final_status != AgentStatus.WAITING.value:
                            remediation_failed = True
                        yield {
                            "type": "dev_review_resume_end",
                            "pipeline_id": pipeline_id,
                            "expert_id": str(agent_id),
                            "expert_type": expert_type,
                            "agent_id": resumed_dev_id,
                            "task_id": resumed_task_id,
                            "review_cycle": review_cycle,
                            "status": final_status,
                            "completion_report": completion_report,
                            "verification_report": verification_report,
                            "changed_files": resumed_changed_files,
                        }

                    refreshed_progress = expert.check_progress()
                    if remediation_failed or not bool(refreshed_progress.get("all_devs_done")):
                        if isinstance(review_payload, dict):
                            issues = list(review_payload.get("issues") or [])
                            issues.append("One or more dev agents did not complete the requested review remediation.")
                            review_payload["issues"] = issues
                        final_review_payload = dict(review_payload or {})
                        break

                if final_review_payload is None and isinstance(review_payload, dict):
                    final_review_payload = dict(review_payload)
                if isinstance(final_review_payload, dict):
                    review_results.append(final_review_payload)

            report_text = expert.aggregate_results()
            if final_review_payload is not None:
                review_summary = str(final_review_payload.get("summary") or "").strip()
                if review_summary:
                    report_text = f"{report_text}\n\n### Review Summary\n{review_summary}"
            final_verdict = str((final_review_payload or {}).get("verdict") or "").strip().lower()
            if final_verdict == "reject":
                blocked_reason_text = expert_blocked_reason or "review_rejected"
                report_text = f"[BLOCKED] {blocked_reason_text}\n\n{report_text}"
                try:
                    _store.update_metadata(str(agent_id), {"blocked_reason": blocked_reason_text, "final_review_verdict": final_verdict})
                except Exception:
                    logger.debug("Failed to persist blocked metadata for expert: %s", agent_id, exc_info=True)
            _mailbox.send(
                str(agent_id),
                resolved_core_execution_session_id,
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

    # ── Phase 5: Core lifecycle loop (LLM-driven parent management) ──

    core_loop_summary: Dict[str, Any] = {}
    core_loop_tool_call_count = 0
    core_loop_tool_names: List[str] = []
    spawned_child_ids: set[str] = set()
    resumed_child_ids: set[str] = set()
    destroyed_child_ids: set[str] = set()
    deferred_child_ids: set[str] = set()
    resume_exec_dev_count = 0
    resume_exec_skips: List[Dict[str, Any]] = []
    core_loop_enabled = bool(
        child_execution_enabled and child_llm_call is not None and child_tool_executor is not None
    )
    if core_loop_enabled and child_llm_call is not None:
        children_snapshot = _collect_core_descendant_status_snapshot(
            store=_store,
            core_execution_session_id=resolved_core_execution_session_id,
        )
        core_loop_initial_task = _build_core_loop_initial_task(
            message=message,
            core_execution_session_id=resolved_core_execution_session_id,
            pipeline_id=pipeline_id,
            children_snapshot=children_snapshot,
        )
        core_tool_defs = _build_core_parent_tool_definitions()
        core_allowed_tools = {str(item.get("name") or "").strip() for item in core_tool_defs}
        core_loop_config = MiniLoopConfig(
            max_rounds=max(1, min(int(child_max_rounds), 6)),
            poll_parent_every_n=max(1, min(3, int(child_max_rounds) if int(child_max_rounds) > 0 else 3)),
            include_child_tools=False,
        )

        async def _core_llm_call(
            messages: List[Dict[str, Any]],
            tools: List[Dict[str, Any]],
            model_name: str,
        ) -> Dict[str, Any]:
            raw = await child_llm_call(messages, tools, model_name)
            payload = raw if isinstance(raw, dict) else {}
            raw_tool_calls = payload.get("tool_calls")
            normalized_calls: List[Dict[str, Any]] = []
            if isinstance(raw_tool_calls, list):
                for item in raw_tool_calls:
                    if not isinstance(item, dict):
                        continue
                    tool_name = str(item.get("name") or "").strip()
                    if tool_name in core_allowed_tools:
                        normalized_calls.append(dict(item))
            return {
                "content": str(payload.get("content") or ""),
                "tool_calls": normalized_calls,
            }

        async def _core_parent_tool_executor(
            tool_name: str,
            arguments: Dict[str, Any],
        ) -> Dict[str, Any]:
            normalized_name = str(tool_name or "").strip()
            if normalized_name not in core_allowed_tools:
                return {
                    "error": f"tool_not_allowed:{normalized_name}",
                    "status": "blocked",
                    "allowed_tools": sorted(core_allowed_tools),
                }
            safe_arguments = dict(arguments) if isinstance(arguments, dict) else {}
            if normalized_name == "spawn_child_agent":
                requested_role = str(safe_arguments.get("role") or "").strip().lower()
                if not requested_role:
                    safe_arguments["role"] = "dev"
                    requested_role = "dev"
                if requested_role not in _CORE_SPAWN_ROLE_ALLOWLIST:
                    return {
                        "error": f"unsupported_spawn_role:{requested_role}",
                        "status": "blocked",
                        "allowed_roles": sorted(_CORE_SPAWN_ROLE_ALLOWLIST),
                    }
                raw_metadata = safe_arguments.get("metadata")
                metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
                metadata["pipeline_id"] = str(pipeline_id or "").strip()
                safe_arguments["metadata"] = metadata
                if str(dispatch.get("target_repo") or "").strip().lower() == "self" and not safe_arguments.get("workspace_mode"):
                    safe_arguments["workspace_mode"] = "worktree"
            return handle_parent_tool_call(
                normalized_name,
                safe_arguments,
                parent_session_id=resolved_core_execution_session_id,
                store=_store,
                mailbox=_mailbox,
            )

        yield {
            "type": "core_loop_start",
            "pipeline_id": pipeline_id,
            "core_execution_session_id": resolved_core_execution_session_id,
            "tool_subset": sorted(core_allowed_tools),
            "child_count": len(children_snapshot),
        }

        async for core_event in run_mini_loop(
            session_id=resolved_core_execution_session_id,
            store=_store,
            mailbox=_mailbox,
            llm_call=_core_llm_call,
            tool_executor=_core_parent_tool_executor,
            tool_definitions=core_tool_defs,
            system_prompt=core.build_system_prompt(str(decomposition.get("prompt_profile") or "")),
            initial_task=core_loop_initial_task,
            config=core_loop_config,
        ):
            if not isinstance(core_event, dict):
                continue
            event_type = str(core_event.get("type") or "")
            if event_type == "tool_call":
                tool_name = str(core_event.get("name") or "").strip()
                if tool_name:
                    core_loop_tool_call_count += 1
                    core_loop_tool_names.append(tool_name)
            elif event_type == "tool_result":
                tool_name = str(core_event.get("name") or "").strip()
                result_payload = core_event.get("result")
                if isinstance(result_payload, dict):
                    child_id = str(result_payload.get("agent_id") or "").strip()
                    status_text = str(result_payload.get("status") or "").strip().lower()
                    if tool_name == "spawn_child_agent" and child_id and status_text == "running":
                        spawned_child_ids.add(child_id)
                    elif tool_name == "resume_child_agent" and child_id and status_text == "running":
                        resumed_child_ids.add(child_id)
                    elif tool_name == "destroy_child_agent" and child_id and status_text == "destroyed":
                        destroyed_child_ids.add(child_id)
            elif event_type == "loop_end":
                state_payload = core_event.get("state")
                if isinstance(state_payload, dict):
                    core_loop_summary.update(state_payload)
                core_loop_summary["stop_reason"] = str(core_event.get("reason") or "")
            yield {
                "type": "core_loop_event",
                "pipeline_id": pipeline_id,
                "core_execution_session_id": resolved_core_execution_session_id,
                "event": core_event,
            }

        if _store.get(resolved_core_execution_session_id) is not None:
            try:
                _store.update_status(resolved_core_execution_session_id, AgentStatus.WAITING)
            except Exception:
                logger.debug("Failed to set core runtime session waiting: %s", resolved_core_execution_session_id, exc_info=True)

        if "stop_reason" not in core_loop_summary:
            core_loop_summary["stop_reason"] = "unknown"
        core_loop_summary["tool_call_count"] = int(core_loop_tool_call_count)
        core_loop_summary["tool_names"] = list(core_loop_tool_names)
        core_loop_summary["spawned_child_ids"] = sorted(spawned_child_ids)
        core_loop_summary["resumed_child_ids"] = sorted(resumed_child_ids)
        core_loop_summary["destroyed_child_ids"] = sorted(destroyed_child_ids)
        core_loop_summary["deferred_child_ids"] = sorted(deferred_child_ids)
        yield {
            "type": "core_loop_end",
            "pipeline_id": pipeline_id,
            "core_execution_session_id": resolved_core_execution_session_id,
            "summary": dict(core_loop_summary),
        }

    # Execute selected child sessions in-band (Phase-5B), so Core lifecycle
    # actions produce immediate, observable effects in this request.
    followup_child_ids = sorted((spawned_child_ids | resumed_child_ids) - destroyed_child_ids)
    if (
        followup_child_ids
        and child_execution_enabled
        and child_llm_call is not None
        and child_tool_executor is not None
    ):
        refreshed_expert_ids: set[str] = set()
        for target_child_id in followup_child_ids:
            source = "spawn" if target_child_id in spawned_child_ids else "resume"
            if source == "spawn":
                start_event_type = "dev_loop_spawn_start"
                event_event_type = "dev_loop_spawn_event"
                end_event_type = "dev_loop_spawn_end"
                skip_event_type = "dev_loop_spawn_skipped"
            else:
                start_event_type = "dev_loop_resume_start"
                event_event_type = "dev_loop_resume_event"
                end_event_type = "dev_loop_resume_end"
                skip_event_type = "dev_loop_resume_skipped"

            resumed_session = _store.get(target_child_id)
            if resumed_session is None:
                resume_exec_skips.append(
                    {
                        "agent_id": target_child_id,
                        "reason": "missing_or_destroyed",
                        "source": source,
                    }
                )
                yield {
                    "type": skip_event_type,
                    "pipeline_id": pipeline_id,
                    "agent_id": target_child_id,
                    "source": source,
                    "reason": "missing_or_destroyed",
                }
                continue

            if resumed_session.status != AgentStatus.RUNNING:
                resume_exec_skips.append(
                    {
                        "agent_id": target_child_id,
                        "reason": "not_running",
                        "source": source,
                    }
                )
                yield {
                    "type": skip_event_type,
                    "pipeline_id": pipeline_id,
                    "agent_id": target_child_id,
                    "source": source,
                    "reason": "not_running",
                    "status": str(resumed_session.status.value),
                }
                continue

            session_role = str(resumed_session.role or "").strip().lower()
            if session_role != "dev":
                if source == "spawn" and session_role in {"expert", "review"}:
                    try:
                        _store.update_status(target_child_id, AgentStatus.WAITING)
                    except Exception:
                        logger.debug("Failed to defer spawned child session: %s", target_child_id, exc_info=True)
                    deferred_child_ids.add(target_child_id)
                    resume_exec_skips.append(
                        {
                            "agent_id": target_child_id,
                            "reason": "spawn_deferred_role",
                            "source": source,
                            "role": session_role,
                        }
                    )
                    yield {
                        "type": "child_spawn_deferred",
                        "pipeline_id": pipeline_id,
                        "agent_id": target_child_id,
                        "source": source,
                        "reason": "spawn_deferred_role",
                        "role": session_role,
                    }
                    continue
                resume_exec_skips.append(
                    {
                        "agent_id": target_child_id,
                        "reason": "unsupported_role",
                        "source": source,
                        "role": str(resumed_session.role or ""),
                    }
                )
                yield {
                    "type": skip_event_type,
                    "pipeline_id": pipeline_id,
                    "agent_id": target_child_id,
                    "source": source,
                    "reason": "unsupported_role",
                    "role": str(resumed_session.role or ""),
                }
                continue

            expert_id = str(resumed_session.parent_id or "").strip()
            expert_type = "expert"
            expert_session = _store.get(expert_id) if expert_id else None
            if expert_session is not None:
                expert_type = str(expert_session.role or "expert").strip() or "expert"

            dev_tool_subset = list(resumed_session.tool_subset or [])
            dev_prompt_blocks = list(resumed_session.prompt_blocks or [])
            dev_initial_task = str(resumed_session.task_description or "").strip()
            runtime_tool_defs = _build_runtime_tool_definitions(dev_tool_subset)
            loop_config = MiniLoopConfig(max_rounds=max(1, int(child_max_rounds)), poll_parent_every_n=3)
            dev_agent = DevAgent(
                config=DevAgentConfig(
                    prompt_blocks=dev_prompt_blocks,
                    tool_subset=dev_tool_subset,
                    prompts_root="system/prompts",
                ),
                session_id=target_child_id,
                store=_store,
                mailbox=_mailbox,
            )

            async def _execute_resumed_dev_tool(
                tool_name: str,
                arguments: Dict[str, Any],
                *,
                _allowed_tools: List[str] = dev_tool_subset,
                _dev_session_id: str = target_child_id,
            ) -> Dict[str, Any]:
                normalized_tool = str(tool_name or "").strip()
                if _allowed_tools and normalized_tool not in _allowed_tools:
                    return {
                        "error": f"tool_not_allowed:{normalized_tool}",
                        "status": "blocked",
                        "tool_name": normalized_tool,
                    }
                safe_arguments = arguments if isinstance(arguments, dict) else {}
                if is_memory_tool(normalized_tool):
                    return handle_memory_tool(normalized_tool, safe_arguments)
                prepared_arguments = _prepare_child_tool_arguments(store=_store, child_session_id=_dev_session_id, tool_name=normalized_tool, arguments=safe_arguments)
                return await child_tool_executor(normalized_tool, prepared_arguments, _dev_session_id)

            yield {
                "type": start_event_type,
                "pipeline_id": pipeline_id,
                "expert_id": expert_id,
                "expert_type": expert_type,
                "agent_id": target_child_id,
                "source": source,
                "tool_subset": dev_tool_subset,
            }

            async for resumed_event in run_mini_loop(
                session_id=target_child_id,
                store=_store,
                mailbox=_mailbox,
                llm_call=child_llm_call,
                tool_executor=_execute_resumed_dev_tool,
                tool_definitions=runtime_tool_defs,
                system_prompt=dev_agent.build_system_prompt(),
                initial_task=dev_initial_task,
                config=loop_config,
            ):
                yield {
                    "type": event_event_type,
                    "pipeline_id": pipeline_id,
                    "expert_id": expert_id,
                    "expert_type": expert_type,
                    "agent_id": target_child_id,
                    "source": source,
                    "event": resumed_event,
                }

            final_resumed_session = _store.get(target_child_id)
            final_status = str(final_resumed_session.status.value) if final_resumed_session is not None else "missing"
            completion_report = ""
            if final_resumed_session is not None:
                completion_report = str(final_resumed_session.metadata.get("completion_report") or "").strip()

            resume_exec_dev_count += 1
            if expert_id and expert_type == "expert":
                refreshed_expert_ids.add(expert_id)
            yield {
                "type": end_event_type,
                "pipeline_id": pipeline_id,
                "expert_id": expert_id,
                "expert_type": expert_type,
                "agent_id": target_child_id,
                "source": source,
                "status": final_status,
                "completion_report": completion_report,
            }

        for expert_id in sorted(refreshed_expert_ids):
            expert_session = _store.get(expert_id)
            if expert_session is None:
                continue
            expert = ExpertAgent(
                config=ExpertAgentConfig(
                    expert_type=str(expert_session.role or "expert").strip() or "expert",
                    prompt_blocks=list(expert_session.prompt_blocks or []),
                    tool_subset=list(expert_session.tool_subset or []),
                ),
                session_id=expert_id,
                store=_store,
                mailbox=_mailbox,
                task_board_engine=task_board_engine,
            )
            refreshed_report = expert.aggregate_results()
            _mailbox.send(
                expert_id,
                resolved_core_execution_session_id,
                refreshed_report,
                message_type="report",
            )
            yield {
                "type": "expert_report_refresh",
                "pipeline_id": pipeline_id,
                "expert_id": expert_id,
                "core_execution_session_id": resolved_core_execution_session_id,
            }

        if core_loop_summary:
            core_loop_summary["resume_exec_dev_count"] = int(resume_exec_dev_count)
            core_loop_summary["resume_exec_skip_count"] = len(resume_exec_skips)
            core_loop_summary["resume_exec_skips"] = list(resume_exec_skips[:20])
            core_loop_summary["deferred_child_ids"] = sorted(deferred_child_ids)

    # ── Phase 6: Collect results ───────────────────────────────

    reports = core.collect_reports(resolved_core_execution_session_id, pipeline_id=pipeline_id)
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
        else:
            normalized_review_verdicts = [str(item.get("verdict") or "").strip().lower() for item in review_results]
            if not all(verdict == "approve" for verdict in normalized_review_verdicts):
                review_gate_passed = False
                if any(verdict == "reject" for verdict in normalized_review_verdicts):
                    review_stop_reason = "review_rejected"
                elif any(verdict == "request_changes" for verdict in normalized_review_verdicts):
                    review_stop_reason = "review_requested_changes"
                else:
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
    if core_loop_summary:
        state = receipt_event.get("agent_state")
        if isinstance(state, dict):
            state["core_loop"] = dict(core_loop_summary)
            state["core_loop_tool_calls"] = int(core_loop_tool_call_count)
            state["core_loop_tools_used"] = list(core_loop_tool_names)

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
        core_execution_session_id=resolved_core_execution_session_id,
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
        "core_execution_session_id": resolved_core_execution_session_id,
        "child_session_cleanup": cleanup_summary,
    }


__all__ = ["run_multi_agent_pipeline"]
