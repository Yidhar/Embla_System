"""Agent session lifecycle: data structures + thread-safe store with SQLite persistence.

Design philosophy: framework is a pipe, not a judge.
No hard limits on tokens, time, or tool calls. The parent agent decides everything.
"""

from __future__ import annotations

import enum
import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.event_bus import EventStore
from system.boxlite.manager import teardown_box_session
from system.git_worktree_sandbox import cleanup_git_worktree_sandbox

logger = logging.getLogger(__name__)

_HEARTBEAT_LEVEL_ORDER = {
    "fresh": 0,
    "warning": 1,
    "critical": 2,
    "blocked": 3,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _parse_iso(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        return _utc_now()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _resolve_now(value: Any = None) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if value is None:
        return _utc_now()
    return _parse_iso(value)


def _add_seconds_iso(base: Any, seconds: int) -> str:
    return (_parse_iso(base) + timedelta(seconds=max(0, int(seconds or 0)))).isoformat()


def _coerce_progress(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("progress must be numeric.")
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("progress must be numeric.") from exc


def _derive_heartbeat_state(*, generated_at: Any, ttl_seconds: Any, now: Any = None) -> Dict[str, Any]:
    generated_dt = _parse_iso(generated_at)
    now_dt = _resolve_now(now)
    ttl = max(1, int(ttl_seconds or 90))
    age_seconds = max(0.0, (now_dt - generated_dt).total_seconds())
    critical_after = max(ttl * 2, ttl + 30)
    blocked_after = critical_after + 60
    if age_seconds > blocked_after:
        stale_level = "blocked"
        escalation_state = "blocked"
    elif age_seconds > critical_after:
        stale_level = "critical"
        escalation_state = "critical"
    elif age_seconds > ttl:
        stale_level = "warning"
        escalation_state = "warning"
    else:
        stale_level = "fresh"
        escalation_state = "active"
    return {
        "stale_level": stale_level,
        "escalation_state": escalation_state,
        "seconds_since_heartbeat": age_seconds,
        "warning_after_seconds": ttl,
        "critical_after_seconds": critical_after,
        "blocked_after_seconds": blocked_after,
        "stale_seconds": max(0.0, age_seconds - ttl),
        "is_stale": stale_level != "fresh",
    }


def _coerce_details(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    raise ValueError("details must be an object.")


def _heartbeat_id(session_id: str, task_id: str, sequence: int) -> str:
    return f"{session_id}:{task_id}:{int(sequence or 0)}"


def _worst_heartbeat_level(levels: List[str]) -> str:
    normalized = [str(level or "fresh").strip().lower() for level in levels if str(level or "").strip()]
    if not normalized:
        return "none"
    return max(normalized, key=lambda item: _HEARTBEAT_LEVEL_ORDER.get(item, 0))


class AgentStatus(str, enum.Enum):
    """Lifecycle states for a child agent session."""

    RUNNING = "running"
    WAITING = "waiting"
    DESTROYED = "destroyed"


@dataclass
class AgentSession:
    """Full state of a child agent session.

    - session_id: unique identifier for this session
    - parent_id: session_id of the parent agent (empty string for root)
    - role: agent role (e.g. "expert", "dev", "review")
    - status: current lifecycle status
    - prompt_blocks: ordered list of prompt block paths
    - tool_profile: preset profile name used to derive tool_subset
    - tool_subset: list of tool names this agent is allowed to use
    - task_description: the task assigned to this agent
    - messages: serialized LLM conversation history (list of dicts)
    - metadata: arbitrary key-value store (budget info, progress, etc.)
    - interrupt_requested: set by parent via terminate; child checks each loop iteration
    """

    session_id: str = ""
    parent_id: str = ""
    role: str = ""
    status: AgentStatus = AgentStatus.RUNNING
    prompt_blocks: List[str] = field(default_factory=list)
    tool_profile: str = ""
    tool_subset: List[str] = field(default_factory=list)
    task_description: str = ""
    messages: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    interrupt_requested: bool = False
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.session_id:
            self.session_id = f"agent-{uuid.uuid4().hex[:12]}"
        now = _utc_now_iso()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    def to_status_summary(self) -> Dict[str, Any]:
        """Lightweight status snapshot for poll_child_status (facts only, no judgment)."""
        return {
            "agent_id": self.session_id,
            "role": self.role,
            "agent_type": str(self.metadata.get("agent_type") or ""),
            "status": self.status.value,
            "interrupt_requested": self.interrupt_requested,
            "task_description": self.task_description,
            "tool_profile": self.tool_profile,
            "tool_subset": list(self.tool_subset),
            "prompt_block_count": len(self.prompt_blocks),
            "prompt_blocks": list(self.prompt_blocks),
            "message_count": len(self.messages),
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_sessions (
    session_id TEXT PRIMARY KEY,
    parent_id TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'running',
    prompt_blocks TEXT NOT NULL DEFAULT '[]',
    tool_profile TEXT NOT NULL DEFAULT '',
    tool_subset TEXT NOT NULL DEFAULT '[]',
    task_description TEXT NOT NULL DEFAULT '',
    messages TEXT NOT NULL DEFAULT '[]',
    metadata TEXT NOT NULL DEFAULT '{}',
    interrupt_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_parent ON agent_sessions(parent_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON agent_sessions(status);
CREATE TABLE IF NOT EXISTS task_heartbeat_projection (
    session_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    parent_id TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    progress REAL,
    stage TEXT NOT NULL DEFAULT '',
    ttl_seconds INTEGER NOT NULL DEFAULT 90,
    sequence INTEGER NOT NULL DEFAULT 0,
    generated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    stale_level TEXT NOT NULL DEFAULT 'fresh',
    escalation_state TEXT NOT NULL DEFAULT 'active',
    last_transition_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (session_id, task_id)
);
CREATE INDEX IF NOT EXISTS idx_task_heartbeat_parent ON task_heartbeat_projection(parent_id);
CREATE INDEX IF NOT EXISTS idx_task_heartbeat_role ON task_heartbeat_projection(role);
CREATE INDEX IF NOT EXISTS idx_task_heartbeat_generated ON task_heartbeat_projection(generated_at);
"""


class AgentSessionStore:
    """Thread-safe in-memory store with SQLite persistence.

    Usage:
        store = AgentSessionStore(db_path="scratch/runtime/agent_sessions.db")
        session = store.create(role="dev", parent_id="agent-abc", task_description="...")
        store.update_status(session.session_id, AgentStatus.WAITING)
        children = store.list_children("agent-abc")
        store.destroy(session.session_id)
    """

    def __init__(self, db_path: str | Path | None = None, *, event_store: Optional[EventStore] = None) -> None:
        self._lock = threading.Lock()
        self._sessions: Dict[str, AgentSession] = {}
        self._event_store = event_store

        resolved = str(db_path) if db_path else ":memory:"
        if db_path and db_path != ":memory:":
            Path(resolved).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(resolved, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA_SQL)
        self._ensure_schema_compat()
        self._db.commit()

        self._load_from_db()

    def create(
        self,
        *,
        role: str,
        parent_id: str = "",
        task_description: str = "",
        prompt_blocks: Optional[List[str]] = None,
        tool_profile: str = "",
        tool_subset: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        session_id: str = "",
    ) -> AgentSession:
        """Create and persist a new agent session."""
        session = AgentSession(
            session_id=session_id or "",
            parent_id=parent_id,
            role=role,
            status=AgentStatus.RUNNING,
            prompt_blocks=list(prompt_blocks or []),
            tool_profile=str(tool_profile or "").strip(),
            tool_subset=list(tool_subset or []),
            task_description=task_description,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            if session.session_id in self._sessions:
                raise ValueError(f"Session {session.session_id} already exists")
            self._sessions[session.session_id] = session
            self._persist(session)
        logger.info("Created agent session %s (role=%s, parent=%s)", session.session_id, role, parent_id)
        return session

    def get(self, session_id: str) -> Optional[AgentSession]:
        """Get a session by ID. Returns None if not found or destroyed."""
        with self._lock:
            s = self._sessions.get(session_id)
            if s and s.status == AgentStatus.DESTROYED:
                return None
            return s

    def update_status(self, session_id: str, new_status: AgentStatus) -> AgentSession:
        """Transition session to a new status."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise KeyError(f"Session {session_id} not found")
            if session.status == AgentStatus.DESTROYED:
                raise ValueError(f"Cannot update destroyed session {session_id}")
            old = session.status
            session.status = new_status
            session.updated_at = _utc_now_iso()
            if new_status == AgentStatus.RUNNING:
                session.interrupt_requested = False
            self._persist(session)
        logger.info("Session %s: %s → %s", session_id, old.value, new_status.value)
        return session

    def set_interrupt(self, session_id: str) -> None:
        """Request child to check interrupt flag at next loop iteration."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise KeyError(f"Session {session_id} not found")
            session.interrupt_requested = True
            session.updated_at = _utc_now_iso()
            self._persist(session)
        logger.info("Interrupt requested for session %s", session_id)

    def save_messages(self, session_id: str, messages: List[Dict[str, Any]]) -> None:
        """Persist LLM conversation history for pause/resume."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise KeyError(f"Session {session_id} not found")
            session.messages = list(messages)
            session.updated_at = _utc_now_iso()
            self._persist(session)

    def update_metadata(self, session_id: str, updates: Dict[str, Any]) -> None:
        """Merge key-value pairs into session metadata."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise KeyError(f"Session {session_id} not found")
            session.metadata.update(updates)
            session.updated_at = _utc_now_iso()
            self._persist(session)

    def publish_task_heartbeat(
        self,
        session_id: str,
        *,
        task_id: str,
        scope: str = "task",
        status: str = "running",
        message: str = "",
        progress: Any = None,
        stage: str = "",
        ttl_seconds: Any = 90,
        details: Any = None,
        generated_at: Any = None,
    ) -> Dict[str, Any]:
        task_id_text = str(task_id or "").strip()
        if not task_id_text:
            raise ValueError("task_id is required")
        progress_value = _coerce_progress(progress)
        details_dict = _coerce_details(details)
        generated_at_iso = _resolve_now(generated_at).isoformat() if generated_at is not None else _utc_now_iso()
        ttl_value = max(1, int(ttl_seconds or 90))
        expires_at = _add_seconds_iso(generated_at_iso, ttl_value)
        pending_events: List[Dict[str, Any]] = []
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise KeyError(f"Session {session_id} not found")
            previous = self._db.execute(
                "SELECT session_id, task_id, parent_id, role, scope, status, message, progress, stage, ttl_seconds, sequence, generated_at, expires_at, details_json, stale_level, escalation_state, last_transition_at "
                "FROM task_heartbeat_projection WHERE session_id = ? AND task_id = ?",
                (session_id, task_id_text),
            ).fetchone()
            previous_level = None
            if previous:
                previous_state = _derive_heartbeat_state(
                    generated_at=previous[11],
                    ttl_seconds=previous[9],
                    now=generated_at_iso,
                )
                previous_level = str(previous_state.get("stale_level") or "fresh")
            sequence = int(previous[10] or 0) + 1 if previous else 1
            current_state = _derive_heartbeat_state(generated_at=generated_at_iso, ttl_seconds=ttl_value, now=generated_at_iso)
            self._db.execute(
                """INSERT OR REPLACE INTO task_heartbeat_projection
                   (session_id, task_id, parent_id, role, scope, status, message, progress, stage,
                    ttl_seconds, sequence, generated_at, expires_at, details_json, stale_level,
                    escalation_state, last_transition_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    task_id_text,
                    session.parent_id,
                    session.role,
                    str(scope or "task").strip() or "task",
                    str(status or "running").strip() or "running",
                    str(message or ""),
                    progress_value,
                    str(stage or "").strip(),
                    ttl_value,
                    sequence,
                    generated_at_iso,
                    expires_at,
                    json.dumps(details_dict, ensure_ascii=False),
                    str(current_state.get("stale_level") or "fresh"),
                    str(current_state.get("escalation_state") or "active"),
                    generated_at_iso,
                ),
            )
            self._db.commit()
            if previous_level in {"warning", "critical", "blocked"}:
                pending_events.append(
                    {
                        "event_type": "TaskHeartbeatRecovered",
                        "severity": "info",
                        "payload": {
                            "session_id": session_id,
                            "parent_id": session.parent_id,
                            "role": session.role,
                            "task_id": task_id_text,
                            "sequence": sequence,
                            "recovered_from": previous_level,
                            "generated_at": generated_at_iso,
                            "ttl_seconds": ttl_value,
                        },
                    }
                )
            pending_events.append(
                {
                    "event_type": "TaskHeartbeatPublished",
                    "severity": "info",
                    "payload": {
                        "session_id": session_id,
                        "parent_id": session.parent_id,
                        "role": session.role,
                        "task_id": task_id_text,
                        "scope": str(scope or "task").strip() or "task",
                        "status": str(status or "running").strip() or "running",
                        "message": str(message or ""),
                        "progress": progress_value,
                        "stage": str(stage or "").strip(),
                        "ttl_seconds": ttl_value,
                        "sequence": sequence,
                        "generated_at": generated_at_iso,
                        "expires_at": expires_at,
                        "stale_level": str(current_state.get("stale_level") or "fresh"),
                        "escalation_state": str(current_state.get("escalation_state") or "active"),
                        "details": details_dict,
                    },
                }
            )
        self._emit_events(pending_events)
        return self._heartbeat_record(
            session_id=session_id,
            task_id=task_id_text,
            parent_id=str(session.parent_id or ""),
            role=str(session.role or ""),
            scope=str(scope or "task").strip() or "task",
            status=str(status or "running").strip() or "running",
            message=str(message or ""),
            progress=progress_value,
            stage=str(stage or "").strip(),
            ttl_seconds=ttl_value,
            sequence=sequence,
            generated_at=generated_at_iso,
            expires_at=expires_at,
            details=details_dict,
            now=generated_at_iso,
        )

    def list_task_heartbeats(self, session_id: str, *, now: Any = None) -> List[Dict[str, Any]]:
        now_dt = _resolve_now(now)
        now_iso = now_dt.isoformat()
        pending_events: List[Dict[str, Any]] = []
        with self._lock:
            rows = self._db.execute(
                "SELECT session_id, task_id, parent_id, role, scope, status, message, progress, stage, ttl_seconds, sequence, generated_at, expires_at, details_json, stale_level, escalation_state, last_transition_at "
                "FROM task_heartbeat_projection WHERE session_id = ? ORDER BY generated_at DESC, task_id ASC",
                (session_id,),
            ).fetchall()
            heartbeats: List[Dict[str, Any]] = []
            changed = False
            for row in rows:
                current_state = _derive_heartbeat_state(generated_at=row[11], ttl_seconds=row[9], now=now_dt)
                current_level = str(current_state.get("stale_level") or "fresh")
                current_escalation = str(current_state.get("escalation_state") or "active")
                stored_level = str(row[14] or "fresh")
                stored_escalation = str(row[15] or "active")
                if current_level != stored_level or current_escalation != stored_escalation:
                    changed = True
                    self._db.execute(
                        "UPDATE task_heartbeat_projection SET stale_level = ?, escalation_state = ?, last_transition_at = ? WHERE session_id = ? AND task_id = ?",
                        (current_level, current_escalation, now_iso, row[0], row[1]),
                    )
                    event_type = self._transition_event_type(current_level)
                    if event_type:
                        pending_events.append(
                            {
                                "event_type": event_type,
                                "severity": self._transition_severity(current_level),
                                "payload": {
                                    "session_id": row[0],
                                    "parent_id": row[2],
                                    "role": row[3],
                                    "task_id": row[1],
                                    "sequence": int(row[10] or 0),
                                    "generated_at": row[11],
                                    "ttl_seconds": int(row[9] or 90),
                                    "stale_level": current_level,
                                    "escalation_state": current_escalation,
                                    "seconds_since_heartbeat": current_state.get("seconds_since_heartbeat"),
                                },
                            }
                        )
                heartbeats.append(
                    self._heartbeat_record(
                        session_id=row[0],
                        task_id=row[1],
                        parent_id=row[2],
                        role=row[3],
                        scope=row[4],
                        status=row[5],
                        message=row[6],
                        progress=row[7],
                        stage=row[8],
                        ttl_seconds=row[9],
                        sequence=row[10],
                        generated_at=row[11],
                        expires_at=row[12],
                        details=self._decode_json_object(row[13]),
                        now=now_dt,
                    )
                )
            if changed:
                self._db.commit()
        self._emit_events(pending_events)
        return heartbeats

    def get_session_heartbeat_snapshot(self, session_id: str, *, now: Any = None) -> Dict[str, Any]:
        session = self.get(session_id)
        heartbeats = self.list_task_heartbeats(session_id, now=now)
        return {
            "session_id": session_id,
            "parent_id": str(session.parent_id or "") if session else "",
            "role": str(session.role or "") if session else "",
            "summary": self._build_heartbeat_summary(
                heartbeats,
                root_session_id=session_id,
                session_count=1 if session is not None else 0,
                sessions_with_heartbeats=1 if heartbeats else 0,
            ),
            "heartbeats": heartbeats,
        }

    def list_descendants(self, parent_id: str) -> List[AgentSession]:
        with self._lock:
            session_map = {
                session_id: session
                for session_id, session in self._sessions.items()
                if session.status != AgentStatus.DESTROYED
            }
        descendants: List[AgentSession] = []
        queue = [str(parent_id or "")]
        while queue:
            current_parent = queue.pop(0)
            children = [session for session in session_map.values() if session.parent_id == current_parent]
            for child in children:
                descendants.append(child)
                queue.append(child.session_id)
        return descendants

    def get_descendant_heartbeat_snapshot(self, root_session_id: str, *, now: Any = None) -> Dict[str, Any]:
        descendants = self.list_descendants(root_session_id)
        heartbeats: List[Dict[str, Any]] = []
        session_summaries: List[Dict[str, Any]] = []
        for session in descendants:
            snapshot = self.get_session_heartbeat_snapshot(session.session_id, now=now)
            summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
            if snapshot.get("heartbeats"):
                heartbeats.extend(list(snapshot.get("heartbeats") or []))
                session_summaries.append(
                    {
                        "session_id": session.session_id,
                        "parent_id": session.parent_id,
                        "role": session.role,
                        "status": session.status.value,
                        "heartbeat_summary": dict(summary),
                    }
                )
        return {
            "root_session_id": str(root_session_id or ""),
            "summary": self._build_heartbeat_summary(
                heartbeats,
                root_session_id=root_session_id,
                session_count=len(descendants),
                sessions_with_heartbeats=len(session_summaries),
            ),
            "sessions": session_summaries,
            "heartbeats": heartbeats,
        }

    def get_runtime_heartbeat_snapshot(self, *, now: Any = None) -> Dict[str, Any]:
        with self._lock:
            sessions = [
                session
                for session in self._sessions.values()
                if session.status != AgentStatus.DESTROYED
            ]

        heartbeats: List[Dict[str, Any]] = []
        session_summaries: List[Dict[str, Any]] = []
        for session in sessions:
            snapshot = self.get_session_heartbeat_snapshot(session.session_id, now=now)
            summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
            session_heartbeats = list(snapshot.get("heartbeats") or [])
            if not session_heartbeats:
                continue
            heartbeats.extend(session_heartbeats)
            session_summaries.append(
                {
                    "session_id": session.session_id,
                    "parent_id": session.parent_id,
                    "role": session.role,
                    "status": session.status.value,
                    "heartbeat_summary": dict(summary),
                }
            )

        session_summaries.sort(
            key=lambda item: (
                str((item.get("heartbeat_summary") or {}).get("max_stale_level") or "fresh"),
                str((item.get("heartbeat_summary") or {}).get("latest_generated_at") or ""),
                str(item.get("session_id") or ""),
            ),
            reverse=True,
        )
        heartbeats.sort(
            key=lambda item: (
                str(item.get("stale_level") or "fresh"),
                str(item.get("generated_at") or ""),
                str(item.get("session_id") or ""),
                str(item.get("task_id") or ""),
            ),
            reverse=True,
        )
        return {
            "root_session_id": "runtime",
            "summary": self._build_heartbeat_summary(
                heartbeats,
                root_session_id="runtime",
                session_count=len(sessions),
                sessions_with_heartbeats=len(session_summaries),
            ),
            "sessions": session_summaries,
            "heartbeats": heartbeats,
        }

    def list_children(self, parent_id: str) -> List[AgentSession]:
        """List all non-destroyed children of a parent."""
        with self._lock:
            return [
                s for s in self._sessions.values()
                if s.parent_id == parent_id and s.status != AgentStatus.DESTROYED
            ]

    def destroy(self, session_id: str, reason: str = "") -> Dict[str, Any]:
        """Mark session as destroyed and clean up, returning factual cleanup results."""
        cleanup_context: Dict[str, Any] = {}
        report: Dict[str, Any] = {
            "destroyed": False,
            "box_cleanup_attempted": False,
            "box_cleanup_success": True,
            "box_cleanup_error": "",
            "workspace_cleanup_attempted": False,
            "workspace_cleanup_success": True,
            "workspace_cleanup_error": "",
        }
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return report
            session.status = AgentStatus.DESTROYED
            session.updated_at = _utc_now_iso()
            if reason:
                session.metadata["destroy_reason"] = reason
            cleanup_context = {
                "execution_backend": str(session.metadata.get("execution_backend") or "").strip(),
                "box_id": str(session.metadata.get("box_id") or "").strip(),
                "box_name": str(session.metadata.get("box_name") or "").strip(),
                "workspace_root": str(session.metadata.get("workspace_root") or "").strip(),
                "workspace_origin_root": str(session.metadata.get("workspace_origin_root") or "").strip(),
                "workspace_owner_session_id": str(session.metadata.get("workspace_owner_session_id") or "").strip(),
                "workspace_cleanup_on_destroy": bool(session.metadata.get("workspace_cleanup_on_destroy", False)),
            }
            self._persist(session)
        report["destroyed"] = True
        logger.info("Destroyed session %s (reason=%s)", session_id, reason or "n/a")

        box_cleanup_success = True
        box_cleanup_error = ""
        if cleanup_context.get("execution_backend") == "boxlite" and (cleanup_context.get("box_id") or cleanup_context.get("box_name")):
            report["box_cleanup_attempted"] = True
            box_cleanup_success, box_cleanup_error = teardown_box_session(cleanup_context)
            with self._lock:
                session = self._sessions.get(session_id)
                if session is not None:
                    session.metadata["box_cleanup_success"] = bool(box_cleanup_success)
                    if box_cleanup_error:
                        session.metadata["box_cleanup_error"] = box_cleanup_error
                    session.updated_at = _utc_now_iso()
                    self._persist(session)
            report["box_cleanup_success"] = bool(box_cleanup_success)
            report["box_cleanup_error"] = str(box_cleanup_error or "")
            if not box_cleanup_success:
                logger.warning("Failed to clean box session for %s: %s", session_id, box_cleanup_error)

        should_cleanup_workspace = bool(
            cleanup_context.get("workspace_cleanup_on_destroy")
            and cleanup_context.get("workspace_owner_session_id") == session_id
            and cleanup_context.get("workspace_root")
        )
        if not should_cleanup_workspace:
            return report

        report["workspace_cleanup_attempted"] = True
        success, error = cleanup_git_worktree_sandbox(
            worktree_root=str(cleanup_context.get("workspace_root") or ""),
            repo_root=str(cleanup_context.get("workspace_origin_root") or "") or None,
        )
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return report
            session.metadata["workspace_cleanup_success"] = bool(success)
            if error:
                session.metadata["workspace_cleanup_error"] = error
            session.updated_at = _utc_now_iso()
            self._persist(session)
        report["workspace_cleanup_success"] = bool(success)
        report["workspace_cleanup_error"] = str(error or "")
        if not success:
            logger.warning("Failed to clean git worktree sandbox for %s: %s", session_id, error)
        return report

    def close(self) -> None:
        """Close the SQLite connection."""
        self._db.close()

    def _persist(self, session: AgentSession) -> None:
        self._db.execute(
            """INSERT OR REPLACE INTO agent_sessions
               (session_id, parent_id, role, status, prompt_blocks, tool_profile, tool_subset,
                task_description, messages, metadata, interrupt_requested,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session.session_id,
                session.parent_id,
                session.role,
                session.status.value,
                json.dumps(session.prompt_blocks, ensure_ascii=False),
                str(session.tool_profile or ""),
                json.dumps(session.tool_subset, ensure_ascii=False),
                session.task_description,
                json.dumps(session.messages, ensure_ascii=False),
                json.dumps(session.metadata, ensure_ascii=False),
                1 if session.interrupt_requested else 0,
                session.created_at,
                session.updated_at,
            ),
        )
        self._db.commit()

    def _ensure_schema_compat(self) -> None:
        columns = {
            str(row[1])
            for row in self._db.execute("PRAGMA table_info(agent_sessions)").fetchall()
            if isinstance(row, tuple) and len(row) > 1
        }
        if "tool_profile" not in columns:
            self._db.execute("ALTER TABLE agent_sessions ADD COLUMN tool_profile TEXT NOT NULL DEFAULT ''")
            self._db.commit()

    def _load_from_db(self) -> None:
        cursor = self._db.execute(
            "SELECT session_id, parent_id, role, status, prompt_blocks, tool_profile, tool_subset, "
            "task_description, messages, metadata, interrupt_requested, created_at, updated_at "
            "FROM agent_sessions WHERE status != ?",
            (AgentStatus.DESTROYED.value,),
        )
        for row in cursor.fetchall():
            session = AgentSession(
                session_id=row[0],
                parent_id=row[1],
                role=row[2],
                status=AgentStatus(row[3]),
                prompt_blocks=json.loads(row[4]),
                tool_profile=str(row[5] or ""),
                tool_subset=json.loads(row[6]),
                task_description=row[7],
                messages=json.loads(row[8]),
                metadata=json.loads(row[9]),
                interrupt_requested=bool(row[10]),
                created_at=row[11],
                updated_at=row[12],
            )
            self._sessions[session.session_id] = session
        logger.debug("Loaded %d agent sessions from DB", len(self._sessions))

    def _emit_events(self, events: List[Dict[str, Any]]) -> None:
        if not events or self._event_store is None:
            return
        for item in events:
            try:
                payload = dict(item.get("payload") or {})
                event_type = str(item.get("event_type") or "").strip()
                if not event_type:
                    continue
                self._event_store.emit(
                    event_type,
                    payload,
                    source="agents.runtime.agent_session",
                    severity=str(item.get("severity") or "info"),
                    idempotency_key=f"{event_type}:{payload.get('session_id')}:{payload.get('task_id')}:{payload.get('sequence')}:{payload.get('stale_level', '')}",
                )
            except Exception:
                logger.exception("Failed to emit heartbeat event %s", item)

    def _heartbeat_record(
        self,
        *,
        session_id: str,
        task_id: str,
        parent_id: str,
        role: str,
        scope: str,
        status: str,
        message: str,
        progress: Any,
        stage: str,
        ttl_seconds: Any,
        sequence: Any,
        generated_at: Any,
        expires_at: Any,
        details: Dict[str, Any],
        now: Any = None,
    ) -> Dict[str, Any]:
        heartbeat_state = _derive_heartbeat_state(generated_at=generated_at, ttl_seconds=ttl_seconds, now=now)
        ttl_value = max(1, int(ttl_seconds or 90))
        generated_at_text = _parse_iso(generated_at).isoformat()
        expires_at_text = _parse_iso(expires_at).isoformat() if str(expires_at or "").strip() else _add_seconds_iso(generated_at_text, ttl_value)
        return {
            "heartbeat_id": _heartbeat_id(session_id, task_id, int(sequence or 0)),
            "session_id": str(session_id or ""),
            "task_id": str(task_id or ""),
            "parent_id": str(parent_id or ""),
            "role": str(role or ""),
            "scope": str(scope or "task"),
            "status": str(status or "running"),
            "message": str(message or ""),
            "progress": None if progress is None else float(progress),
            "stage": str(stage or ""),
            "ttl_seconds": ttl_value,
            "sequence": int(sequence or 0),
            "generated_at": generated_at_text,
            "expires_at": expires_at_text,
            "details": dict(details or {}),
            **heartbeat_state,
        }

    def _build_heartbeat_summary(
        self,
        heartbeats: List[Dict[str, Any]],
        *,
        root_session_id: str,
        session_count: int,
        sessions_with_heartbeats: int,
    ) -> Dict[str, Any]:
        counts = {"fresh": 0, "warning": 0, "critical": 0, "blocked": 0}
        for heartbeat in heartbeats:
            level = str(heartbeat.get("stale_level") or "fresh").strip().lower()
            if level in counts:
                counts[level] += 1
        latest_generated_at = max((str(item.get("generated_at") or "") for item in heartbeats), default="")
        latest_expires_at = max((str(item.get("expires_at") or "") for item in heartbeats), default="")
        return {
            "root_session_id": str(root_session_id or ""),
            "session_count": max(0, int(session_count or 0)),
            "sessions_with_heartbeats": max(0, int(sessions_with_heartbeats or 0)),
            "task_count": len(heartbeats),
            "fresh_count": counts["fresh"],
            "warning_count": counts["warning"],
            "critical_count": counts["critical"],
            "blocked_count": counts["blocked"],
            "max_stale_level": _worst_heartbeat_level([str(item.get("stale_level") or "fresh") for item in heartbeats]),
            "latest_generated_at": latest_generated_at,
            "latest_expires_at": latest_expires_at,
            "has_stale": (counts["warning"] + counts["critical"] + counts["blocked"]) > 0,
            "has_blocked": counts["blocked"] > 0,
        }

    def _decode_json_object(self, value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if value in (None, ""):
            return {}
        try:
            decoded = json.loads(value)
        except Exception:
            return {}
        return dict(decoded) if isinstance(decoded, dict) else {}

    def _transition_event_type(self, stale_level: str) -> str:
        level = str(stale_level or "").strip().lower()
        if level == "warning":
            return "TaskHeartbeatStaleWarning"
        if level == "critical":
            return "TaskHeartbeatStaleCritical"
        if level == "blocked":
            return "TaskHeartbeatEscalatedBlocked"
        return ""

    def _transition_severity(self, stale_level: str) -> str:
        level = str(stale_level or "").strip().lower()
        if level == "warning":
            return "warning"
        if level == "critical":
            return "error"
        if level == "blocked":
            return "critical"
        return "info"


__all__ = ["AgentSession", "AgentSessionStore", "AgentStatus"]
