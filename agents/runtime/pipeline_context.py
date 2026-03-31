"""Pipeline context store — pull-model context sharing between pipeline stages.

Shell writes structured context entries (tool results, system state snapshots)
into this store after dispatch. Downstream agents (Expert, Dev) pull what they
need by shell_session_id. This avoids prompt injection and keeps context
transfer structured and auditable.

Architecture:
    api_server.py  ──write──►  pipeline_context (SQLite)  ◄──read──  pipeline.py
    (Shell layer)                                                    (Dev/Expert)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = "scratch/runtime/agent_sessions.db"


class PipelineContextStore:
    """SQLite-backed store for pipeline context entries.

    Shares the same DB file as AgentSessionStore but uses its own table.
    Thread-safe via lock; WAL mode for concurrent reads.
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._ensure_table()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_table(self) -> None:
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS pipeline_context (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        source_role TEXT NOT NULL DEFAULT 'shell',
                        entry_type TEXT NOT NULL DEFAULT 'tool_result',
                        tool_name TEXT NOT NULL DEFAULT '',
                        content TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_pipeline_ctx_session
                    ON pipeline_context (session_id)
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def write_batch(
        self,
        *,
        session_id: str,
        entries: List[Dict[str, Any]],
    ) -> int:
        """Write multiple context entries at once. Returns count written."""
        if not entries:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for entry in entries:
            content = entry.get("content", {})
            serialized = (
                json.dumps(content, ensure_ascii=False, default=str)
                if not isinstance(content, str)
                else content
            )
            rows.append((
                session_id,
                str(entry.get("source_role", "shell")),
                str(entry.get("entry_type", "tool_result")),
                str(entry.get("tool_name", "")),
                serialized,
                now,
            ))
        with self._lock:
            conn = self._get_conn()
            try:
                conn.executemany(
                    "INSERT INTO pipeline_context"
                    " (session_id, source_role, entry_type, tool_name, content, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    rows,
                )
                conn.commit()
                return len(rows)
            finally:
                conn.close()

    def read(
        self,
        session_id: str,
        *,
        entry_type: Optional[str] = None,
        source_role: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Read context entries for a session. Returns list of dicts."""
        query = (
            "SELECT source_role, entry_type, tool_name, content, created_at"
            " FROM pipeline_context WHERE session_id = ?"
        )
        params: list = [session_id]
        if entry_type:
            query += " AND entry_type = ?"
            params.append(entry_type)
        if source_role:
            query += " AND source_role = ?"
            params.append(source_role)
        query += " ORDER BY id ASC LIMIT ?"
        params.append(limit)

        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute(query, params).fetchall()
                results = []
                for row in rows:
                    content = row[3]
                    try:
                        content = json.loads(content)
                    except (json.JSONDecodeError, TypeError):
                        pass
                    results.append({
                        "source_role": row[0],
                        "entry_type": row[1],
                        "tool_name": row[2],
                        "content": content,
                        "created_at": row[4],
                    })
                return results
            finally:
                conn.close()

    def clear(self, session_id: str) -> int:
        """Remove all context entries for a session. Returns count deleted."""
        with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    "DELETE FROM pipeline_context WHERE session_id = ?",
                    (session_id,),
                )
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()


# ── Singleton ──────────────────────────────────────────────────────

_instance: Optional[PipelineContextStore] = None
_instance_lock = threading.Lock()


def get_pipeline_context_store(db_path: str = _DEFAULT_DB_PATH) -> PipelineContextStore:
    """Get or create the singleton PipelineContextStore."""
    global _instance
    if _instance is not None:
        return _instance
    with _instance_lock:
        if _instance is None:
            _instance = PipelineContextStore(db_path=db_path)
        return _instance
