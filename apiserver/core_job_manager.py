from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable, Deque, Dict, List, Optional, Set

from agents.core_agent import CoreAgent
from agents.pipeline import (
    advance_core_waiting_descendants_once,
    build_core_execution_receipt,
    collect_core_pending_descendants,
    evaluate_core_pipeline_state,
    merge_heartbeat_escalation_summaries,
    run_multi_agent_pipeline,
)
from agents.runtime.agent_session import AgentSessionStore, AgentStatus

logger = logging.getLogger(__name__)

DEFAULT_CORE_RUNTIME_ID = "core-main"
_QUEUEABLE_JOB_STATUSES = {"accepted", "running"}
_RECOVERABLE_JOB_STATUSES = {"accepted", "running", "waiting_descendants", "blocked"}
_VISIBLE_ACTIVE_JOB_STATUSES = set(_RECOVERABLE_JOB_STATUSES)
_RECENT_EVENT_LIMIT = 40
_RECOVERY_TERMINAL_JOB_LIMIT = 20
_SHELL_OUTBOX_SIGNIFICANT_JOB_STATUSES = {"running", "waiting_descendants"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_route_summary(route_decision: Dict[str, Any], dispatch_payload: Dict[str, Any]) -> Dict[str, Any]:
    decision = dict(route_decision or {})
    dispatch = dict(dispatch_payload or {})
    return {
        "delegation_intent": str(
            dispatch.get("delegation_intent")
            or decision.get("delegation_intent")
            or ""
        ),
        "prompt_profile": str(
            dispatch.get("prompt_profile")
            or decision.get("prompt_profile")
            or ""
        ),
        "tool_profile": list(dispatch.get("tool_profile") or decision.get("tool_profile") or []),
        "model_tier": str(
            dispatch.get("model_tier")
            or decision.get("selected_model_tier")
            or ""
        ),
        "core_route": str(
            dispatch.get("core_route")
            or decision.get("core_route")
            or ""
        ),
        "complexity_hint": str(
            dispatch.get("complexity_hint")
            or decision.get("complexity_hint")
            or ""
        ),
        "selected_role": str(
            dispatch.get("selected_role")
            or decision.get("selected_role")
            or ""
        ),
    }


def _truncate_text(value: Any, limit: int = 320) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)]}..."


def _summarize_event(event: Dict[str, Any]) -> Dict[str, Any]:
    event_type = str(event.get("type") or "").strip()
    summary: Dict[str, Any] = {
        "type": event_type,
        "pipeline_id": str(event.get("pipeline_id") or ""),
        "timestamp": _utc_now_iso(),
    }
    for key in (
        "reason",
        "status",
        "decision",
        "phase",
        "role",
        "agent_id",
        "source",
        "session_id",
        "parent_session_id",
        "core_execution_session_id",
    ):
        text = str(event.get(key) or "").strip()
        if text:
            summary[key] = text

    if event_type in {"execution_receipt", "review_result"}:
        agent_state = event.get("agent_state") if isinstance(event.get("agent_state"), dict) else {}
        review_result = event.get("review_result") if isinstance(event.get("review_result"), dict) else {}
        if agent_state:
            summary["task_completed"] = bool(agent_state.get("task_completed"))
            summary["final_answer"] = _truncate_text(
                agent_state.get("final_answer") or agent_state.get("completion_summary") or ""
            )
            summary["core_recovery_restart_count"] = int(agent_state.get("core_recovery_restart_count") or 0)
            summary["core_handoff_duplicate_count"] = int(agent_state.get("core_handoff_duplicate_count") or 0)
            summary["core_shell_inbox_dedup_skipped_count"] = int(
                agent_state.get("core_shell_inbox_dedup_skipped_count") or 0
            )
        if review_result:
            summary["verdict"] = str(review_result.get("verdict") or "")
            summary["issue_count"] = len(review_result.get("issues") or [])
    elif event_type == "content":
        summary["text"] = _truncate_text(event.get("text") or "")
    elif event_type == "warning":
        summary["text"] = _truncate_text(event.get("text") or "")
    elif event_type == "pipeline_end":
        summary["duration_ms"] = int(event.get("duration_ms") or 0)

    return summary


def _derive_terminal_status(
    *,
    pipeline_end_reason: str,
    saw_completed_receipt: bool,
    error_text: str,
) -> str:
    if error_text:
        return "failed"
    reason = str(pipeline_end_reason or "").strip().lower()
    if reason in {"delegated_waiting_child_completion", "waiting_child_completion"}:
        return "waiting_descendants"
    if saw_completed_receipt or reason in {"completed", "success", "done"}:
        return "completed"
    if "block" in reason:
        return "blocked"
    if reason in {"cancelled", "canceled"}:
        return "cancelled"
    if reason:
        return "failed"
    return "completed" if saw_completed_receipt else "failed"


def _derive_reconciled_job_status(*, task_completed: bool, stop_reason: str, experts_blocked: bool) -> str:
    reason = str(stop_reason or "").strip().lower()
    if task_completed:
        return "completed"
    if reason in {"review_requested_changes", "review_rejected"}:
        return "blocked"
    if experts_blocked or "block" in reason:
        return "blocked"
    if reason in {"cancelled", "canceled"}:
        return "cancelled"
    return "failed"


def _build_job_execution_session_id(*, core_runtime_id: str, job_id: str) -> str:
    return f"{str(core_runtime_id or DEFAULT_CORE_RUNTIME_ID)}__job__{str(job_id or '').strip()}"


def _build_shell_core_execution_session_id(*, shell_session_id: str, core_runtime_id: str) -> str:
    normalized_shell_session_id = str(shell_session_id or "").strip()
    if normalized_shell_session_id:
        return f"{normalized_shell_session_id}__core"
    return _build_job_execution_session_id(
        core_runtime_id=core_runtime_id,
        job_id=f"fallback_{uuid.uuid4().hex[:12]}",
    )


def _build_shell_status_update_text(*, status: str, job_id: str, goal: str, pending_descendant_count: int = 0) -> str:
    normalized_status = str(status or "").strip().lower() or "unknown"
    trimmed_goal = _truncate_text(goal, limit=180)
    if normalized_status == "running":
        return f"[CORE RUNNING] job_id={job_id} 已开始执行：{trimmed_goal}".strip()
    if normalized_status == "waiting_descendants":
        suffix = f"；待收口子任务数={max(0, int(pending_descendant_count or 0))}"
        return f"[CORE WAITING] job_id={job_id} 正等待下游结果：{trimmed_goal}{suffix}".strip()
    return f"[CORE {normalized_status.upper()}] job_id={job_id} {trimmed_goal}".strip()


@dataclass
class CoreDispatchJob:
    job_id: str
    shell_session_id: str
    core_runtime_id: str
    core_execution_session_id: str
    goal: str
    risk_level: str
    handoff_source: str
    route_summary: Dict[str, Any] = field(default_factory=dict)
    core_execution_session_created: bool = False
    handoff_message_seq: int = 0
    completion_message_seq: int = 0
    handoff_duplicate_count: int = 0
    recovery_restart_count: int = 0
    status: str = "accepted"
    created_at: str = field(default_factory=_utc_now_iso)
    started_at: str = ""
    updated_at: str = field(default_factory=_utc_now_iso)
    completed_at: str = ""
    pipeline_id: str = ""
    last_event_type: str = ""
    last_event_at: str = ""
    pipeline_end_reason: str = ""
    error_text: str = ""
    last_execution_receipt: Dict[str, Any] = field(default_factory=dict)
    event_count: int = 0
    recent_events: Deque[Dict[str, Any]] = field(default_factory=lambda: deque(maxlen=_RECENT_EVENT_LIMIT))

    def snapshot(self, *, include_events: bool = True) -> Dict[str, Any]:
        payload = {
            "job_id": self.job_id,
            "shell_session_id": self.shell_session_id,
            "core_runtime_id": self.core_runtime_id,
            "run_context_id": self.core_execution_session_id,
            "core_execution_session_id": self.core_execution_session_id,
            "goal": self.goal,
            "risk_level": self.risk_level,
            "handoff_source": self.handoff_source,
            "route_summary": dict(self.route_summary),
            "run_context_created": bool(self.core_execution_session_created),
            "core_execution_session_created": bool(self.core_execution_session_created),
            "handoff_message_seq": int(self.handoff_message_seq or 0),
            "completion_message_seq": int(self.completion_message_seq or 0),
            "handoff_duplicate_count": int(self.handoff_duplicate_count or 0),
            "recovery_restart_count": int(self.recovery_restart_count or 0),
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "pipeline_id": self.pipeline_id,
            "last_event_type": self.last_event_type,
            "last_event_at": self.last_event_at,
            "pipeline_end_reason": self.pipeline_end_reason,
            "error_text": self.error_text,
            "event_count": int(self.event_count),
            "last_execution_receipt": dict(self.last_execution_receipt or {}),
        }
        if include_events:
            payload["recent_events"] = list(self.recent_events)
        return payload


@dataclass
class CoreDispatchJobRunSpec:
    runner: Callable[..., AsyncGenerator[Dict[str, Any], None]]
    goal: str
    risk_level: str
    route_decision: Dict[str, Any]
    dispatch_payload: Dict[str, Any]
    core_execution_session_id: str
    core_runtime_id: str
    store: AgentSessionStore
    mailbox: Any
    task_board_engine: Any
    child_llm_call: Optional[Callable[..., Any]]
    child_tool_executor: Optional[Callable[..., Any]]
    enable_child_execution: bool
    child_max_rounds: int
    child_session_cleanup_mode: str
    child_session_cleanup_ttl_seconds: int


@dataclass
class CoreDispatchRuntimeDefaults:
    store: Optional[AgentSessionStore] = None
    mailbox: Any = None
    task_board_engine: Any = None
    runner: Optional[Callable[..., AsyncGenerator[Dict[str, Any], None]]] = None
    child_llm_call: Optional[Callable[..., Any]] = None
    child_tool_executor: Optional[Callable[..., Any]] = None
    enable_child_execution: bool = False
    child_max_rounds: int = 12
    child_session_cleanup_mode: str = "ttl"
    child_session_cleanup_ttl_seconds: int = 3600
    heartbeat_interval_seconds: float = 15.0


class CoreDispatchJobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, CoreDispatchJob] = {}
        self._job_tasks: Dict[str, asyncio.Task[Any]] = {}
        self._heartbeat_tasks: Dict[str, asyncio.Task[Any]] = {}
        self._job_specs: Dict[str, CoreDispatchJobRunSpec] = {}
        self._shell_jobs: Dict[str, List[str]] = defaultdict(list)
        self._shell_archived_jobs: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._shell_queues: Dict[str, Deque[str]] = defaultdict(deque)
        self._shell_workers: Dict[str, asyncio.Task[Any]] = {}
        self._shell_current_jobs: Dict[str, str] = {}
        self._shell_mailboxes: Dict[str, Any] = {}
        self._shell_core_sessions: Dict[str, str] = {}
        self._shell_mailbox_cursors: Dict[str, int] = {}
        self._shell_recovery_restart_totals: Dict[str, int] = {}
        self._shell_inbox_dedup_skipped_counts: Dict[str, int] = {}
        self._shell_last_dedup_message_seq: Dict[str, int] = {}
        self._runtime_monitor_task: Optional[asyncio.Task[Any]] = None
        self._known_core_runtime_ids: Set[str] = {DEFAULT_CORE_RUNTIME_ID}
        self._runtime_defaults = CoreDispatchRuntimeDefaults()

    def configure_runtime_defaults(
        self,
        *,
        store: Optional[AgentSessionStore] = None,
        mailbox: Any = None,
        task_board_engine: Any = None,
        runner: Optional[Callable[..., AsyncGenerator[Dict[str, Any], None]]] = None,
        child_llm_call: Optional[Callable[..., Any]] = None,
        child_tool_executor: Optional[Callable[..., Any]] = None,
        enable_child_execution: Optional[bool] = None,
        child_max_rounds: Optional[int] = None,
        child_session_cleanup_mode: Optional[str] = None,
        child_session_cleanup_ttl_seconds: Optional[int] = None,
        heartbeat_interval_seconds: Optional[float] = None,
    ) -> None:
        defaults = self._runtime_defaults
        if store is not None:
            defaults.store = store
        if mailbox is not None:
            defaults.mailbox = mailbox
        if task_board_engine is not None:
            defaults.task_board_engine = task_board_engine
        if runner is not None:
            defaults.runner = runner
        if child_llm_call is not None:
            defaults.child_llm_call = child_llm_call
        if child_tool_executor is not None:
            defaults.child_tool_executor = child_tool_executor
        if enable_child_execution is not None:
            defaults.enable_child_execution = bool(enable_child_execution)
        if child_max_rounds is not None:
            defaults.child_max_rounds = max(1, int(child_max_rounds or 0))
        if child_session_cleanup_mode is not None:
            defaults.child_session_cleanup_mode = str(child_session_cleanup_mode or "ttl")
        if child_session_cleanup_ttl_seconds is not None:
            defaults.child_session_cleanup_ttl_seconds = max(0, int(child_session_cleanup_ttl_seconds or 0))
        if heartbeat_interval_seconds is not None:
            defaults.heartbeat_interval_seconds = max(1.0, float(heartbeat_interval_seconds or 15.0))
        self._start_runtime_monitor_if_possible()

    @staticmethod
    def _normalize_recovery_job_envelope(raw_job: Any) -> Dict[str, Any]:
        payload = dict(raw_job or {}) if isinstance(raw_job, dict) else {}
        job_id = str(payload.get("job_id") or "").strip()
        if not job_id:
            return {}
        return {
            "job_id": job_id,
            "shell_session_id": str(payload.get("shell_session_id") or "").strip(),
            "core_runtime_id": str(payload.get("core_runtime_id") or DEFAULT_CORE_RUNTIME_ID).strip() or DEFAULT_CORE_RUNTIME_ID,
            "run_context_id": str(payload.get("run_context_id") or payload.get("core_execution_session_id") or "").strip(),
            "core_execution_session_id": str(payload.get("run_context_id") or payload.get("core_execution_session_id") or "").strip(),
            "goal": str(payload.get("goal") or "").strip(),
            "risk_level": str(payload.get("risk_level") or "").strip(),
            "handoff_source": str(payload.get("handoff_source") or "").strip(),
            "route_summary": dict(payload.get("route_summary") or {}),
            "route_decision": dict(payload.get("route_decision") or {}),
            "dispatch_payload": dict(payload.get("dispatch_payload") or {}),
            "run_context_created": bool(
                payload.get("run_context_created")
                if payload.get("run_context_created") is not None
                else payload.get("core_execution_session_created")
            ),
            "core_execution_session_created": bool(
                payload.get("run_context_created")
                if payload.get("run_context_created") is not None
                else payload.get("core_execution_session_created")
            ),
            "handoff_message_seq": max(0, int(payload.get("handoff_message_seq") or 0)),
            "completion_message_seq": max(0, int(payload.get("completion_message_seq") or 0)),
            "handoff_duplicate_count": max(0, int(payload.get("handoff_duplicate_count") or 0)),
            "recovery_restart_count": max(0, int(payload.get("recovery_restart_count") or 0)),
            "status": str(payload.get("status") or "accepted").strip() or "accepted",
            "created_at": str(payload.get("created_at") or ""),
            "started_at": str(payload.get("started_at") or ""),
            "updated_at": str(payload.get("updated_at") or ""),
            "completed_at": str(payload.get("completed_at") or ""),
            "pipeline_id": str(payload.get("pipeline_id") or ""),
            "last_event_type": str(payload.get("last_event_type") or ""),
            "last_event_at": str(payload.get("last_event_at") or ""),
            "pipeline_end_reason": str(payload.get("pipeline_end_reason") or ""),
            "error_text": str(payload.get("error_text") or ""),
            "event_count": max(0, int(payload.get("event_count") or 0)),
            "last_execution_receipt": dict(payload.get("last_execution_receipt") or {}),
            "enable_child_execution": bool(payload.get("enable_child_execution")),
            "child_max_rounds": max(1, int(payload.get("child_max_rounds") or 12)),
            "child_session_cleanup_mode": str(payload.get("child_session_cleanup_mode") or "ttl"),
            "child_session_cleanup_ttl_seconds": max(0, int(payload.get("child_session_cleanup_ttl_seconds") or 0)),
            "recovery_restart_count": max(0, int(payload.get("recovery_restart_count") or 0)),
        }

    @classmethod
    def _normalize_recovery_state(cls, raw_state: Any) -> Dict[str, Any]:
        payload = dict(raw_state or {}) if isinstance(raw_state, dict) else {}
        raw_jobs = payload.get("jobs")
        normalized_jobs: Dict[str, Dict[str, Any]] = {}
        if isinstance(raw_jobs, dict):
            for key, value in raw_jobs.items():
                envelope = cls._normalize_recovery_job_envelope(value)
                if envelope:
                    normalized_jobs[str(key or envelope["job_id"]).strip() or envelope["job_id"]] = envelope
        pending_job_ids_raw = payload.get("pending_job_ids")
        pending_job_ids: List[str] = []
        if isinstance(pending_job_ids_raw, list):
            for item in pending_job_ids_raw:
                job_id = str(item or "").strip()
                if job_id and job_id not in pending_job_ids:
                    pending_job_ids.append(job_id)
        recent_terminal_jobs_raw = payload.get("recent_terminal_jobs")
        recent_terminal_jobs: List[Dict[str, Any]] = []
        if isinstance(recent_terminal_jobs_raw, list):
            for item in recent_terminal_jobs_raw:
                if not isinstance(item, dict):
                    continue
                job_id = str(item.get("job_id") or "").strip()
                if not job_id:
                    continue
                snapshot = dict(item)
                snapshot["job_id"] = job_id
                recent_terminal_jobs.append(snapshot)
        return {
            "shell_session_id": str(payload.get("shell_session_id") or "").strip(),
            "core_runtime_id": str(payload.get("core_runtime_id") or DEFAULT_CORE_RUNTIME_ID).strip() or DEFAULT_CORE_RUNTIME_ID,
            "mailbox_cursor_seq": max(0, int(payload.get("mailbox_cursor_seq") or 0)),
            "recovery_restart_total": max(0, int(payload.get("recovery_restart_total") or 0)),
            "inbox_dedup_skipped_count": max(0, int(payload.get("inbox_dedup_skipped_count") or 0)),
            "last_dedup_message_seq": max(0, int(payload.get("last_dedup_message_seq") or 0)),
            "pending_job_ids": pending_job_ids,
            "jobs": normalized_jobs,
            "recent_terminal_jobs": recent_terminal_jobs[:_RECOVERY_TERMINAL_JOB_LIMIT],
        }

    def _load_recovery_state(
        self,
        *,
        store: Optional[AgentSessionStore],
        core_execution_session_id: str,
    ) -> Dict[str, Any]:
        if store is None or not core_execution_session_id:
            return self._normalize_recovery_state({})
        try:
            session = store.get(core_execution_session_id)
        except Exception:
            session = None
        if session is None:
            return self._normalize_recovery_state({})
        metadata = session.metadata if isinstance(session.metadata, dict) else {}
        return self._normalize_recovery_state(metadata.get("core_job_recovery_state"))

    def _save_recovery_state(
        self,
        *,
        store: Optional[AgentSessionStore],
        core_execution_session_id: str,
        state: Dict[str, Any],
    ) -> None:
        if store is None or not core_execution_session_id:
            return
        normalized_state = self._normalize_recovery_state(state)
        try:
            store.update_metadata(
                core_execution_session_id,
                {"core_job_recovery_state": normalized_state},
            )
        except Exception:
            logger.debug("Failed to persist core recovery state: %s", core_execution_session_id, exc_info=True)

    def _persist_shell_recovery_metrics(
        self,
        *,
        store: Optional[AgentSessionStore],
        shell_session_id: str,
        core_execution_session_id: str,
    ) -> None:
        if store is None or not shell_session_id or not core_execution_session_id:
            return
        state = self._load_recovery_state(store=store, core_execution_session_id=core_execution_session_id)
        state["shell_session_id"] = str(shell_session_id or "").strip()
        state["core_runtime_id"] = str(state.get("core_runtime_id") or DEFAULT_CORE_RUNTIME_ID).strip() or DEFAULT_CORE_RUNTIME_ID
        state["mailbox_cursor_seq"] = max(
            int(state.get("mailbox_cursor_seq") or 0),
            int(self._shell_mailbox_cursors.get(shell_session_id) or 0),
        )
        state["recovery_restart_total"] = max(
            int(state.get("recovery_restart_total") or 0),
            int(self._shell_recovery_restart_totals.get(shell_session_id) or 0),
        )
        state["inbox_dedup_skipped_count"] = max(
            int(state.get("inbox_dedup_skipped_count") or 0),
            int(self._shell_inbox_dedup_skipped_counts.get(shell_session_id) or 0),
        )
        state["last_dedup_message_seq"] = max(
            int(state.get("last_dedup_message_seq") or 0),
            int(self._shell_last_dedup_message_seq.get(shell_session_id) or 0),
        )
        self._save_recovery_state(store=store, core_execution_session_id=core_execution_session_id, state=state)

    def _record_inbox_dedup_locked(
        self,
        *,
        shell_session_id: str,
        core_execution_session_id: str,
        message_seq: int,
        job_id: str,
    ) -> None:
        session_id = str(shell_session_id or "").strip()
        if not session_id:
            return
        self._shell_inbox_dedup_skipped_counts[session_id] = max(
            0,
            int(self._shell_inbox_dedup_skipped_counts.get(session_id) or 0),
        ) + 1
        self._shell_last_dedup_message_seq[session_id] = max(
            int(self._shell_last_dedup_message_seq.get(session_id) or 0),
            max(0, int(message_seq or 0)),
        )
        normalized_job_id = str(job_id or "").strip()
        envelope: Dict[str, Any] = {}
        if normalized_job_id:
            job = self._jobs.get(normalized_job_id)
            if job is not None:
                job.handoff_duplicate_count = max(0, int(job.handoff_duplicate_count or 0)) + 1
                envelope = self._build_job_envelope_from_locked_state(normalized_job_id)
        if envelope:
            self._persist_job_recovery_state(
                store=self._runtime_defaults.store,
                core_execution_session_id=str(core_execution_session_id or "").strip(),
                job_envelope=envelope,
                mailbox_cursor_seq=int(self._shell_mailbox_cursors.get(session_id) or 0),
            )
        self._persist_shell_recovery_metrics(
            store=self._runtime_defaults.store,
            shell_session_id=session_id,
            core_execution_session_id=str(core_execution_session_id or "").strip(),
        )

    def _persist_job_recovery_state(
        self,
        *,
        store: Optional[AgentSessionStore],
        core_execution_session_id: str,
        job_envelope: Dict[str, Any],
        terminal_snapshot: Optional[Dict[str, Any]] = None,
        mailbox_cursor_seq: Optional[int] = None,
    ) -> None:
        if store is None or not core_execution_session_id:
            return
        state = self._load_recovery_state(store=store, core_execution_session_id=core_execution_session_id)
        envelope = self._normalize_recovery_job_envelope(job_envelope)
        if not envelope:
            return
        state["shell_session_id"] = str(envelope.get("shell_session_id") or state.get("shell_session_id") or "").strip()
        state["core_runtime_id"] = str(envelope.get("core_runtime_id") or state.get("core_runtime_id") or DEFAULT_CORE_RUNTIME_ID).strip() or DEFAULT_CORE_RUNTIME_ID
        if mailbox_cursor_seq is not None:
            state["mailbox_cursor_seq"] = max(
                int(state.get("mailbox_cursor_seq") or 0),
                max(0, int(mailbox_cursor_seq or 0)),
            )
        else:
            state["mailbox_cursor_seq"] = max(
                int(state.get("mailbox_cursor_seq") or 0),
                max(
                    int(envelope.get("handoff_message_seq") or 0),
                    int(envelope.get("completion_message_seq") or 0),
                ),
            )
        pending_job_ids = [str(item or "").strip() for item in list(state.get("pending_job_ids") or []) if str(item or "").strip()]
        job_id = str(envelope.get("job_id") or "").strip()
        status = str(envelope.get("status") or "accepted").strip()
        if status in _RECOVERABLE_JOB_STATUSES:
            state_jobs = dict(state.get("jobs") or {})
            state_jobs[job_id] = envelope
            state["jobs"] = state_jobs
            if job_id not in pending_job_ids:
                pending_job_ids.append(job_id)
        else:
            state_jobs = dict(state.get("jobs") or {})
            state_jobs.pop(job_id, None)
            state["jobs"] = state_jobs
            pending_job_ids = [item for item in pending_job_ids if item != job_id]
            if isinstance(terminal_snapshot, dict) and str(terminal_snapshot.get("job_id") or "").strip():
                archived = [dict(item) for item in list(state.get("recent_terminal_jobs") or []) if isinstance(item, dict)]
                archived = [item for item in archived if str(item.get("job_id") or "").strip() != job_id]
                archived.append(dict(terminal_snapshot))
                archived.sort(key=lambda item: str(item.get("updated_at") or item.get("completed_at") or item.get("created_at") or ""), reverse=True)
                state["recent_terminal_jobs"] = archived[:_RECOVERY_TERMINAL_JOB_LIMIT]
        state["pending_job_ids"] = pending_job_ids
        self._save_recovery_state(store=store, core_execution_session_id=core_execution_session_id, state=state)

    def _build_job_envelope_from_locked_state(self, job_id: str) -> Dict[str, Any]:
        job = self._jobs.get(str(job_id or "").strip())
        if job is None:
            return {}
        spec = self._job_specs.get(job.job_id)
        child_execution_mode = bool(spec.enable_child_execution) if spec is not None else bool(self._runtime_defaults.enable_child_execution)
        state = self._load_recovery_state(store=self._runtime_defaults.store, core_execution_session_id=job.core_execution_session_id)
        existing_envelope = dict((state.get("jobs") or {}).get(job.job_id) or {})
        child_max_rounds = max(
            1,
            int(
                spec.child_max_rounds
                if spec is not None
                else existing_envelope.get("child_max_rounds")
                or self._runtime_defaults.child_max_rounds
                or 12
            ),
        )
        cleanup_mode = str(spec.child_session_cleanup_mode if spec is not None else self._runtime_defaults.child_session_cleanup_mode or "ttl")
        cleanup_ttl = max(
            0,
            int(
                spec.child_session_cleanup_ttl_seconds
                if spec is not None
                else self._runtime_defaults.child_session_cleanup_ttl_seconds
                or 0
            ),
        )
        existing_restart_count = max(0, int(existing_envelope.get("recovery_restart_count") or 0))
        return {
            "job_id": job.job_id,
            "shell_session_id": job.shell_session_id,
            "core_runtime_id": job.core_runtime_id,
            "run_context_id": job.core_execution_session_id,
            "core_execution_session_id": job.core_execution_session_id,
            "goal": job.goal,
            "risk_level": job.risk_level,
            "handoff_source": job.handoff_source,
            "route_summary": dict(job.route_summary or {}),
            "route_decision": dict(spec.route_decision or {}) if spec is not None else {},
            "dispatch_payload": dict(spec.dispatch_payload or {}) if spec is not None else {},
            "run_context_created": bool(job.core_execution_session_created),
            "core_execution_session_created": bool(job.core_execution_session_created),
            "handoff_message_seq": int(job.handoff_message_seq or 0),
            "completion_message_seq": int(job.completion_message_seq or 0),
            "handoff_duplicate_count": int(job.handoff_duplicate_count or 0),
            "recovery_restart_count": int(job.recovery_restart_count or existing_restart_count or 0),
            "status": str(job.status or "accepted"),
            "created_at": str(job.created_at or ""),
            "started_at": str(job.started_at or ""),
            "updated_at": str(job.updated_at or ""),
            "completed_at": str(job.completed_at or ""),
            "pipeline_id": str(job.pipeline_id or ""),
            "last_event_type": str(job.last_event_type or ""),
            "last_event_at": str(job.last_event_at or ""),
            "pipeline_end_reason": str(job.pipeline_end_reason or ""),
            "error_text": str(job.error_text or ""),
            "event_count": int(job.event_count or 0),
            "last_execution_receipt": dict(job.last_execution_receipt or {}),
            "enable_child_execution": child_execution_mode,
            "child_max_rounds": child_max_rounds,
            "child_session_cleanup_mode": cleanup_mode,
            "child_session_cleanup_ttl_seconds": cleanup_ttl,
        }

    def _recover_shell_state(self, shell_session_id: str) -> None:
        defaults = self._runtime_defaults
        store = defaults.store
        session_id = str(shell_session_id or "").strip()
        if store is None or not session_id:
            return
        core_execution_session_id = _build_shell_core_execution_session_id(
            shell_session_id=session_id,
            core_runtime_id=DEFAULT_CORE_RUNTIME_ID,
        )
        state = self._load_recovery_state(store=store, core_execution_session_id=core_execution_session_id)
        jobs = dict(state.get("jobs") or {})
        if not jobs and not state.get("recent_terminal_jobs"):
            return
        with self._lock:
            self._known_core_runtime_ids.add(
                str(state.get("core_runtime_id") or DEFAULT_CORE_RUNTIME_ID).strip() or DEFAULT_CORE_RUNTIME_ID
            )
            self._shell_core_sessions[session_id] = str(
                state.get("core_execution_session_id")
                or core_execution_session_id
            ).strip() or core_execution_session_id
            if defaults.mailbox is not None:
                self._shell_mailboxes[session_id] = defaults.mailbox
            self._shell_mailbox_cursors[session_id] = max(
                int(self._shell_mailbox_cursors.get(session_id) or 0),
                int(state.get("mailbox_cursor_seq") or 0),
            )
            self._shell_recovery_restart_totals[session_id] = max(
                int(self._shell_recovery_restart_totals.get(session_id) or 0),
                int(state.get("recovery_restart_total") or 0),
            )
            self._shell_inbox_dedup_skipped_counts[session_id] = max(
                int(self._shell_inbox_dedup_skipped_counts.get(session_id) or 0),
                int(state.get("inbox_dedup_skipped_count") or 0),
            )
            self._shell_last_dedup_message_seq[session_id] = max(
                int(self._shell_last_dedup_message_seq.get(session_id) or 0),
                int(state.get("last_dedup_message_seq") or 0),
            )
            if defaults.mailbox is not None:
                self._hydrate_shell_queue_from_mailbox_locked(session_id)
            archived = [dict(item) for item in list(state.get("recent_terminal_jobs") or []) if isinstance(item, dict)]
            if archived:
                existing_archived = {
                    str(item.get("job_id") or "").strip(): dict(item)
                    for item in list(self._shell_archived_jobs.get(session_id) or [])
                    if isinstance(item, dict) and str(item.get("job_id") or "").strip()
                }
                for item in archived:
                    existing_archived[str(item.get("job_id") or "").strip()] = dict(item)
                self._shell_archived_jobs[session_id] = list(existing_archived.values())
            pending_job_ids = [str(item or "").strip() for item in list(state.get("pending_job_ids") or []) if str(item or "").strip()]
            recovery_state_changed = False
            for job_id in pending_job_ids:
                envelope = self._normalize_recovery_job_envelope(jobs.get(job_id))
                if not envelope:
                    continue
                if job_id not in self._jobs:
                    envelope["recovery_restart_count"] = max(0, int(envelope.get("recovery_restart_count") or 0)) + 1
                    self._shell_recovery_restart_totals[session_id] = max(
                        0,
                        int(self._shell_recovery_restart_totals.get(session_id) or 0),
                    ) + 1
                    recovered_job = CoreDispatchJob(
                        job_id=job_id,
                        shell_session_id=session_id,
                        core_runtime_id=str(envelope.get("core_runtime_id") or DEFAULT_CORE_RUNTIME_ID),
                        core_execution_session_id=str(envelope.get("core_execution_session_id") or core_execution_session_id),
                        goal=str(envelope.get("goal") or ""),
                        risk_level=str(envelope.get("risk_level") or ""),
                        handoff_source=str(envelope.get("handoff_source") or ""),
                        route_summary=dict(envelope.get("route_summary") or {}),
                        core_execution_session_created=bool(envelope.get("core_execution_session_created")),
                        handoff_message_seq=int(envelope.get("handoff_message_seq") or 0),
                        completion_message_seq=int(envelope.get("completion_message_seq") or 0),
                        handoff_duplicate_count=int(envelope.get("handoff_duplicate_count") or 0),
                        recovery_restart_count=int(envelope.get("recovery_restart_count") or 0),
                        status=str(envelope.get("status") or "accepted"),
                        created_at=str(envelope.get("created_at") or _utc_now_iso()),
                        started_at=str(envelope.get("started_at") or ""),
                        updated_at=str(envelope.get("updated_at") or _utc_now_iso()),
                        completed_at=str(envelope.get("completed_at") or ""),
                        pipeline_id=str(envelope.get("pipeline_id") or ""),
                        last_event_type=str(envelope.get("last_event_type") or ""),
                        last_event_at=str(envelope.get("last_event_at") or ""),
                        pipeline_end_reason=str(envelope.get("pipeline_end_reason") or ""),
                        error_text=str(envelope.get("error_text") or ""),
                        last_execution_receipt=dict(envelope.get("last_execution_receipt") or {}),
                        event_count=max(0, int(envelope.get("event_count") or 0)),
                    )
                    self._jobs[job_id] = recovered_job
                    jobs[job_id] = dict(envelope)
                    recovery_state_changed = True
                if job_id not in self._shell_jobs[session_id]:
                    self._shell_jobs[session_id].append(job_id)
                if job_id not in self._job_specs:
                    self._job_specs[job_id] = CoreDispatchJobRunSpec(
                        runner=defaults.runner or run_multi_agent_pipeline,
                        goal=str(envelope.get("goal") or ""),
                        risk_level=str(envelope.get("risk_level") or ""),
                        route_decision=dict(envelope.get("route_decision") or {}),
                        dispatch_payload=dict(envelope.get("dispatch_payload") or {}),
                        core_execution_session_id=str(envelope.get("core_execution_session_id") or core_execution_session_id),
                        core_runtime_id=str(envelope.get("core_runtime_id") or DEFAULT_CORE_RUNTIME_ID),
                        store=store,
                        mailbox=defaults.mailbox,
                        task_board_engine=defaults.task_board_engine,
                        child_llm_call=defaults.child_llm_call,
                        child_tool_executor=defaults.child_tool_executor,
                        enable_child_execution=bool(envelope.get("enable_child_execution")),
                        child_max_rounds=max(
                            1,
                            int(envelope.get("child_max_rounds") or defaults.child_max_rounds or 12),
                        ),
                        child_session_cleanup_mode=str(envelope.get("child_session_cleanup_mode") or defaults.child_session_cleanup_mode or "ttl"),
                        child_session_cleanup_ttl_seconds=max(
                            0,
                            int(envelope.get("child_session_cleanup_ttl_seconds") or defaults.child_session_cleanup_ttl_seconds or 0),
                        ),
                    )
                current_job_id = str(self._shell_current_jobs.get(session_id) or "").strip()
                queued_job_ids = {
                    str(item or "").strip()
                    for item in list(self._shell_queues.get(session_id) or [])
                    if str(item or "").strip()
                }
                if (
                    str(envelope.get("status") or "").strip() in _QUEUEABLE_JOB_STATUSES
                    and job_id != current_job_id
                    and job_id not in queued_job_ids
                ):
                    self._shell_queues[session_id].append(job_id)
            running_loop: Optional[asyncio.AbstractEventLoop] = None
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None
            if running_loop is not None:
                for job_id in pending_job_ids:
                    job = self._jobs.get(job_id)
                    if job is None or str(job.status or "").strip() not in _RECOVERABLE_JOB_STATUSES:
                        continue
                    self._start_job_heartbeat_locked(job_id, loop=running_loop)
            if (
                running_loop is not None
                and (
                    str(self._shell_current_jobs.get(session_id) or "").strip()
                    or bool(self._shell_queues.get(session_id))
                )
            ):
                self._reserve_shell_current_job_locked(session_id)
                self._start_shell_worker_locked(session_id, loop=running_loop)
        self._start_runtime_monitor_if_possible()
        if recovery_state_changed:
            state["jobs"] = jobs
            state["recovery_restart_total"] = max(
                int(state.get("recovery_restart_total") or 0),
                int(self._shell_recovery_restart_totals.get(session_id) or 0),
            )
            self._save_recovery_state(store=store, core_execution_session_id=core_execution_session_id, state=state)
        else:
            self._persist_shell_recovery_metrics(
                store=store,
                shell_session_id=session_id,
                core_execution_session_id=core_execution_session_id,
            )

    @staticmethod
    def _can_reuse_worker_task(task: Optional[asyncio.Task[Any]], *, loop: Optional[asyncio.AbstractEventLoop] = None) -> bool:
        if task is None or task.done() or task.cancelled():
            return False
        try:
            task_loop = task.get_loop()
        except Exception:
            return False
        if loop is None:
            try:
                return not task_loop.is_closed()
            except Exception:
                return False
        return task_loop is loop and not task_loop.is_closed()

    def _collect_job_pending_descendants_locked(self, job: CoreDispatchJob) -> List[Dict[str, Any]]:
        if str(job.status or "").strip() != "waiting_descendants":
            return []
        if not str(job.pipeline_id or "").strip():
            return []
        spec = self._job_specs.get(job.job_id)
        if spec is None or spec.store is None:
            return []
        reports: List[Dict[str, Any]] = []
        try:
            core = CoreAgent(
                store=spec.store,
                mailbox=spec.mailbox,
                task_board_engine=spec.task_board_engine,
            )
            reports = core.collect_reports(
                job.core_execution_session_id,
                pipeline_id=str(job.pipeline_id or ""),
            )
        except Exception:
            logger.debug(
                "Failed to collect core reports for waiting-descendants job: %s",
                job.job_id,
                exc_info=True,
            )
            reports = []
        try:
            return list(
                collect_core_pending_descendants(
                    store=spec.store,
                    core_execution_session_id=job.core_execution_session_id,
                    pipeline_id=str(job.pipeline_id or ""),
                    reports=reports,
                )
                or []
            )
        except Exception:
            logger.debug(
                "Failed to collect pending descendants for core job: %s",
                job.job_id,
                exc_info=True,
            )
            return []

    def _collect_job_reconcile_payload_locked(self, job: CoreDispatchJob) -> Dict[str, Any]:
        spec = self._job_specs.get(job.job_id)
        if spec is None or spec.store is None:
            return {}
        pipeline_id = str(job.pipeline_id or "").strip()
        if not pipeline_id:
            return {}
        store = spec.store
        core = CoreAgent(
            store=store,
            mailbox=spec.mailbox,
            task_board_engine=spec.task_board_engine,
        )
        reports = core.collect_reports(job.core_execution_session_id, pipeline_id=pipeline_id)
        root_children = [
            child
            for child in list(store.list_children(job.core_execution_session_id) or [])
            if str((getattr(child, "metadata", {}) or {}).get("pipeline_id") or "").strip() == pipeline_id
        ]
        expert_results: List[Dict[str, Any]] = []
        expert_heartbeat_summaries: List[Dict[str, Any]] = []
        for child in root_children:
            if str(getattr(child, "role", "") or "").strip().lower() != "expert":
                continue
            metadata = dict(getattr(child, "metadata", {}) or {})
            expert_results.append(
                {
                    "agent_id": str(getattr(child, "session_id", "") or "").strip(),
                    "expert_type": str(getattr(child, "role", "") or "expert").strip() or "expert",
                    "status": str(getattr(getattr(child, "status", None), "value", getattr(child, "status", "")) or ""),
                }
            )
            heartbeat_summary = metadata.get("heartbeat_summary")
            if isinstance(heartbeat_summary, dict):
                expert_heartbeat_summaries.append(dict(heartbeat_summary))

        review_results: List[Dict[str, Any]] = []
        review_expected_count = 0
        for session in list(store.list_descendants(job.core_execution_session_id) or []):
            metadata = dict(getattr(session, "metadata", {}) or {})
            if str(metadata.get("pipeline_id") or "").strip() != pipeline_id:
                continue
            if bool(metadata.get("superseded")) or bool(metadata.get("heartbeat_superseded")):
                continue
            if str(getattr(session, "role", "") or "").strip().lower() != "review":
                continue
            review_expected_count += 1
            raw_review = metadata.get("review_result")
            if not isinstance(raw_review, dict):
                continue
            review_payload = dict(raw_review)
            review_payload.setdefault("review_agent_id", str(getattr(session, "session_id", "") or "").strip())
            review_payload.setdefault("expert_id", str(getattr(session, "parent_id", "") or "").strip())
            expert_session = store.get(str(getattr(session, "parent_id", "") or "").strip())
            if expert_session is not None:
                review_payload.setdefault(
                    "expert_type",
                    str(getattr(expert_session, "role", "") or "expert").strip() or "expert",
                )
            if not str(review_payload.get("summary") or "").strip():
                review_payload["summary"] = str(metadata.get("completion_report") or "").strip()
            review_results.append(review_payload)

        heartbeat_summary = merge_heartbeat_escalation_summaries(expert_heartbeat_summaries)
        pending_descendants = collect_core_pending_descendants(
            store=store,
            core_execution_session_id=job.core_execution_session_id,
            pipeline_id=pipeline_id,
            reports=reports,
        )
        completion_state = evaluate_core_pipeline_state(
            reports=reports,
            review_results=review_results,
            review_expected_count=review_expected_count,
            heartbeat_summary=heartbeat_summary,
            pending_descendants=pending_descendants,
        )
        return {
            "reports": reports,
            "expert_results": expert_results,
            "review_results": review_results,
            "review_expected_count": review_expected_count,
            "heartbeat_summary": heartbeat_summary,
            "pending_descendants": pending_descendants,
            "completion_state": completion_state,
        }

    def _build_shell_runtime_snapshot_locked(self, shell_session_id: str) -> Dict[str, Any]:
        session_id = str(shell_session_id or "").strip()
        current_job_id = str(self._shell_current_jobs.get(session_id) or "").strip()
        queued_job_ids = [
            str(job_id or "").strip()
            for job_id in list(self._shell_queues.get(session_id) or [])
            if str(job_id or "").strip()
        ]
        worker = self._shell_workers.get(session_id)
        if not self._can_reuse_worker_task(worker):
            if worker is not None:
                self._shell_workers.pop(session_id, None)
            worker = None
        worker_status = "running" if worker is not None else ("unavailable" if current_job_id or queued_job_ids else "idle")
        queue_depth = len(queued_job_ids)
        pipeline_depth = queue_depth + (1 if current_job_id else 0)
        mailbox_cursor_seq = max(0, int(self._shell_mailbox_cursors.get(session_id) or 0))
        recovery_restart_total = max(0, int(self._shell_recovery_restart_totals.get(session_id) or 0))
        inbox_dedup_skipped_count = max(0, int(self._shell_inbox_dedup_skipped_counts.get(session_id) or 0))
        last_dedup_message_seq = max(0, int(self._shell_last_dedup_message_seq.get(session_id) or 0))
        return {
            "worker_status": worker_status,
            "current_job_id": current_job_id,
            "queued_job_ids": queued_job_ids,
            "queue_depth": queue_depth,
            "pipeline_depth": pipeline_depth,
            "mailbox_cursor_seq": mailbox_cursor_seq,
            "recovery_restart_total": recovery_restart_total,
            "inbox_dedup_skipped_count": inbox_dedup_skipped_count,
            "last_dedup_message_seq": last_dedup_message_seq,
        }

    def _build_job_runtime_snapshot_locked(self, job: CoreDispatchJob) -> Dict[str, Any]:
        shell_runtime = self._build_shell_runtime_snapshot_locked(job.shell_session_id)
        current_job_id = str(shell_runtime.get("current_job_id") or "").strip()
        queued_job_ids = list(shell_runtime.get("queued_job_ids") or [])
        queue_position = 0
        if current_job_id == job.job_id:
            queue_position = 1
        elif job.job_id in queued_job_ids:
            queue_position = queued_job_ids.index(job.job_id) + 1 + (1 if current_job_id else 0)
        return {
            **shell_runtime,
            "queue_position": queue_position,
        }

    def _build_job_snapshot_locked(self, job_id: str, *, include_events: bool = True) -> Dict[str, Any]:
        job = self._jobs.get(str(job_id or "").strip())
        if job is None:
            return {}
        payload = job.snapshot(include_events=include_events)
        payload.update(self._build_job_runtime_snapshot_locked(job))
        pending_descendants = self._collect_job_pending_descendants_locked(job)
        payload["pending_descendant_count"] = len(pending_descendants)
        payload["pending_descendant_ids"] = [
            str(item.get("agent_id") or "").strip()
            for item in pending_descendants
            if str(item.get("agent_id") or "").strip()
        ]
        if pending_descendants:
            payload["pending_descendants"] = pending_descendants[:20]
        return payload

    def _hydrate_shell_queue_from_mailbox_locked(self, shell_session_id: str) -> None:
        session_id = str(shell_session_id or "").strip()
        if not session_id:
            return
        mailbox = self._shell_mailboxes.get(session_id)
        core_execution_session_id = str(self._shell_core_sessions.get(session_id) or "").strip()
        if mailbox is None or not core_execution_session_id or not callable(getattr(mailbox, "read", None)):
            return
        since_seq = max(0, int(self._shell_mailbox_cursors.get(session_id) or 0))
        try:
            messages = mailbox.read(core_execution_session_id, since_seq=since_seq, limit=500, message_type="query")
        except Exception:
            logger.debug("Failed to hydrate core shell queue from mailbox: %s", session_id, exc_info=True)
            return
        if not messages:
            return

        current_job_id = str(self._shell_current_jobs.get(session_id) or "").strip()
        queued_job_ids = {
            str(job_id or "").strip()
            for job_id in list(self._shell_queues.get(session_id) or [])
            if str(job_id or "").strip()
        }
        for message in messages:
            self._shell_mailbox_cursors[session_id] = max(
                int(self._shell_mailbox_cursors.get(session_id) or 0),
                int(message.seq or 0),
            )
            metadata = dict(message.metadata or {})
            job_id = str(
                metadata.get("core_job_id")
                or metadata.get("job_id")
                or ""
            ).strip()
            if not job_id:
                continue
            job = self._jobs.get(job_id)
            if job is not None and not job.handoff_message_seq:
                job.handoff_message_seq = int(message.seq or 0)
            if (
                not job_id
                or job_id == current_job_id
                or job_id in queued_job_ids
                or job is None
                or str(job.status or "").strip() not in _RECOVERABLE_JOB_STATUSES
            ):
                if job_id and (
                    job_id == current_job_id
                    or job_id in queued_job_ids
                    or job is not None
                ):
                    self._record_inbox_dedup_locked(
                        shell_session_id=session_id,
                        core_execution_session_id=core_execution_session_id,
                        message_seq=int(message.seq or 0),
                        job_id=job_id,
                    )
                continue
            self._shell_queues[session_id].append(job_id)
            queued_job_ids.add(job_id)

    def _start_shell_worker_locked(self, shell_session_id: str, *, loop: asyncio.AbstractEventLoop) -> bool:
        session_id = str(shell_session_id or "").strip()
        existing = self._shell_workers.get(session_id)
        if self._can_reuse_worker_task(existing, loop=loop):
            return False
        if existing is not None:
            self._shell_workers.pop(session_id, None)
        worker = loop.create_task(
            self._shell_worker_loop(shell_session_id=session_id),
            name=f"core-dispatch-shell-worker:{session_id or 'default'}",
        )
        self._shell_workers[session_id] = worker
        return True

    def _start_job_heartbeat_locked(self, job_id: str, *, loop: asyncio.AbstractEventLoop) -> bool:
        normalized_job_id = str(job_id or "").strip()
        if not normalized_job_id:
            return False
        existing = self._heartbeat_tasks.get(normalized_job_id)
        if self._can_reuse_worker_task(existing, loop=loop):
            return False
        if existing is not None:
            self._heartbeat_tasks.pop(normalized_job_id, None)
        job = self._jobs.get(normalized_job_id)
        spec = self._job_specs.get(normalized_job_id)
        if job is None or spec is None or spec.store is None:
            return False
        if str(job.status or "").strip() not in _RECOVERABLE_JOB_STATUSES:
            return False
        heartbeat_task = loop.create_task(
            self._heartbeat_loop(
                job_id=normalized_job_id,
                store=spec.store,
                interval_seconds=max(1.0, float(self._runtime_defaults.heartbeat_interval_seconds or 15.0)),
            ),
            name=f"core-dispatch-heartbeat:{normalized_job_id}",
        )
        self._heartbeat_tasks[normalized_job_id] = heartbeat_task
        return True

    def _collect_known_shell_session_ids_locked(self) -> List[str]:
        session_ids = {
            str(item or "").strip()
            for item in (
                list(self._shell_jobs.keys())
                + list(self._shell_mailboxes.keys())
                + list(self._shell_core_sessions.keys())
                + list(self._shell_workers.keys())
                + list(self._shell_current_jobs.keys())
            )
            if str(item or "").strip()
        }
        return sorted(session_ids)

    def _recover_runtime_shell_states(self) -> Dict[str, Any]:
        store = self._runtime_defaults.store
        if store is None or not hasattr(store, "list_sessions"):
            return {"runtime_ids": sorted(self._known_core_runtime_ids), "shell_session_ids": []}
        runtime_ids: Set[str] = set()
        shell_session_ids: Set[str] = set()
        try:
            sessions = list(store.list_sessions(role="core") or [])
        except Exception:
            logger.debug("Failed to enumerate core sessions for runtime recovery", exc_info=True)
            sessions = []
        for session in sessions:
            metadata = dict(getattr(session, "metadata", {}) or {})
            session_id = str(getattr(session, "session_id", "") or "").strip()
            parent_id = str(getattr(session, "parent_id", "") or "").strip()
            agent_type = str(metadata.get("agent_type") or "").strip()
            session_kind = str(metadata.get("session_kind") or "").strip()
            has_recovery_state = isinstance(metadata.get("core_job_recovery_state"), dict)
            if agent_type == "core_runtime":
                runtime_ids.add(session_id or DEFAULT_CORE_RUNTIME_ID)
                continue
            if (
                session_kind != "shell_core_root"
                and not (
                    has_recovery_state
                    and (session_id.endswith("__core") or str(metadata.get("shell_session_id") or "").strip())
                )
            ):
                continue
            shell_session_id = str(metadata.get("shell_session_id") or "").strip()
            if not shell_session_id and session_id.endswith("__core"):
                shell_session_id = session_id[:-len("__core")]
            if not shell_session_id:
                continue
            shell_session_ids.add(shell_session_id)
            runtime_ids.add(
                str(metadata.get("core_runtime_id") or parent_id or DEFAULT_CORE_RUNTIME_ID).strip()
                or DEFAULT_CORE_RUNTIME_ID
            )
            self._recover_shell_state(shell_session_id)
        runtime_ids.update(self._known_core_runtime_ids)
        with self._lock:
            self._known_core_runtime_ids.update(runtime_ids)
        return {
            "runtime_ids": sorted(item for item in runtime_ids if str(item or "").strip()),
            "shell_session_ids": sorted(item for item in shell_session_ids if str(item or "").strip()),
        }

    def _publish_core_runtime_heartbeat(self, *, runtime_id: str, shell_session_count: int, active_job_count: int) -> None:
        store = self._runtime_defaults.store
        normalized_runtime_id = str(runtime_id or DEFAULT_CORE_RUNTIME_ID).strip() or DEFAULT_CORE_RUNTIME_ID
        if store is None or not normalized_runtime_id:
            return
        try:
            if store.get(normalized_runtime_id) is None:
                return
            status = "running" if active_job_count > 0 else "idle"
            store.publish_task_heartbeat(
                normalized_runtime_id,
                task_id="core_runtime_loop",
                scope="runtime",
                status=status,
                message="resident_core_runtime_monitor",
                stage="core_runtime_poll",
                ttl_seconds=max(5, int(max(1.0, float(self._runtime_defaults.heartbeat_interval_seconds or 15.0)) * 3)),
                details={
                    "core_runtime_id": normalized_runtime_id,
                    "shell_session_count": int(shell_session_count),
                    "active_job_count": int(active_job_count),
                },
            )
        except Exception:
            logger.debug("Failed to publish core runtime heartbeat: %s", normalized_runtime_id, exc_info=True)

    def _send_shell_status_update(
        self,
        *,
        shell_session_id: str,
        core_execution_session_id: str,
        core_runtime_id: str,
        job_id: str,
        status: str,
        goal: str,
        pipeline_id: str = "",
        pending_descendant_count: int = 0,
    ) -> int:
        mailbox = self._shell_mailboxes.get(str(shell_session_id or "").strip())
        if mailbox is None or not shell_session_id:
            return 0
        normalized_status = str(status or "").strip().lower()
        if normalized_status not in _SHELL_OUTBOX_SIGNIFICANT_JOB_STATUSES:
            return 0
        metadata = {
            "kind": "core_job_status",
            "status": normalized_status,
            "core_job_id": str(job_id or ""),
            "job_id": str(job_id or ""),
            "core_runtime_id": str(core_runtime_id or DEFAULT_CORE_RUNTIME_ID),
            "core_execution_session_id": str(core_execution_session_id or ""),
            "pipeline_id": str(pipeline_id or ""),
            "pending_descendant_count": max(0, int(pending_descendant_count or 0)),
        }
        content = _build_shell_status_update_text(
            status=normalized_status,
            job_id=str(job_id or ""),
            goal=str(goal or ""),
            pending_descendant_count=max(0, int(pending_descendant_count or 0)),
        )
        try:
            return int(
                mailbox.send(
                    str(core_execution_session_id or core_runtime_id or "core"),
                    str(shell_session_id or ""),
                    content,
                    message_type="status",
                    metadata=metadata,
                )
                or 0
            )
        except Exception:
            logger.debug("Failed to send shell status update for core job: %s", job_id, exc_info=True)
            return 0

    def _start_runtime_monitor_if_possible(self) -> bool:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False
        with self._lock:
            existing = self._runtime_monitor_task
            if self._can_reuse_worker_task(existing, loop=loop):
                return False
            if existing is not None:
                self._runtime_monitor_task = None
            self._runtime_monitor_task = loop.create_task(
                self._runtime_monitor_loop(),
                name="core-dispatch-runtime-monitor",
            )
        return True

    def _runtime_monitor_poll_interval_seconds(self) -> float:
        heartbeat_interval = max(1.0, float(self._runtime_defaults.heartbeat_interval_seconds or 15.0))
        return max(0.5, min(2.0, heartbeat_interval / 3.0))

    async def _runtime_monitor_loop(self) -> None:
        current_task = asyncio.current_task()
        try:
            while True:
                recovery_summary = self._recover_runtime_shell_states()
                runtime_ids = [
                    str(item or "").strip()
                    for item in list(recovery_summary.get("runtime_ids") or [])
                    if str(item or "").strip()
                ]
                loop = asyncio.get_running_loop()
                with self._lock:
                    known_shell_session_ids = set(self._collect_known_shell_session_ids_locked())
                    known_shell_session_ids.update(
                        str(item or "").strip()
                        for item in list(recovery_summary.get("shell_session_ids") or [])
                        if str(item or "").strip()
                    )
                    shell_session_count = len(known_shell_session_ids)
                    active_job_count = 0
                    for job_id, job in list(self._jobs.items()):
                        if str(job.status or "").strip() in _RECOVERABLE_JOB_STATUSES:
                            active_job_count += 1
                            self._start_job_heartbeat_locked(job_id, loop=loop)
                    for shell_session_id in sorted(known_shell_session_ids):
                        self._hydrate_shell_queue_from_mailbox_locked(shell_session_id)
                        current_job_id = self._reserve_shell_current_job_locked(shell_session_id)
                        queued_job_ids = list(self._shell_queues.get(shell_session_id) or [])
                        if current_job_id or queued_job_ids:
                            self._start_shell_worker_locked(shell_session_id, loop=loop)
                for runtime_id in runtime_ids or [DEFAULT_CORE_RUNTIME_ID]:
                    self._publish_core_runtime_heartbeat(
                        runtime_id=runtime_id,
                        shell_session_count=shell_session_count,
                        active_job_count=active_job_count,
                    )
                await asyncio.sleep(self._runtime_monitor_poll_interval_seconds())
        except asyncio.CancelledError:
            raise
        finally:
            with self._lock:
                if self._runtime_monitor_task is current_task:
                    self._runtime_monitor_task = None

    def _reserve_shell_current_job_locked(self, shell_session_id: str) -> str:
        session_id = str(shell_session_id or "").strip()
        if not session_id:
            return ""
        current_job_id = str(self._shell_current_jobs.get(session_id) or "").strip()
        current_job = self._jobs.get(current_job_id)
        if (
            current_job_id
            and current_job is not None
            and str(current_job.status or "").strip() in _QUEUEABLE_JOB_STATUSES
        ):
            return current_job_id
        self._shell_current_jobs.pop(session_id, None)
        queue = self._shell_queues.get(session_id)
        while queue:
            candidate = str(queue.popleft() or "").strip()
            if not candidate:
                continue
            job = self._jobs.get(candidate)
            if job is None or str(job.status or "").strip() not in _QUEUEABLE_JOB_STATUSES:
                continue
            self._shell_current_jobs[session_id] = candidate
            return candidate
        if queue is not None and not queue:
            self._shell_queues.pop(session_id, None)
        return ""

    def _ensure_core_runtime_session(
        self,
        *,
        store: AgentSessionStore,
        core_runtime_id: str,
    ) -> None:
        runtime_id = str(core_runtime_id or DEFAULT_CORE_RUNTIME_ID).strip() or DEFAULT_CORE_RUNTIME_ID
        existing = store.get(runtime_id)
        if existing is None:
            try:
                store.create(
                    role="core",
                    session_id=runtime_id,
                    metadata={
                        "agent_type": "core_runtime",
                        "runtime_kind": "long_lived_core",
                    },
                )
            except ValueError:
                pass
        else:
            try:
                store.update_status(runtime_id, AgentStatus.WAITING)
            except Exception:
                logger.debug("Failed to mark core runtime waiting: %s", runtime_id, exc_info=True)

    @staticmethod
    def _ensure_core_job_session(
        *,
        store: AgentSessionStore,
        core_runtime_id: str,
        core_execution_session_id: str,
        shell_session_id: str,
        job_id: str,
        goal: str,
    ) -> bool:
        existing = store.get(core_execution_session_id)
        created = existing is None
        metadata = {
            "agent_type": "core_session",
            "active_job_id": str(job_id or ""),
            "last_job_id": str(job_id or ""),
            "shell_session_id": str(shell_session_id or ""),
            "core_runtime_id": str(core_runtime_id or DEFAULT_CORE_RUNTIME_ID),
            "latest_goal": str(goal or ""),
            "session_kind": "shell_core_root",
        }
        if existing is None:
            try:
                store.create(
                    role="core",
                    parent_id=str(core_runtime_id or DEFAULT_CORE_RUNTIME_ID),
                    session_id=core_execution_session_id,
                    task_description=str(goal or ""),
                    metadata=metadata,
                )
            except ValueError:
                pass
        try:
            store.update_metadata(core_execution_session_id, metadata)
            store.update_status(core_execution_session_id, AgentStatus.RUNNING)
        except Exception:
            logger.debug("Failed to update core job session metadata: %s", core_execution_session_id, exc_info=True)
        return created

    @staticmethod
    def _ensure_message_session(
        *,
        message_manager: Any,
        shell_session_id: str,
        core_execution_session_id: str,
    ) -> None:
        if message_manager is None or not core_execution_session_id:
            return
        if message_manager.get_session(core_execution_session_id):
            return
        shell_session = message_manager.get_session(shell_session_id) or {}
        temporary = bool(shell_session.get("temporary", False))
        message_manager.create_session(session_id=core_execution_session_id, temporary=temporary)

    def submit_job(
        self,
        *,
        shell_session_id: str,
        goal: str,
        risk_level: str,
        handoff_source: str,
        route_decision: Optional[Dict[str, Any]],
        dispatch_payload: Optional[Dict[str, Any]],
        core_runtime_id: str = DEFAULT_CORE_RUNTIME_ID,
        store: AgentSessionStore,
        message_manager: Any = None,
        pipeline_runner: Optional[Callable[..., AsyncGenerator[Dict[str, Any], None]]] = None,
        child_llm_call: Optional[Callable[..., Any]] = None,
        child_tool_executor: Optional[Callable[..., Any]] = None,
        enable_child_execution: bool = False,
        child_max_rounds: int = 12,
        child_session_cleanup_mode: str = "ttl",
        child_session_cleanup_ttl_seconds: int = 3600,
        mailbox: Any = None,
        task_board_engine: Any = None,
        heartbeat_interval_seconds: float = 15.0,
    ) -> Dict[str, Any]:
        self._recover_shell_state(str(shell_session_id or ""))
        running_loop = asyncio.get_running_loop()
        job_id = f"corejob_{uuid.uuid4().hex[:12]}"
        resolved_core_runtime_id = str(core_runtime_id or DEFAULT_CORE_RUNTIME_ID).strip() or DEFAULT_CORE_RUNTIME_ID
        with self._lock:
            self._known_core_runtime_ids.add(resolved_core_runtime_id)
        core_execution_session_id = _build_shell_core_execution_session_id(
            shell_session_id=str(shell_session_id or ""),
            core_runtime_id=resolved_core_runtime_id,
        )
        self._ensure_core_runtime_session(store=store, core_runtime_id=resolved_core_runtime_id)
        core_execution_session_created = self._ensure_core_job_session(
            store=store,
            core_runtime_id=resolved_core_runtime_id,
            core_execution_session_id=core_execution_session_id,
            shell_session_id=shell_session_id,
            job_id=job_id,
            goal=goal,
        )
        self._ensure_message_session(
            message_manager=message_manager,
            shell_session_id=shell_session_id,
            core_execution_session_id=core_execution_session_id,
        )

        job = CoreDispatchJob(
            job_id=job_id,
            shell_session_id=str(shell_session_id or ""),
            core_runtime_id=resolved_core_runtime_id,
            core_execution_session_id=core_execution_session_id,
            goal=str(goal or ""),
            risk_level=str(risk_level or "").strip(),
            handoff_source=str(handoff_source or "").strip(),
            route_summary=_coerce_route_summary(route_decision or {}, dispatch_payload or {}),
            core_execution_session_created=bool(core_execution_session_created),
        )
        handoff_message_seq = 0
        if mailbox is not None and core_execution_session_id:
            handoff_metadata = {
                "job_id": job_id,
                "core_job_id": job_id,
                "shell_session_id": str(shell_session_id or ""),
                "core_runtime_id": resolved_core_runtime_id,
                "core_execution_session_id": core_execution_session_id,
                "risk_level": str(risk_level or "").strip(),
                "handoff_source": str(handoff_source or "").strip(),
                "route_summary": dict(job.route_summary or {}),
                "dispatch_kind": "shell_to_core",
            }
            try:
                handoff_message_seq = int(
                    mailbox.send(
                        str(shell_session_id or "shell"),
                        core_execution_session_id,
                        str(goal or ""),
                        message_type="query",
                        metadata=handoff_metadata,
                    )
                    or 0
                )
            except Exception:
                logger.debug("Failed to persist core handoff mailbox message: %s", job_id, exc_info=True)
        job.handoff_message_seq = max(0, int(handoff_message_seq or 0))
        with self._lock:
            self._jobs[job_id] = job
            self._shell_jobs[job.shell_session_id].append(job_id)
            if mailbox is not None:
                self._shell_mailboxes[job.shell_session_id] = mailbox
                self._shell_core_sessions[job.shell_session_id] = core_execution_session_id
            self._job_specs[job_id] = CoreDispatchJobRunSpec(
                runner=pipeline_runner or run_multi_agent_pipeline,
                goal=str(goal or ""),
                risk_level=str(risk_level or ""),
                route_decision=dict(route_decision or {}),
                dispatch_payload=dict(dispatch_payload or {}),
                core_execution_session_id=core_execution_session_id,
                core_runtime_id=resolved_core_runtime_id,
                store=store,
                mailbox=mailbox,
                task_board_engine=task_board_engine,
                child_llm_call=child_llm_call,
                child_tool_executor=child_tool_executor,
                enable_child_execution=enable_child_execution,
                child_max_rounds=max(1, int(child_max_rounds or 0)),
                child_session_cleanup_mode=str(child_session_cleanup_mode or "ttl"),
                child_session_cleanup_ttl_seconds=max(0, int(child_session_cleanup_ttl_seconds or 0)),
            )
            if mailbox is not None:
                self._hydrate_shell_queue_from_mailbox_locked(job.shell_session_id)
            current_job_id = str(self._shell_current_jobs.get(job.shell_session_id) or "").strip()
            queued_job_ids = {
                str(item or "").strip()
                for item in list(self._shell_queues.get(job.shell_session_id) or [])
                if str(item or "").strip()
            }
            if (
                mailbox is None
                or handoff_message_seq <= 0
                or (job_id != current_job_id and job_id not in queued_job_ids)
            ):
                self._shell_queues[job.shell_session_id].append(job_id)
            self._reserve_shell_current_job_locked(job.shell_session_id)
            self._start_shell_worker_locked(job.shell_session_id, loop=running_loop)
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(
                job_id=job_id,
                store=store,
                interval_seconds=max(1.0, float(heartbeat_interval_seconds or 15.0)),
            ),
            name=f"core-dispatch-heartbeat:{job_id}",
        )
        with self._lock:
            self._heartbeat_tasks[job_id] = heartbeat_task
            snapshot = self._build_job_snapshot_locked(job_id)
            envelope = self._build_job_envelope_from_locked_state(job_id)
            cursor_seq = int(self._shell_mailbox_cursors.get(job.shell_session_id) or 0)
        self._start_runtime_monitor_if_possible()
        self._persist_job_recovery_state(
            store=store,
            core_execution_session_id=core_execution_session_id,
            job_envelope=envelope,
            mailbox_cursor_seq=max(cursor_seq, int(job.handoff_message_seq or 0)),
        )
        return snapshot

    async def _shell_worker_loop(self, *, shell_session_id: str) -> None:
        current_task = asyncio.current_task()
        try:
            while True:
                with self._lock:
                    worker = self._shell_workers.get(str(shell_session_id or ""))
                    if worker is not current_task:
                        return
                    self._hydrate_shell_queue_from_mailbox_locked(str(shell_session_id or ""))
                    job_id = self._reserve_shell_current_job_locked(str(shell_session_id or ""))
                    queue = self._shell_queues.get(str(shell_session_id or ""))
                    if not job_id:
                        self._shell_current_jobs.pop(str(shell_session_id or ""), None)
                        self._shell_workers.pop(str(shell_session_id or ""), None)
                        if queue is not None and not queue:
                            self._shell_queues.pop(str(shell_session_id or ""), None)
                        return
                    self._job_tasks[job_id] = current_task

                spec = self._job_specs.get(job_id)
                if spec is None:
                    logger.warning("Missing core dispatch job spec: %s", job_id)
                    with self._lock:
                        job = self._jobs.get(job_id)
                        if job is not None:
                            job.status = "failed"
                            job.updated_at = _utc_now_iso()
                            job.completed_at = job.updated_at
                            job.pipeline_end_reason = "missing_job_spec"
                            job.error_text = "missing core dispatch job spec"
                            if not job.last_event_type:
                                job.last_event_type = "pipeline_end"
                            if not job.last_event_at:
                                job.last_event_at = job.updated_at
                        heartbeat_task = self._heartbeat_tasks.pop(job_id, None)
                        self._job_tasks.pop(job_id, None)
                        self._job_specs.pop(job_id, None)
                    if heartbeat_task is not None and not heartbeat_task.done():
                        heartbeat_task.cancel()
                    continue
                try:
                    await self._run_job(
                        job_id=job_id,
                        runner=spec.runner,
                        goal=spec.goal,
                        risk_level=spec.risk_level,
                        route_decision=dict(spec.route_decision or {}),
                        dispatch_payload=dict(spec.dispatch_payload or {}),
                        core_execution_session_id=spec.core_execution_session_id,
                        core_runtime_id=spec.core_runtime_id,
                        store=spec.store,
                        mailbox=spec.mailbox,
                        task_board_engine=spec.task_board_engine,
                        child_llm_call=spec.child_llm_call,
                        child_tool_executor=spec.child_tool_executor,
                        enable_child_execution=spec.enable_child_execution,
                        child_max_rounds=spec.child_max_rounds,
                        child_session_cleanup_mode=spec.child_session_cleanup_mode,
                        child_session_cleanup_ttl_seconds=spec.child_session_cleanup_ttl_seconds,
                    )
                finally:
                    with self._lock:
                        if self._shell_current_jobs.get(str(shell_session_id or "")) == job_id:
                            self._shell_current_jobs.pop(str(shell_session_id or ""), None)
        finally:
            with self._lock:
                worker = self._shell_workers.get(str(shell_session_id or ""))
                if worker is current_task:
                    self._shell_workers.pop(str(shell_session_id or ""), None)
                if not self._shell_queues.get(str(shell_session_id or "")):
                    self._shell_queues.pop(str(shell_session_id or ""), None)
                self._shell_current_jobs.pop(str(shell_session_id or ""), None)

    async def _run_job(
        self,
        *,
        job_id: str,
        runner: Callable[..., AsyncGenerator[Dict[str, Any], None]],
        goal: str,
        risk_level: str,
        route_decision: Dict[str, Any],
        dispatch_payload: Dict[str, Any],
        core_execution_session_id: str,
        core_runtime_id: str,
        store: AgentSessionStore,
        mailbox: Any,
        task_board_engine: Any,
        child_llm_call: Optional[Callable[..., Any]],
        child_tool_executor: Optional[Callable[..., Any]],
        enable_child_execution: bool,
        child_max_rounds: int,
        child_session_cleanup_mode: str,
        child_session_cleanup_ttl_seconds: int,
    ) -> None:
        self._mark_job_running(job_id)
        saw_completed_receipt = False
        pipeline_end_reason = ""
        error_text = ""
        try:
            async for event in runner(
                message=str(goal or ""),
                session_id=core_execution_session_id,
                risk_level=str(risk_level or ""),
                route_decision=dict(route_decision or {}),
                dispatch_payload=dict(dispatch_payload or {}),
                forced_route_semantic="core_execution",
                core_execution_session_id=core_execution_session_id,
                child_llm_call=child_llm_call,
                child_tool_executor=child_tool_executor,
                enable_child_execution=enable_child_execution,
                child_max_rounds=max(1, int(child_max_rounds or 0)),
                child_session_cleanup_mode=str(child_session_cleanup_mode or "ttl"),
                child_session_cleanup_ttl_seconds=max(0, int(child_session_cleanup_ttl_seconds or 0)),
                store=store,
                mailbox=mailbox,
                task_board_engine=task_board_engine,
            ):
                if not isinstance(event, dict):
                    continue
                self._record_event(job_id, event)
                if str(event.get("type") or "").strip() == "execution_receipt":
                    agent_state = event.get("agent_state") if isinstance(event.get("agent_state"), dict) else {}
                    if bool(agent_state.get("task_completed")):
                        saw_completed_receipt = True
                elif str(event.get("type") or "").strip() == "pipeline_end":
                    pipeline_end_reason = str(event.get("reason") or "").strip()
            final_status = _derive_terminal_status(
                pipeline_end_reason=pipeline_end_reason,
                saw_completed_receipt=saw_completed_receipt,
                error_text=error_text,
            )
        except asyncio.CancelledError:
            final_status = "cancelled"
            error_text = "cancelled"
            raise
        except Exception as exc:
            logger.exception("Core dispatch job failed: %s", job_id)
            final_status = "failed"
            error_text = str(exc)
        finally:
            if final_status == "waiting_descendants":
                self._mark_job_waiting_descendants(
                    job_id=job_id,
                    pipeline_end_reason=pipeline_end_reason,
                    store=store,
                    core_runtime_id=core_runtime_id,
                    core_execution_session_id=core_execution_session_id,
                )
            else:
                self._mark_job_terminal(
                    job_id=job_id,
                    status=final_status,
                    pipeline_end_reason=pipeline_end_reason,
                    error_text=error_text,
                    store=store,
                    core_runtime_id=core_runtime_id,
                    core_execution_session_id=core_execution_session_id,
                )

    async def _heartbeat_loop(
        self,
        *,
        job_id: str,
        store: AgentSessionStore,
        interval_seconds: float,
    ) -> None:
        while True:
            snapshot = self.get_job_snapshot(job_id, include_events=False)
            if not snapshot:
                return
            status = str(snapshot.get("status") or "accepted")
            if status == "waiting_descendants":
                await self._try_advance_waiting_descendants(job_id)
                if self._try_reconcile_waiting_descendants(job_id):
                    return
                snapshot = self.get_job_snapshot(job_id, include_events=False)
                if not snapshot:
                    return
                status = str(snapshot.get("status") or "accepted")
            session_id = str(snapshot.get("core_execution_session_id") or "")
            if session_id:
                if status == "running":
                    heartbeat_status = "running"
                elif status == "accepted":
                    heartbeat_status = "queued"
                else:
                    heartbeat_status = status
                try:
                    store.publish_task_heartbeat(
                        session_id,
                        task_id=str(job_id),
                        scope="pipeline",
                        status=heartbeat_status,
                        message=str(snapshot.get("last_event_type") or status),
                        stage=str(snapshot.get("last_event_type") or ""),
                        ttl_seconds=max(5, int(interval_seconds * 3)),
                        details={
                            "job_id": str(job_id),
                            "shell_session_id": str(snapshot.get("shell_session_id") or ""),
                            "core_runtime_id": str(snapshot.get("core_runtime_id") or ""),
                            "pipeline_id": str(snapshot.get("pipeline_id") or ""),
                        },
                    )
                except Exception:
                    logger.debug("Failed to publish core job heartbeat: %s", job_id, exc_info=True)
            if status not in _RECOVERABLE_JOB_STATUSES:
                return
            await asyncio.sleep(interval_seconds)

    def _mark_job_running(self, job_id: str) -> None:
        now = _utc_now_iso()
        envelope: Dict[str, Any] = {}
        core_execution_session_id = ""
        core_runtime_id = DEFAULT_CORE_RUNTIME_ID
        shell_session_id = ""
        goal = ""
        pipeline_id = ""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = "running"
            job.started_at = job.started_at or now
            job.updated_at = now
            job.last_event_at = now
            job.last_event_type = "pipeline_start"
            core_execution_session_id = str(job.core_execution_session_id or "")
            core_runtime_id = str(job.core_runtime_id or DEFAULT_CORE_RUNTIME_ID)
            shell_session_id = str(job.shell_session_id or "")
            goal = str(job.goal or "")
            pipeline_id = str(job.pipeline_id or "")
            envelope = self._build_job_envelope_from_locked_state(job_id)
        self._persist_job_recovery_state(
            store=self._runtime_defaults.store,
            core_execution_session_id=core_execution_session_id,
            job_envelope=envelope,
        )
        if shell_session_id:
            self._send_shell_status_update(
                shell_session_id=shell_session_id,
                core_execution_session_id=core_execution_session_id,
                core_runtime_id=core_runtime_id,
                job_id=job_id,
                status="running",
                goal=goal,
                pipeline_id=pipeline_id,
                pending_descendant_count=0,
            )

    def _record_event(self, job_id: str, event: Dict[str, Any]) -> None:
        now = _utc_now_iso()
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            event_type = str(event.get("type") or "").strip()
            if event_type == "execution_receipt":
                agent_state = event.get("agent_state") if isinstance(event.get("agent_state"), dict) else {}
                shell_runtime = self._build_shell_runtime_snapshot_locked(job.shell_session_id)
                core_dispatch_state = {
                    "job_id": str(job.job_id or ""),
                    "shell_session_id": str(job.shell_session_id or ""),
                    "core_runtime_id": str(job.core_runtime_id or ""),
                    "core_execution_session_id": str(job.core_execution_session_id or ""),
                    "handoff_message_seq": int(job.handoff_message_seq or 0),
                    "completion_message_seq": int(job.completion_message_seq or 0),
                    "handoff_duplicate_count": int(job.handoff_duplicate_count or 0),
                    "recovery_restart_count": int(job.recovery_restart_count or 0),
                    "shell_recovery_restart_total": int(shell_runtime.get("recovery_restart_total") or 0),
                    "shell_inbox_dedup_skipped_count": int(shell_runtime.get("inbox_dedup_skipped_count") or 0),
                    "shell_last_dedup_message_seq": int(shell_runtime.get("last_dedup_message_seq") or 0),
                }
                enriched_agent_state = dict(agent_state)
                enriched_agent_state["core_dispatch"] = core_dispatch_state
                enriched_agent_state["core_job_id"] = str(job.job_id or "")
                enriched_agent_state["core_recovery_restart_count"] = int(job.recovery_restart_count or 0)
                enriched_agent_state["core_handoff_duplicate_count"] = int(job.handoff_duplicate_count or 0)
                enriched_agent_state["core_shell_recovery_restart_total"] = int(shell_runtime.get("recovery_restart_total") or 0)
                enriched_agent_state["core_shell_inbox_dedup_skipped_count"] = int(shell_runtime.get("inbox_dedup_skipped_count") or 0)
                event = dict(event)
                event["agent_state"] = enriched_agent_state
            job.updated_at = now
            job.last_event_at = now
            job.last_event_type = event_type
            job.event_count += 1
            pipeline_id = str(event.get("pipeline_id") or "").strip()
            if pipeline_id:
                job.pipeline_id = pipeline_id
            if event_type == "execution_receipt":
                job.last_execution_receipt = dict(event)
            if event_type == "pipeline_end":
                job.pipeline_end_reason = str(event.get("reason") or "").strip()
            job.recent_events.append(_summarize_event(event))

    def _mark_job_terminal(
        self,
        *,
        job_id: str,
        status: str,
        pipeline_end_reason: str,
        error_text: str,
        store: AgentSessionStore,
        core_runtime_id: str,
        core_execution_session_id: str,
    ) -> None:
        now = _utc_now_iso()
        heartbeat_task: Optional[asyncio.Task[Any]] = None
        shell_session_id = ""
        completion_message_seq = 0
        mailbox = None
        final_summary = ""
        terminal_snapshot: Dict[str, Any] = {}
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = str(status or "failed")
                job.updated_at = now
                job.completed_at = now
                if pipeline_end_reason:
                    job.pipeline_end_reason = str(pipeline_end_reason)
                if error_text:
                    job.error_text = str(error_text)
                if not job.last_event_type:
                    job.last_event_type = "pipeline_end"
                if not job.last_event_at:
                    job.last_event_at = now
                shell_session_id = str(job.shell_session_id or "").strip()
                final_answer = ""
                if isinstance(job.last_execution_receipt, dict):
                    agent_state = job.last_execution_receipt.get("agent_state")
                    if isinstance(agent_state, dict):
                        final_answer = str(
                            agent_state.get("final_answer")
                            or agent_state.get("completion_summary")
                            or ""
                        ).strip()
                if final_answer:
                    final_summary = _truncate_text(final_answer, limit=320)
                elif error_text:
                    final_summary = _truncate_text(error_text, limit=320)
                elif pipeline_end_reason:
                    final_summary = _truncate_text(pipeline_end_reason, limit=320)
                mailbox = self._shell_mailboxes.get(shell_session_id)
            heartbeat_task = self._heartbeat_tasks.pop(job_id, None)
            self._job_tasks.pop(job_id, None)
            self._job_specs.pop(job_id, None)

        if heartbeat_task is not None and not heartbeat_task.done():
            heartbeat_task.cancel()

        if mailbox is not None and shell_session_id:
            report_metadata = {
                "job_id": str(job_id or ""),
                "core_job_id": str(job_id or ""),
                "core_runtime_id": str(core_runtime_id or ""),
                "core_execution_session_id": str(core_execution_session_id or ""),
                "status": str(status or ""),
                "pipeline_end_reason": str(pipeline_end_reason or ""),
                "error_text": str(error_text or ""),
            }
            report_content = f"[CORE {str(status or '').upper()}] {final_summary}".strip()
            try:
                completion_message_seq = int(
                    mailbox.send(
                        str(core_execution_session_id or core_runtime_id or "core"),
                        shell_session_id,
                        report_content,
                        message_type="report",
                        metadata=report_metadata,
                    )
                    or 0
                )
            except Exception:
                logger.debug("Failed to persist core completion mailbox message: %s", job_id, exc_info=True)
        if completion_message_seq > 0:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None:
                    job.completion_message_seq = completion_message_seq
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                terminal_snapshot = job.snapshot(include_events=False)
                terminal_snapshot.update(
                    {
                        "worker_status": "idle",
                        "current_job_id": "",
                        "queued_job_ids": [],
                        "queue_depth": 0,
                        "pipeline_depth": 0,
                        "mailbox_cursor_seq": int(self._shell_mailbox_cursors.get(shell_session_id) or 0),
                    }
                )
                archived = [
                    dict(item)
                    for item in list(self._shell_archived_jobs.get(shell_session_id) or [])
                    if isinstance(item, dict) and str(item.get("job_id") or "").strip() != job_id
                ]
                archived.append(dict(terminal_snapshot))
                archived.sort(
                    key=lambda item: str(item.get("updated_at") or item.get("completed_at") or item.get("created_at") or ""),
                    reverse=True,
                )
                self._shell_archived_jobs[shell_session_id] = archived[:_RECOVERY_TERMINAL_JOB_LIMIT]
                envelope = self._build_job_envelope_from_locked_state(job_id)
            else:
                envelope = {}
        self._persist_job_recovery_state(
            store=store,
            core_execution_session_id=core_execution_session_id,
            job_envelope=envelope,
            terminal_snapshot=terminal_snapshot,
            mailbox_cursor_seq=max(
                int(self._shell_mailbox_cursors.get(shell_session_id) or 0),
                int(completion_message_seq or 0),
            ),
        )

        try:
            store.update_metadata(
                core_execution_session_id,
                {
                    "last_job_id": str(job_id or ""),
                    "last_pipeline_end_reason": str(pipeline_end_reason or ""),
                    "last_error_text": str(error_text or ""),
                },
            )
        except Exception:
            logger.debug("Failed to persist terminal core session metadata: %s", core_execution_session_id, exc_info=True)
        try:
            store.update_status(core_execution_session_id, AgentStatus.WAITING)
        except Exception:
            logger.debug("Failed to mark core job session waiting: %s", core_execution_session_id, exc_info=True)
        try:
            store.update_status(core_runtime_id, AgentStatus.WAITING)
        except Exception:
            logger.debug("Failed to mark core runtime waiting: %s", core_runtime_id, exc_info=True)
        try:
            store.publish_task_heartbeat(
                core_execution_session_id,
                task_id=str(job_id),
                scope="pipeline",
                status=str(status or "failed"),
                message=str(pipeline_end_reason or status or ""),
                stage="pipeline_end",
                ttl_seconds=90,
                details={
                    "job_id": str(job_id),
                    "core_runtime_id": str(core_runtime_id or ""),
                    "pipeline_end_reason": str(pipeline_end_reason or ""),
                    "error_text": str(error_text or ""),
                },
            )
        except Exception:
            logger.debug("Failed to publish terminal core job heartbeat: %s", job_id, exc_info=True)

    def _mark_job_waiting_descendants(
        self,
        *,
        job_id: str,
        pipeline_end_reason: str,
        store: AgentSessionStore,
        core_runtime_id: str,
        core_execution_session_id: str,
    ) -> None:
        now = _utc_now_iso()
        shell_session_id = ""
        envelope: Dict[str, Any] = {}
        goal = ""
        pipeline_id = ""
        pending_descendant_count = 0
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = "waiting_descendants"
                job.updated_at = now
                job.completed_at = ""
                if pipeline_end_reason:
                    job.pipeline_end_reason = str(pipeline_end_reason)
                if not job.last_event_type:
                    job.last_event_type = "pipeline_end"
                if not job.last_event_at:
                    job.last_event_at = now
                shell_session_id = str(job.shell_session_id or "").strip()
                goal = str(job.goal or "")
                pipeline_id = str(job.pipeline_id or "")
                envelope = self._build_job_envelope_from_locked_state(job_id)
                pending_descendant_count = len(self._collect_job_pending_descendants_locked(job))
            self._job_tasks.pop(job_id, None)
        self._persist_job_recovery_state(
            store=store,
            core_execution_session_id=core_execution_session_id,
            job_envelope=envelope,
            mailbox_cursor_seq=int(self._shell_mailbox_cursors.get(shell_session_id) or 0),
        )
        if shell_session_id:
            self._send_shell_status_update(
                shell_session_id=shell_session_id,
                core_execution_session_id=core_execution_session_id,
                core_runtime_id=core_runtime_id,
                job_id=job_id,
                status="waiting_descendants",
                goal=goal,
                pipeline_id=pipeline_id,
                pending_descendant_count=pending_descendant_count,
            )
        try:
            store.update_metadata(
                core_execution_session_id,
                {
                    "last_job_id": str(job_id or ""),
                    "last_pipeline_end_reason": str(pipeline_end_reason or ""),
                    "last_error_text": "",
                    "active_job_status": "waiting_descendants",
                },
            )
        except Exception:
            logger.debug(
                "Failed to persist waiting-descendants core session metadata: %s",
                core_execution_session_id,
                exc_info=True,
            )
        try:
            store.update_status(core_execution_session_id, AgentStatus.WAITING)
        except Exception:
            logger.debug(
                "Failed to mark core job session waiting_descendants: %s",
                core_execution_session_id,
                exc_info=True,
            )
        try:
            store.update_status(core_runtime_id, AgentStatus.WAITING)
        except Exception:
            logger.debug(
                "Failed to mark core runtime waiting_descendants: %s",
                core_runtime_id,
                exc_info=True,
            )
        try:
            store.publish_task_heartbeat(
                core_execution_session_id,
                task_id=str(job_id),
                scope="pipeline",
                status="waiting_descendants",
                message=str(pipeline_end_reason or "waiting_descendants"),
                stage="pipeline_waiting_descendants",
                ttl_seconds=90,
                details={
                    "job_id": str(job_id),
                    "core_runtime_id": str(core_runtime_id or ""),
                    "pipeline_end_reason": str(pipeline_end_reason or ""),
                },
            )
        except Exception:
            logger.debug("Failed to publish waiting_descendants heartbeat: %s", job_id, exc_info=True)

    def _try_reconcile_waiting_descendants(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(str(job_id or "").strip())
            if job is None or str(job.status or "").strip() != "waiting_descendants":
                return False
            reconcile_payload = self._collect_job_reconcile_payload_locked(job)
            completion_state = (
                reconcile_payload.get("completion_state")
                if isinstance(reconcile_payload.get("completion_state"), dict)
                else {}
            )
            if list(completion_state.get("pending_descendants") or []):
                return False
            spec = self._job_specs.get(job.job_id)
            if spec is None or spec.store is None:
                return False
            prior_receipt = dict(job.last_execution_receipt or {}) if isinstance(job.last_execution_receipt, dict) else {}
            scheduler_summary = {}
            prior_agent_state = prior_receipt.get("agent_state") if isinstance(prior_receipt.get("agent_state"), dict) else {}
            if isinstance(prior_agent_state.get("scheduler"), dict):
                scheduler_summary = dict(prior_agent_state.get("scheduler") or {})
            receipt_event = build_core_execution_receipt(
                pipeline_id=str(job.pipeline_id or ""),
                decomposition={
                    "original_goal": str(job.goal or ""),
                    "goal_id": str(job.pipeline_id or job.job_id or ""),
                },
                expert_results=list(reconcile_payload.get("expert_results") or []),
                reports=list(reconcile_payload.get("reports") or []),
                review_results=list(reconcile_payload.get("review_results") or []),
                task_completed=bool(completion_state.get("task_completed")),
                stop_reason=str(completion_state.get("stop_reason") or ""),
                scheduler_metrics=scheduler_summary or None,
                heartbeat_summary=dict(reconcile_payload.get("heartbeat_summary") or {}),
                blocked_expert_reasons=list(completion_state.get("blocked_expert_reasons") or []),
            )
            receipt_state = receipt_event.get("agent_state") if isinstance(receipt_event.get("agent_state"), dict) else {}
            if isinstance(prior_agent_state.get("core_loop"), dict):
                receipt_state["core_loop"] = dict(prior_agent_state.get("core_loop") or {})
            for key in ("core_loop_tool_calls", "core_loop_tools_used"):
                if key in prior_agent_state and key not in receipt_state:
                    receipt_state[key] = prior_agent_state.get(key)
            receipt_event["agent_state"] = receipt_state
            store = spec.store
            core_runtime_id = str(job.core_runtime_id or DEFAULT_CORE_RUNTIME_ID)
            core_execution_session_id = str(job.core_execution_session_id or "")

        self._record_event(job_id, receipt_event)
        final_status = _derive_reconciled_job_status(
            task_completed=bool(completion_state.get("task_completed")),
            stop_reason=str(completion_state.get("stop_reason") or ""),
            experts_blocked=bool(completion_state.get("experts_blocked")),
        )
        self._mark_job_terminal(
            job_id=job_id,
            status=final_status,
            pipeline_end_reason=str(completion_state.get("stop_reason") or ""),
            error_text="",
            store=store,
            core_runtime_id=core_runtime_id,
            core_execution_session_id=core_execution_session_id,
        )
        return True

    async def _try_advance_waiting_descendants(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(str(job_id or "").strip())
            if job is None or str(job.status or "").strip() != "waiting_descendants":
                return False
            spec = self._job_specs.get(job.job_id)
            if spec is None or spec.store is None or spec.mailbox is None:
                return False
            pipeline_id = str(job.pipeline_id or "").strip()
            if not pipeline_id:
                return False
            store = spec.store
            mailbox = spec.mailbox
            core_execution_session_id = str(job.core_execution_session_id or "").strip()
            task_board_engine = spec.task_board_engine
            child_llm_call = spec.child_llm_call
            child_tool_executor = spec.child_tool_executor

        snapshot = self.get_job_snapshot(job_id, include_events=False)
        pending_count = max(0, int(snapshot.get("pending_descendant_count") or 0))
        if pending_count <= 0:
            return False

        async def _emit(event: Dict[str, Any]) -> None:
            self._record_event(job_id, dict(event))

        try:
            summary = await advance_core_waiting_descendants_once(
                store=store,
                mailbox=mailbox,
                core_execution_session_id=core_execution_session_id,
                pipeline_id=pipeline_id,
                child_llm_call=child_llm_call,
                child_tool_executor=child_tool_executor,
                child_max_rounds=max(1, int(spec.child_max_rounds or 0)),
                task_board_engine=task_board_engine,
                emit=_emit,
            )
        except Exception:
            logger.exception("Failed to actively advance waiting descendants: %s", job_id)
            return False

        progress_made = bool(summary.get("progress_made"))
        if progress_made:
            self._record_event(
                job_id,
                {
                    "type": "waiting_descendants_progress",
                    "pipeline_id": pipeline_id,
                    "core_execution_session_id": core_execution_session_id,
                    "summary": dict(summary),
                },
            )
        return progress_made

    def _reconcile_shell_waiting_jobs(self, shell_session_id: str) -> None:
        session_id = str(shell_session_id or "").strip()
        if not session_id:
            return
        with self._lock:
            job_ids = [
                str(job_id or "").strip()
                for job_id in list(self._shell_jobs.get(session_id) or [])
                if str(job_id or "").strip()
            ]
        for job_id in job_ids:
            self._try_reconcile_waiting_descendants(job_id)

    def get_job_snapshot(self, job_id: str, *, include_events: bool = True) -> Dict[str, Any]:
        self._try_reconcile_waiting_descendants(job_id)
        with self._lock:
            return self._build_job_snapshot_locked(job_id, include_events=include_events)

    def list_shell_jobs(self, shell_session_id: str, *, limit: int = 10) -> List[Dict[str, Any]]:
        session_id = str(shell_session_id or "").strip()
        self._recover_shell_state(session_id)
        self._reconcile_shell_waiting_jobs(session_id)
        with self._lock:
            self._hydrate_shell_queue_from_mailbox_locked(session_id)
            job_ids = list(self._shell_jobs.get(session_id, []))
            jobs = [self._build_job_snapshot_locked(job_id, include_events=False) for job_id in job_ids if job_id in self._jobs]
            archived = [dict(item) for item in list(self._shell_archived_jobs.get(session_id) or []) if isinstance(item, dict)]
        merged: Dict[str, Dict[str, Any]] = {}
        for item in archived + jobs:
            job_id = str(item.get("job_id") or "").strip()
            if job_id:
                merged[job_id] = dict(item)
        ordered = list(merged.values())
        ordered.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return ordered[: max(1, int(limit))]

    def get_shell_snapshot(self, shell_session_id: str, *, limit: int = 10) -> Dict[str, Any]:
        session_id = str(shell_session_id or "").strip()
        self._recover_shell_state(session_id)
        self._reconcile_shell_waiting_jobs(session_id)
        with self._lock:
            self._hydrate_shell_queue_from_mailbox_locked(session_id)
            ordered_job_ids = list(self._shell_jobs.get(session_id, []))
            ordered_jobs = [
                self._build_job_snapshot_locked(job_id, include_events=False)
                for job_id in ordered_job_ids
                if job_id in self._jobs
            ]
            shell_runtime = self._build_shell_runtime_snapshot_locked(session_id)
            archived_jobs = [dict(item) for item in list(self._shell_archived_jobs.get(session_id) or []) if isinstance(item, dict)]
        jobs = list(ordered_jobs)
        merged_jobs: Dict[str, Dict[str, Any]] = {}
        for item in archived_jobs + jobs:
            job_id = str(item.get("job_id") or "").strip()
            if job_id:
                merged_jobs[job_id] = dict(item)
        jobs = list(merged_jobs.values())
        jobs.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        active_jobs_in_order = [
            job for job in ordered_jobs if str(job.get("status") or "") in _VISIBLE_ACTIVE_JOB_STATUSES
        ]
        running_jobs = [job for job in active_jobs_in_order if str(job.get("status") or "") == "running"]
        active_job = running_jobs[0] if running_jobs else (active_jobs_in_order[0] if active_jobs_in_order else {})
        latest_job = jobs[0] if jobs else {}
        return {
            "shell_session_id": session_id,
            "core_runtime_id": str(
                active_job.get("core_runtime_id")
                or latest_job.get("core_runtime_id")
                or DEFAULT_CORE_RUNTIME_ID
            ),
            "active_job_id": str(active_job.get("job_id") or ""),
            "active_job_ids": [
                str(job.get("job_id") or "")
                for job in active_jobs_in_order
                if str(job.get("job_id") or "")
            ],
            "latest_job_id": str(latest_job.get("job_id") or ""),
            "latest_job": dict(latest_job or {}),
            "active_job": dict(active_job or {}),
            "jobs": jobs,
            "worker_status": str(shell_runtime.get("worker_status") or "idle"),
            "current_job_id": str(shell_runtime.get("current_job_id") or ""),
            "queued_job_ids": list(shell_runtime.get("queued_job_ids") or []),
            "queue_depth": int(shell_runtime.get("queue_depth") or 0),
            "pipeline_depth": int(shell_runtime.get("pipeline_depth") or len(active_jobs_in_order)),
            "mailbox_cursor_seq": int(shell_runtime.get("mailbox_cursor_seq") or 0),
            "recovery_restart_total": int(shell_runtime.get("recovery_restart_total") or 0),
            "inbox_dedup_skipped_count": int(shell_runtime.get("inbox_dedup_skipped_count") or 0),
            "last_dedup_message_seq": int(shell_runtime.get("last_dedup_message_seq") or 0),
            "latest_handoff_message_seq": int(latest_job.get("handoff_message_seq") or 0),
            "latest_completion_message_seq": int(latest_job.get("completion_message_seq") or 0),
        }

    async def shutdown(self) -> None:
        with self._lock:
            tasks = (
                list(self._job_tasks.values())
                + list(self._heartbeat_tasks.values())
                + list(self._shell_workers.values())
                + ([self._runtime_monitor_task] if self._runtime_monitor_task is not None else [])
            )
            self._job_tasks.clear()
            self._heartbeat_tasks.clear()
            self._job_specs.clear()
            self._shell_workers.clear()
            self._shell_current_jobs.clear()
            self._shell_queues.clear()
            self._shell_archived_jobs.clear()
            self._shell_mailboxes.clear()
            self._shell_core_sessions.clear()
            self._shell_mailbox_cursors.clear()
            self._shell_recovery_restart_totals.clear()
            self._shell_inbox_dedup_skipped_counts.clear()
            self._shell_last_dedup_message_seq.clear()
            self._runtime_monitor_task = None
            self._known_core_runtime_ids = {DEFAULT_CORE_RUNTIME_ID}
        unique_tasks = list({id(task): task for task in tasks}.values())
        for task in unique_tasks:
            if not task.done():
                task.cancel()
        if unique_tasks:
            await asyncio.gather(*unique_tasks, return_exceptions=True)
