"""Agent-to-agent message delivery backed by SQLite.

Supports parent↔child and peer-to-peer (Expert-relayed) messaging.
Each agent has a logical inbox identified by its session_id.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MailboxMessage:
    """A single message in an agent's inbox."""

    seq: int
    from_id: str
    to_id: str
    content: str
    message_type: str = "info"  # info | query | report | system
    metadata: Dict[str, Any] | None = None
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_messages (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    content TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'info',
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_to_id ON agent_messages(to_id);
CREATE INDEX IF NOT EXISTS idx_messages_to_seq ON agent_messages(to_id, seq);
"""


class AgentMailbox:
    """SQLite-backed message delivery for agent communication.

    Usage:
        mailbox = AgentMailbox(db_path="scratch/runtime/agent_mailbox.db")
        seq = mailbox.send("agent-parent", "agent-child", "你可以开始了")
        messages = mailbox.read("agent-child")
        messages = mailbox.read("agent-child", since_seq=5)
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._lock = threading.Lock()
        resolved = str(db_path) if db_path else ":memory:"
        if db_path and str(db_path) != ":memory:":
            Path(resolved).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(resolved, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA_SQL)
        self._db.commit()

    def send(
        self,
        from_id: str,
        to_id: str,
        content: str,
        *,
        message_type: str = "info",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Send a message to an agent's inbox. Returns the message sequence number."""
        now = _utc_now_iso()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._lock:
            cursor = self._db.execute(
                "INSERT INTO agent_messages (from_id, to_id, content, message_type, metadata, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (from_id, to_id, content, message_type, meta_json, now),
            )
            self._db.commit()
            seq = cursor.lastrowid or 0
        logger.debug("Message %d: %s → %s (%s)", seq, from_id, to_id, message_type)
        return seq

    def read(
        self,
        agent_id: str,
        *,
        since_seq: int = 0,
        limit: int = 100,
        message_type: Optional[str] = None,
    ) -> List[MailboxMessage]:
        """Read messages from an agent's inbox.

        Args:
            agent_id: the recipient agent's session_id
            since_seq: only return messages with seq > since_seq
            limit: max messages to return
            message_type: optional filter by message type
        """
        with self._lock:
            if message_type:
                cursor = self._db.execute(
                    "SELECT seq, from_id, to_id, content, message_type, metadata, created_at "
                    "FROM agent_messages WHERE to_id = ? AND seq > ? AND message_type = ? "
                    "ORDER BY seq ASC LIMIT ?",
                    (agent_id, since_seq, message_type, limit),
                )
            else:
                cursor = self._db.execute(
                    "SELECT seq, from_id, to_id, content, message_type, metadata, created_at "
                    "FROM agent_messages WHERE to_id = ? AND seq > ? "
                    "ORDER BY seq ASC LIMIT ?",
                    (agent_id, since_seq, limit),
                )
            rows = cursor.fetchall()
        return [
            MailboxMessage(
                seq=r[0],
                from_id=r[1],
                to_id=r[2],
                content=r[3],
                message_type=r[4],
                metadata=json.loads(r[5]) if r[5] else None,
                created_at=r[6],
            )
            for r in rows
        ]

    def read_latest(self, agent_id: str) -> Optional[MailboxMessage]:
        """Read the most recent message in an agent's inbox."""
        msgs = self.read(agent_id, limit=1)
        # We need desc order for latest
        with self._lock:
            cursor = self._db.execute(
                "SELECT seq, from_id, to_id, content, message_type, metadata, created_at "
                "FROM agent_messages WHERE to_id = ? ORDER BY seq DESC LIMIT 1",
                (agent_id,),
            )
            row = cursor.fetchone()
        if not row:
            return None
        return MailboxMessage(
            seq=row[0],
            from_id=row[1],
            to_id=row[2],
            content=row[3],
            message_type=row[4],
            metadata=json.loads(row[5]) if row[5] else None,
            created_at=row[6],
        )

    def count_unread(self, agent_id: str, since_seq: int = 0) -> int:
        """Count unread messages (seq > since_seq)."""
        with self._lock:
            cursor = self._db.execute(
                "SELECT COUNT(*) FROM agent_messages WHERE to_id = ? AND seq > ?",
                (agent_id, since_seq),
            )
            row = cursor.fetchone()
        return row[0] if row else 0

    def purge_agent_messages(self, agent_ids: List[str]) -> int:
        """Delete messages sent from/to the given agent IDs. Returns deleted row count."""
        normalized_ids = sorted({str(item or "").strip() for item in list(agent_ids or []) if str(item or "").strip()})
        if not normalized_ids:
            return 0

        placeholders = ",".join(["?"] * len(normalized_ids))
        sql = (
            f"DELETE FROM agent_messages "
            f"WHERE from_id IN ({placeholders}) OR to_id IN ({placeholders})"
        )
        params = tuple(normalized_ids + normalized_ids)
        with self._lock:
            before = self._db.total_changes
            self._db.execute(sql, params)
            self._db.commit()
            after = self._db.total_changes
        deleted = max(0, int(after - before))
        logger.info("Purged %d mailbox messages for %d agent IDs", deleted, len(normalized_ids))
        return deleted

    def close(self) -> None:
        """Close the SQLite connection."""
        self._db.close()


__all__ = ["AgentMailbox", "MailboxMessage"]
