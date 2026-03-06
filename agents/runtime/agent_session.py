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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from system.git_worktree_sandbox import cleanup_git_worktree_sandbox

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            "status": self.status.value,
            "interrupt_requested": self.interrupt_requested,
            "task_description": self.task_description,
            "tool_profile": self.tool_profile,
            "tool_subset": list(self.tool_subset),
            "prompt_block_count": len(self.prompt_blocks),
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

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._lock = threading.Lock()
        self._sessions: Dict[str, AgentSession] = {}

        # SQLite persistence
        resolved = str(db_path) if db_path else ":memory:"
        if db_path and db_path != ":memory:":
            Path(resolved).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(resolved, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA_SQL)
        self._ensure_schema_compat()
        self._db.commit()

        # Load existing sessions from disk
        self._load_from_db()

    # ── public API ──────────────────────────────────────────────

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

    def list_children(self, parent_id: str) -> List[AgentSession]:
        """List all non-destroyed children of a parent."""
        with self._lock:
            return [
                s for s in self._sessions.values()
                if s.parent_id == parent_id and s.status != AgentStatus.DESTROYED
            ]

    def destroy(self, session_id: str, reason: str = "") -> None:
        """Mark session as destroyed and clean up."""
        cleanup_context: Dict[str, Any] = {}
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return  # idempotent
            session.status = AgentStatus.DESTROYED
            session.updated_at = _utc_now_iso()
            if reason:
                session.metadata["destroy_reason"] = reason
            cleanup_context = {
                "workspace_root": str(session.metadata.get("workspace_root") or "").strip(),
                "workspace_origin_root": str(session.metadata.get("workspace_origin_root") or "").strip(),
                "workspace_owner_session_id": str(session.metadata.get("workspace_owner_session_id") or "").strip(),
                "workspace_cleanup_on_destroy": bool(session.metadata.get("workspace_cleanup_on_destroy", False)),
            }
            self._persist(session)
            # Keep in memory for audit trail, but get() will return None
        logger.info("Destroyed session %s (reason=%s)", session_id, reason or "n/a")

        should_cleanup_workspace = bool(
            cleanup_context.get("workspace_cleanup_on_destroy")
            and cleanup_context.get("workspace_owner_session_id") == session_id
            and cleanup_context.get("workspace_root")
        )
        if not should_cleanup_workspace:
            return

        success, error = cleanup_git_worktree_sandbox(
            worktree_root=str(cleanup_context.get("workspace_root") or ""),
            repo_root=str(cleanup_context.get("workspace_origin_root") or "") or None,
        )
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return
            session.metadata["workspace_cleanup_success"] = bool(success)
            if error:
                session.metadata["workspace_cleanup_error"] = error
            session.updated_at = _utc_now_iso()
            self._persist(session)
        if not success:
            logger.warning("Failed to clean git worktree sandbox for %s: %s", session_id, error)

    def close(self) -> None:
        """Close the SQLite connection."""
        self._db.close()

    # ── private ─────────────────────────────────────────────────

    def _persist(self, session: AgentSession) -> None:
        """Upsert session into SQLite."""
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
        """Apply lightweight additive migrations for persisted runtime DBs."""
        columns = {
            str(row[1])
            for row in self._db.execute("PRAGMA table_info(agent_sessions)").fetchall()
            if isinstance(row, tuple) and len(row) > 1
        }
        if "tool_profile" not in columns:
            self._db.execute("ALTER TABLE agent_sessions ADD COLUMN tool_profile TEXT NOT NULL DEFAULT ''")
            self._db.commit()

    def _load_from_db(self) -> None:
        """Load all non-destroyed sessions from SQLite on startup."""
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


__all__ = ["AgentSession", "AgentSessionStore", "AgentStatus"]
