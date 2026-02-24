"""SQLite-backed workflow state persistence."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from autonomous.event_log.event_schema import build_event_envelope, is_event_envelope, normalize_event_envelope


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().isoformat()


def _parse_iso(timestamp: str) -> datetime:
    normalized = str(timestamp or "").replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json(payload: Dict[str, Any] | None) -> str:
    return json.dumps(payload or {}, ensure_ascii=False)


@dataclass(frozen=True)
class LeaseStatus:
    lease_name: str
    owner_id: str
    fencing_epoch: int
    lease_expire_at: str
    is_owner: bool
    changed: bool


@dataclass
class WorkflowStore:
    """Durable store for workflow state transitions and command logs."""

    db_path: Path
    schema_path: Optional[Path] = None

    def __post_init__(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.schema_path is None:
            self.schema_path = Path(__file__).with_name("schema.sql")
        self._lock = threading.Lock()
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.row_factory = sqlite3.Row
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        schema = self.schema_path.read_text(encoding="utf-8")
        with self._lock:
            with self._connect() as conn:
                conn.executescript(schema)
                self._ensure_outbox_columns(conn)
                conn.commit()

    @staticmethod
    def _ensure_outbox_columns(conn: sqlite3.Connection) -> None:
        rows = conn.execute("PRAGMA table_info(outbox_event)").fetchall()
        existing = {str(row["name"]) for row in rows}
        required: Dict[str, str] = {
            "dispatch_attempts": "INTEGER NOT NULL DEFAULT 0",
            "max_attempts": "INTEGER NOT NULL DEFAULT 5",
            "last_error": "TEXT",
            "next_retry_at": "TEXT",
        }
        for column, ddl in required.items():
            if column in existing:
                continue
            conn.execute(f"ALTER TABLE outbox_event ADD COLUMN {column} {ddl}")

    def create_workflow(
        self,
        workflow_id: str,
        task_id: str,
        initial_state: str = "GoalAccepted",
        max_retries: int = 0,
    ) -> None:
        now = _now_iso()
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO workflow_state
                    (workflow_id, task_id, current_state, retry_count, max_retries, created_at, updated_at)
                    VALUES (?, ?, ?, 0, ?, ?, ?)
                    """,
                    (workflow_id, task_id, initial_state, max_retries, now, now),
                )
                if cursor.rowcount > 0:
                    conn.execute(
                        """
                        INSERT INTO workflow_event
                        (transition_id, workflow_id, from_state, to_state, reason, payload_json, created_at)
                        VALUES (?, ?, NULL, ?, ?, ?, ?)
                        """,
                        (str(uuid.uuid4()), workflow_id, "workflow_created", "", _json({"task_id": task_id}), now),
                    )
                conn.commit()

    def transition(
        self,
        workflow_id: str,
        to_state: str,
        reason: str = "",
        payload: Dict[str, Any] | None = None,
    ) -> None:
        now = _now_iso()
        reason_lower = reason.lower()
        should_capture_error = to_state in {"FailedExhausted", "FailedHard", "Killed", "Reworking"} or "fail" in reason_lower
        error_value = reason if should_capture_error else ""
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT current_state, retry_count FROM workflow_state WHERE workflow_id = ?",
                    (workflow_id,),
                ).fetchone()
                if row is None:
                    raise ValueError(f"workflow not found: {workflow_id}")
                from_state = row["current_state"]
                retry_count = int(row["retry_count"])
                if to_state == "Reworking":
                    retry_count += 1
                conn.execute(
                    """
                    UPDATE workflow_state
                    SET current_state = ?, retry_count = ?, updated_at = ?, last_error = CASE WHEN ? = '' THEN last_error ELSE ? END
                    WHERE workflow_id = ?
                    """,
                    (to_state, retry_count, now, error_value, error_value, workflow_id),
                )
                conn.execute(
                    """
                    INSERT INTO workflow_event
                    (transition_id, workflow_id, from_state, to_state, reason, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (str(uuid.uuid4()), workflow_id, from_state, to_state, reason, _json(payload), now),
                )
                conn.commit()

    def create_command(
        self,
        workflow_id: str,
        step_name: str,
        command_type: str,
        idempotency_key: str,
        attempt: int,
        max_attempt: int,
        fencing_epoch: int = 0,
    ) -> str:
        now = _now_iso()
        with self._lock:
            with self._connect() as conn:
                existing = conn.execute(
                    """
                    SELECT command_id
                    FROM workflow_command
                    WHERE workflow_id = ? AND idempotency_key = ?
                    """,
                    (workflow_id, idempotency_key),
                ).fetchone()
                if existing is not None:
                    command_id = str(existing["command_id"])
                    conn.execute(
                        """
                        UPDATE workflow_command
                        SET updated_at = ?
                        WHERE command_id = ?
                        """,
                        (now, command_id),
                    )
                    conn.commit()
                    return command_id

                command_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO workflow_command
                    (command_id, workflow_id, step_name, command_type, idempotency_key, fencing_epoch,
                     status, attempt, max_attempt, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?)
                    """,
                    (
                        command_id,
                        workflow_id,
                        step_name,
                        command_type,
                        idempotency_key,
                        fencing_epoch,
                        attempt,
                        max_attempt,
                        now,
                        now,
                    ),
                )
                conn.commit()
                return command_id

    def update_command(self, command_id: str, status: str, last_error: str = "") -> None:
        now = _now_iso()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE workflow_command
                    SET status = ?, last_error = ?, updated_at = ?
                    WHERE command_id = ?
                    """,
                    (status, last_error, now, command_id),
                )
                conn.commit()

    def enqueue_outbox(
        self,
        workflow_id: str,
        event_type: str,
        payload: Dict[str, Any] | None = None,
        *,
        max_attempts: int = 5,
    ) -> int:
        now = _now_iso()
        payload_data = dict(payload or {})
        if is_event_envelope(payload_data):
            envelope = normalize_event_envelope(
                payload_data,
                fallback_event_type=event_type,
                fallback_timestamp=now,
            )
        else:
            envelope = build_event_envelope(
                event_type,
                payload_data,
                source=str(payload_data.get("source") or "autonomous.workflow_store"),
                timestamp=now,
            )
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO outbox_event
                    (workflow_id, event_type, payload_json, status, dispatch_attempts, max_attempts, created_at, updated_at)
                    VALUES (?, ?, ?, 'pending', 0, ?, ?, ?)
                    """,
                    (workflow_id, event_type, _json(envelope), max(1, int(max_attempts)), now, now),
                )
                conn.commit()
                return int(cur.lastrowid)

    def read_pending_outbox(self, limit: int = 100) -> List[Dict[str, Any]]:
        now = _now_iso()
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        outbox_id,
                        workflow_id,
                        event_type,
                        payload_json,
                        status,
                        dispatch_attempts,
                        max_attempts,
                        last_error,
                        next_retry_at,
                        created_at,
                        updated_at
                    FROM outbox_event
                    WHERE status = 'pending'
                      AND dispatch_attempts < max_attempts
                      AND (next_retry_at IS NULL OR next_retry_at <= ?)
                    ORDER BY outbox_id ASC
                    LIMIT ?
                    """,
                    (now, limit),
                ).fetchall()
        result: List[Dict[str, Any]] = []
        for row in rows:
            payload_json = row["payload_json"] or "{}"
            try:
                payload_raw = json.loads(payload_json)
            except json.JSONDecodeError:
                payload_raw = {"raw": payload_json}

            if isinstance(payload_raw, dict) and is_event_envelope(payload_raw):
                envelope = normalize_event_envelope(
                    payload_raw,
                    fallback_event_type=str(row["event_type"]),
                    fallback_timestamp=str(row["created_at"]),
                )
            else:
                payload_data = payload_raw if isinstance(payload_raw, dict) else {"raw": payload_raw}
                envelope = build_event_envelope(
                    str(row["event_type"]),
                    payload_data,
                    source="autonomous.workflow_store",
                    timestamp=str(row["created_at"]),
                )

            payload = envelope.get("data")
            if not isinstance(payload, dict):
                payload = {"raw": payload}
            result.append(
                {
                    "outbox_id": int(row["outbox_id"]),
                    "workflow_id": row["workflow_id"],
                    "event_type": envelope.get("event_type", row["event_type"]),
                    "payload": payload,
                    "event_envelope": envelope,
                    "schema_version": envelope.get("schema_version"),
                    "source": envelope.get("source"),
                    "severity": envelope.get("severity"),
                    "trace_id": envelope.get("trace_id"),
                    "status": row["status"],
                    "dispatch_attempts": int(row["dispatch_attempts"] or 0),
                    "max_attempts": int(row["max_attempts"] or 1),
                    "last_error": row["last_error"] or "",
                    "next_retry_at": row["next_retry_at"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return result

    def mark_outbox_dispatched(self, outbox_id: int) -> None:
        now = _now_iso()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE outbox_event
                    SET status = 'dispatched', last_error = '', next_retry_at = NULL, updated_at = ?
                    WHERE outbox_id = ?
                    """,
                    (now, outbox_id),
                )
                conn.commit()

    def is_inbox_processed(self, consumer: str, message_id: str) -> bool:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT 1
                    FROM inbox_dedup
                    WHERE consumer = ? AND message_id = ?
                    """,
                    (consumer, message_id),
                ).fetchone()
                return row is not None

    def complete_outbox_for_consumer(self, outbox_id: int, consumer: str, message_id: str) -> None:
        """Atomically mark outbox dispatched and persist consumer dedup marker."""

        now = _now_iso()
        with self._lock:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT OR IGNORE INTO inbox_dedup
                    (consumer, message_id, processed_at)
                    VALUES (?, ?, ?)
                    """,
                    (consumer, message_id, now),
                )
                conn.execute(
                    """
                    UPDATE outbox_event
                    SET status = 'dispatched', last_error = '', next_retry_at = NULL, updated_at = ?
                    WHERE outbox_id = ?
                    """,
                    (now, outbox_id),
                )
                conn.commit()

    def record_outbox_attempt_failure(
        self,
        outbox_id: int,
        error: str,
        *,
        base_backoff_seconds: float = 2.0,
        max_backoff_seconds: float = 120.0,
    ) -> Dict[str, Any]:
        now_dt = _now_utc()
        now = now_dt.isoformat()
        with self._lock:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    """
                    SELECT dispatch_attempts, max_attempts
                    FROM outbox_event
                    WHERE outbox_id = ?
                    """,
                    (outbox_id,),
                ).fetchone()
                if row is None:
                    conn.commit()
                    return {
                        "outbox_id": outbox_id,
                        "attempts": 0,
                        "max_attempts": 0,
                        "status": "missing",
                        "exhausted": True,
                        "next_retry_at": None,
                    }

                attempts = int(row["dispatch_attempts"] or 0) + 1
                max_attempts = max(1, int(row["max_attempts"] or 1))
                exhausted = attempts >= max_attempts
                status = "dead_letter" if exhausted else "pending"

                if exhausted:
                    next_retry_at: str | None = None
                else:
                    base = max(0.0, float(base_backoff_seconds))
                    max_backoff = max(base, float(max_backoff_seconds))
                    backoff = min(max_backoff, base * (2 ** max(0, attempts - 1)))
                    next_retry_at = (now_dt + timedelta(seconds=backoff)).isoformat()

                conn.execute(
                    """
                    UPDATE outbox_event
                    SET dispatch_attempts = ?,
                        status = ?,
                        last_error = ?,
                        next_retry_at = ?,
                        updated_at = ?
                    WHERE outbox_id = ?
                    """,
                    (attempts, status, str(error or ""), next_retry_at, now, outbox_id),
                )
                conn.commit()
        return {
            "outbox_id": outbox_id,
            "attempts": attempts,
            "max_attempts": max_attempts,
            "status": status,
            "exhausted": exhausted,
            "next_retry_at": next_retry_at,
        }

    def try_acquire_or_renew_lease(self, lease_name: str, owner_id: str, ttl_seconds: int) -> LeaseStatus:
        ttl = max(1, int(ttl_seconds))
        now_dt = _now_utc()
        expire_at = (now_dt + timedelta(seconds=ttl)).isoformat()
        now = now_dt.isoformat()

        with self._lock:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    """
                    SELECT lease_name, owner_id, fencing_epoch, lease_expire_at
                    FROM orchestrator_lease
                    WHERE lease_name = ?
                    """,
                    (lease_name,),
                ).fetchone()

                if row is None:
                    conn.execute(
                        """
                        INSERT INTO orchestrator_lease
                        (lease_name, owner_id, fencing_epoch, lease_expire_at, updated_at)
                        VALUES (?, ?, 1, ?, ?)
                        """,
                        (lease_name, owner_id, expire_at, now),
                    )
                    conn.commit()
                    return LeaseStatus(
                        lease_name=lease_name,
                        owner_id=owner_id,
                        fencing_epoch=1,
                        lease_expire_at=expire_at,
                        is_owner=True,
                        changed=True,
                    )

                current_owner = str(row["owner_id"])
                current_epoch = int(row["fencing_epoch"])
                current_expire = str(row["lease_expire_at"])
                expired = _parse_iso(current_expire) <= now_dt

                if current_owner == owner_id:
                    conn.execute(
                        """
                        UPDATE orchestrator_lease
                        SET lease_expire_at = ?, updated_at = ?
                        WHERE lease_name = ?
                        """,
                        (expire_at, now, lease_name),
                    )
                    conn.commit()
                    return LeaseStatus(
                        lease_name=lease_name,
                        owner_id=owner_id,
                        fencing_epoch=current_epoch,
                        lease_expire_at=expire_at,
                        is_owner=True,
                        changed=False,
                    )

                if expired:
                    next_epoch = current_epoch + 1
                    conn.execute(
                        """
                        UPDATE orchestrator_lease
                        SET owner_id = ?, fencing_epoch = ?, lease_expire_at = ?, updated_at = ?
                        WHERE lease_name = ?
                        """,
                        (owner_id, next_epoch, expire_at, now, lease_name),
                    )
                    conn.commit()
                    return LeaseStatus(
                        lease_name=lease_name,
                        owner_id=owner_id,
                        fencing_epoch=next_epoch,
                        lease_expire_at=expire_at,
                        is_owner=True,
                        changed=True,
                    )

                conn.commit()
                return LeaseStatus(
                    lease_name=lease_name,
                    owner_id=current_owner,
                    fencing_epoch=current_epoch,
                    lease_expire_at=current_expire,
                    is_owner=False,
                    changed=False,
                )

    def read_lease(self, lease_name: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT lease_name, owner_id, fencing_epoch, lease_expire_at, updated_at
                    FROM orchestrator_lease
                    WHERE lease_name = ?
                    """,
                    (lease_name,),
                ).fetchone()
        if row is None:
            return None
        return {
            "lease_name": row["lease_name"],
            "owner_id": row["owner_id"],
            "fencing_epoch": int(row["fencing_epoch"]),
            "lease_expire_at": row["lease_expire_at"],
            "updated_at": row["updated_at"],
        }

    def is_lease_owner(self, lease_name: str, owner_id: str, fencing_epoch: int) -> bool:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT owner_id, fencing_epoch, lease_expire_at
                    FROM orchestrator_lease
                    WHERE lease_name = ?
                    """,
                    (lease_name,),
                ).fetchone()
        if row is None:
            return False
        return (
            str(row["owner_id"]) == owner_id
            and int(row["fencing_epoch"]) == int(fencing_epoch)
            and _parse_iso(str(row["lease_expire_at"])) > _now_utc()
        )

    def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT workflow_id, task_id, current_state, retry_count, max_retries, last_error, created_at, updated_at
                    FROM workflow_state
                    WHERE workflow_id = ?
                    """,
                    (workflow_id,),
                ).fetchone()
        if row is None:
            return None
        return {
            "workflow_id": row["workflow_id"],
            "task_id": row["task_id"],
            "current_state": row["current_state"],
            "retry_count": row["retry_count"],
            "max_retries": row["max_retries"],
            "last_error": row["last_error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
