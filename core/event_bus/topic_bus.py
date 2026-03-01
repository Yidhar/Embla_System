"""WS25-001 topic-oriented event bus with durable persistence."""

from __future__ import annotations

import asyncio
import fnmatch
import json
import os
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from core.event_bus.event_schema import (
    DEFAULT_EVENT_SOURCE,
    build_event_envelope,
    is_event_envelope,
    normalize_event_envelope,
)


EventHandler = Callable[[Dict[str, Any]], Any]


_TOPIC_RULES: Dict[str, tuple[str, ...]] = {
    "system": ("watchdog", "cpu", "memory", "disk", "network", "system"),
    "log": ("log", "error", "exception", "trace"),
    "cron": ("cron", "schedule", "timer"),
    "agent": ("task", "workflow", "agent", "release", "outbox"),
    "tool": ("tool", "cli", "mcp", "executor"),
    "evolution": ("evolution", "prompt", "dna"),
    "mutex": ("mutex", "lock", "lease", "fencing"),
    "budget": ("budget", "cost", "quota", "token"),
    "wake": ("wake", "sleep"),
}


def _normalize_topic_token(text: str) -> str:
    token = str(text or "").strip()
    token = re.sub(r"([a-z0-9])([A-Z])", r"\1.\2", token)
    token = token.replace(" ", ".").replace("_", ".").replace("-", ".")
    token = re.sub(r"\.+", ".", token).strip(".").lower()
    return token


def infer_event_topic(event_type: str, data: Dict[str, Any]) -> str:
    explicit_topic = str(data.get("topic") or data.get("channel") or "").strip()
    if explicit_topic:
        return _normalize_topic_token(explicit_topic)

    normalized = _normalize_topic_token(event_type)
    lowered = normalized.lower()
    for topic_prefix, markers in _TOPIC_RULES.items():
        if any(marker in lowered for marker in markers):
            return f"{topic_prefix}.{normalized}" if normalized else topic_prefix
    return f"agent.{normalized}" if normalized else "agent.unknown"


@dataclass(frozen=True)
class TopicSubscription:
    subscription_id: str
    pattern: str
    timeout_ms: int = 5_000
    max_retries: int = 1


@dataclass(frozen=True)
class ReplayDispatchResult:
    anchor_id: str
    topic_pattern: str
    scanned_count: int
    dispatched_count: int
    deduped_count: int
    failed_count: int
    last_seq: int
    next_from_seq: int
    from_seq: int
    to_seq: int


class TopicEventBus:
    """In-process topic bus with SQLite persistence and local subscriptions."""

    def __init__(
        self,
        *,
        db_path: Path,
        mirror_file_path: Optional[Path] = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.mirror_file_path = Path(mirror_file_path) if mirror_file_path is not None else None
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.mirror_file_path is not None:
            self.mirror_file_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._subscribers: Dict[str, tuple[TopicSubscription, EventHandler]] = {}
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS topic_event (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            topic TEXT NOT NULL,
            event_type TEXT NOT NULL,
            source TEXT NOT NULL,
            severity TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            partition_ym TEXT NOT NULL DEFAULT '',
            envelope_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_topic_event_topic_seq ON topic_event(topic, seq);
        CREATE INDEX IF NOT EXISTS idx_topic_event_timestamp ON topic_event(timestamp);
        CREATE TABLE IF NOT EXISTS dead_letter_event (
            dlq_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL,
            topic TEXT NOT NULL,
            subscription_pattern TEXT NOT NULL,
            error TEXT NOT NULL,
            retry_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_dead_letter_event_event_id ON dead_letter_event(event_id);
        CREATE TABLE IF NOT EXISTS replay_anchor (
            anchor_id TEXT PRIMARY KEY,
            topic_pattern TEXT NOT NULL,
            last_seq INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS replay_dedupe (
            anchor_id TEXT NOT NULL,
            subscription_pattern TEXT NOT NULL,
            dedupe_key TEXT NOT NULL,
            event_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(anchor_id, subscription_pattern, dedupe_key)
        );
        CREATE INDEX IF NOT EXISTS idx_replay_dedupe_anchor_seq ON replay_dedupe(anchor_id, seq);
        """
        with self._lock:
            with self._connect() as conn:
                conn.executescript(schema)
                self._migrate_topic_event_partition_column(conn)
                conn.commit()

    @staticmethod
    def _partition_from_timestamp(timestamp: str) -> str:
        parsed = _parse_iso_datetime(timestamp)
        if parsed is None:
            parsed = datetime.now(timezone.utc)
        return parsed.strftime("%Y%m")

    def _migrate_topic_event_partition_column(self, conn: sqlite3.Connection) -> None:
        columns = conn.execute("PRAGMA table_info(topic_event)").fetchall()
        column_names = {str(row["name"]) for row in columns}
        if "partition_ym" not in column_names:
            conn.execute("ALTER TABLE topic_event ADD COLUMN partition_ym TEXT NOT NULL DEFAULT ''")
        conn.execute(
            "UPDATE topic_event SET partition_ym = strftime('%Y%m', replace(substr(timestamp, 1, 19), 'T', ' ')) "
            "WHERE coalesce(partition_ym, '') = ''"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_topic_event_partition_seq ON topic_event(partition_ym, seq)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_topic_event_partition_topic_seq ON topic_event(partition_ym, topic, seq)"
        )

    def subscribe(
        self,
        pattern: str,
        handler: EventHandler,
        *,
        timeout_ms: int = 5_000,
        max_retries: int = 1,
    ) -> TopicSubscription:
        normalized_pattern = _normalize_topic_token(pattern) or "*"
        subscription = TopicSubscription(
            subscription_id=f"sub_{uuid.uuid4().hex[:16]}",
            pattern=normalized_pattern,
            timeout_ms=max(100, int(timeout_ms)),
            max_retries=max(1, int(max_retries)),
        )
        with self._lock:
            self._subscribers[subscription.subscription_id] = (subscription, handler)
        return subscription

    def unsubscribe(self, subscription: TopicSubscription | str) -> None:
        subscription_id = subscription if isinstance(subscription, str) else subscription.subscription_id
        with self._lock:
            self._subscribers.pop(str(subscription_id), None)

    def publish(
        self,
        topic: str,
        payload: Dict[str, Any],
        *,
        event_type: str | None = None,
        source: str | None = None,
        severity: str | None = None,
        idempotency_key: str | None = None,
        timestamp: str | None = None,
    ) -> str:
        payload_dict = dict(payload or {})
        normalized_topic = _normalize_topic_token(topic) or infer_event_topic(str(event_type or ""), payload_dict)
        envelope = self._build_envelope(
            payload_dict,
            event_type=event_type,
            source=source,
            severity=severity,
            idempotency_key=idempotency_key,
            timestamp=timestamp,
        )
        envelope["topic"] = normalized_topic
        partition_ym = self._partition_from_timestamp(str(envelope.get("timestamp") or ""))

        envelope_json = json.dumps(envelope, ensure_ascii=False)
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO topic_event
                    (event_id, topic, event_type, source, severity, idempotency_key, timestamp, partition_ym, envelope_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(envelope.get("event_id") or ""),
                        normalized_topic,
                        str(envelope.get("event_type") or ""),
                        str(envelope.get("source") or ""),
                        str(envelope.get("severity") or ""),
                        str(envelope.get("idempotency_key") or ""),
                        str(envelope.get("timestamp") or ""),
                        partition_ym,
                        envelope_json,
                    ),
                )
                conn.commit()
            self._append_mirror(envelope)

        self._dispatch_to_subscribers(envelope)
        return str(envelope.get("event_id") or "")

    def _build_envelope(
        self,
        payload: Dict[str, Any],
        *,
        event_type: str | None,
        source: str | None,
        severity: str | None,
        idempotency_key: str | None,
        timestamp: str | None,
    ) -> Dict[str, Any]:
        if is_event_envelope(payload):
            normalized = normalize_event_envelope(
                payload,
                fallback_event_type=str(event_type or payload.get("event_type") or "TopicEvent"),
                fallback_timestamp=str(timestamp or payload.get("timestamp") or ""),
            )
            if source:
                normalized["source"] = str(source)
            if severity:
                normalized["severity"] = str(severity)
            if idempotency_key:
                normalized["idempotency_key"] = str(idempotency_key)
            return normalized

        event_type_value = str(event_type or payload.get("event_type") or "TopicEvent")
        return build_event_envelope(
            event_type_value,
            payload,
            source=str(source or payload.get("source") or DEFAULT_EVENT_SOURCE),
            severity=str(severity or payload.get("severity") or ""),
            idempotency_key=str(idempotency_key or payload.get("idempotency_key") or ""),
            timestamp=str(timestamp or payload.get("timestamp") or ""),
        )

    def _append_mirror(self, envelope: Dict[str, Any]) -> None:
        if self.mirror_file_path is None:
            return
        row = {**envelope, "payload": dict(envelope.get("data") or {})}
        with self.mirror_file_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _dispatch_to_subscribers(self, envelope: Dict[str, Any]) -> None:
        topic = str(envelope.get("topic") or "")
        with self._lock:
            subscribers = list(self._subscribers.values())
        for subscription, handler in subscribers:
            if not fnmatch.fnmatchcase(topic, subscription.pattern):
                continue
            self._deliver_to_handler(subscription, handler, envelope)

    def _deliver_to_handler(
        self,
        subscription: TopicSubscription,
        handler: EventHandler,
        envelope: Dict[str, Any],
    ) -> bool:
        for _attempt in range(subscription.max_retries):
            try:
                result = handler(dict(envelope))
                if asyncio.iscoroutine(result):
                    self._await_handler_result(
                        result,
                        timeout_ms=subscription.timeout_ms,
                    )
                return True
            except Exception as exc:
                self._record_dead_letter(
                    event_id=str(envelope.get("event_id") or ""),
                    topic=str(envelope.get("topic") or ""),
                    subscription_pattern=subscription.pattern,
                    error=str(exc),
                )
        return False

    @staticmethod
    def _await_handler_result(coro: Any, *, timeout_ms: int) -> None:
        timeout_seconds = max(0.1, float(timeout_ms) / 1000.0)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(asyncio.wait_for(coro, timeout=timeout_seconds))
            return

        task = loop.create_task(asyncio.wait_for(coro, timeout=timeout_seconds))
        # Fire-and-forget in running-loop context; completion/failure will surface in task exception logs.
        task.add_done_callback(lambda _task: None)

    def _record_dead_letter(
        self,
        *,
        event_id: str,
        topic: str,
        subscription_pattern: str,
        error: str,
    ) -> None:
        now = build_event_envelope("DeadLetterEvent", {}, source=DEFAULT_EVENT_SOURCE)["timestamp"]
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO dead_letter_event
                    (event_id, topic, subscription_pattern, error, retry_count, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 0, ?, ?)
                    """,
                    (event_id, topic, subscription_pattern, str(error), now, now),
                )
                conn.commit()

    @staticmethod
    def _utc_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _normalize_anchor_id(anchor_id: str) -> str:
        normalized = str(anchor_id or "").strip()
        if not normalized:
            raise ValueError("anchor_id is required")
        return normalized

    def get_replay_anchor(self, anchor_id: str, *, topic_pattern: str | None = None) -> Dict[str, Any]:
        normalized_anchor = self._normalize_anchor_id(anchor_id)
        normalized_pattern = _normalize_topic_token(topic_pattern or "") or "*"
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT anchor_id, topic_pattern, last_seq, updated_at FROM replay_anchor WHERE anchor_id = ?",
                    (normalized_anchor,),
                ).fetchone()
        if row is None:
            self._upsert_replay_anchor(
                anchor_id=normalized_anchor,
                topic_pattern=normalized_pattern,
                last_seq=0,
            )
            with self._lock:
                with self._connect() as conn:
                    row = conn.execute(
                        "SELECT anchor_id, topic_pattern, last_seq, updated_at FROM replay_anchor WHERE anchor_id = ?",
                        (normalized_anchor,),
                    ).fetchone()
            if row is None:
                return {
                    "anchor_id": normalized_anchor,
                    "topic_pattern": normalized_pattern,
                    "last_seq": 0,
                    "updated_at": "",
                }
        existing_pattern = str(row["topic_pattern"] or "*")
        if topic_pattern is not None and existing_pattern != normalized_pattern:
            self._upsert_replay_anchor(
                anchor_id=normalized_anchor,
                topic_pattern=normalized_pattern,
                last_seq=int(row["last_seq"] or 0),
            )
            existing_pattern = normalized_pattern
        return {
            "anchor_id": str(row["anchor_id"] or normalized_anchor),
            "topic_pattern": existing_pattern,
            "last_seq": int(row["last_seq"] or 0),
            "updated_at": str(row["updated_at"] or ""),
        }

    def reset_replay_anchor(
        self,
        anchor_id: str,
        *,
        last_seq: int = 0,
        topic_pattern: str | None = None,
        clear_dedupe: bool = False,
    ) -> Dict[str, Any]:
        current = self.get_replay_anchor(anchor_id, topic_pattern=topic_pattern)
        normalized_anchor = self._normalize_anchor_id(anchor_id)
        target_pattern = _normalize_topic_token(topic_pattern or "") or str(current.get("topic_pattern") or "*")
        target_last_seq = max(0, int(last_seq))
        self._upsert_replay_anchor(
            anchor_id=normalized_anchor,
            topic_pattern=target_pattern,
            last_seq=target_last_seq,
        )
        if clear_dedupe:
            with self._lock:
                with self._connect() as conn:
                    conn.execute("DELETE FROM replay_dedupe WHERE anchor_id = ?", (normalized_anchor,))
                    conn.commit()
        return self.get_replay_anchor(normalized_anchor)

    def replay_dispatch(
        self,
        *,
        anchor_id: str,
        topic_pattern: str | None = None,
        from_seq: int | None = None,
        to_seq: int | None = None,
        limit: int = 1_000,
    ) -> ReplayDispatchResult:
        anchor = self.get_replay_anchor(anchor_id, topic_pattern=topic_pattern)
        normalized_anchor = str(anchor["anchor_id"])
        resolved_pattern = _normalize_topic_token(topic_pattern or "") or str(anchor.get("topic_pattern") or "*")
        start_seq = max(1, int(from_seq)) if from_seq is not None else max(1, int(anchor.get("last_seq") or 0) + 1)
        rows = self.replay(
            topic_pattern=None if resolved_pattern == "*" else resolved_pattern,
            from_seq=start_seq,
            to_seq=to_seq,
            limit=limit,
        )

        dispatched_count = 0
        deduped_count = 0
        failed_count = 0
        highest_seq = int(anchor.get("last_seq") or 0)
        first_failed_seq: int | None = None

        for envelope in rows:
            seq = int(envelope.get("seq") or 0)
            if seq > highest_seq:
                highest_seq = seq
            event_failed = False
            topic = str(envelope.get("topic") or "")
            with self._lock:
                subscribers = list(self._subscribers.values())
            for subscription, handler in subscribers:
                if not fnmatch.fnmatchcase(topic, subscription.pattern):
                    continue
                dedupe_key = str(envelope.get("idempotency_key") or envelope.get("event_id") or f"seq:{seq}")
                if self._is_replay_deduped(
                    anchor_id=normalized_anchor,
                    subscription_pattern=subscription.pattern,
                    dedupe_key=dedupe_key,
                ):
                    deduped_count += 1
                    continue
                delivered = self._deliver_to_handler(subscription, handler, envelope)
                if delivered:
                    self._mark_replay_deduped(
                        anchor_id=normalized_anchor,
                        subscription_pattern=subscription.pattern,
                        dedupe_key=dedupe_key,
                        event_id=str(envelope.get("event_id") or ""),
                        seq=seq,
                    )
                    dispatched_count += 1
                    continue
                failed_count += 1
                event_failed = True
            if event_failed and (first_failed_seq is None or seq < first_failed_seq):
                first_failed_seq = seq

        if first_failed_seq is None:
            committed_seq = highest_seq
        else:
            committed_seq = max(0, first_failed_seq - 1)

        self._upsert_replay_anchor(
            anchor_id=normalized_anchor,
            topic_pattern=resolved_pattern,
            last_seq=committed_seq,
        )
        upper_seq = int(rows[-1].get("seq") or (start_seq - 1)) if rows else (start_seq - 1)
        return ReplayDispatchResult(
            anchor_id=normalized_anchor,
            topic_pattern=resolved_pattern,
            scanned_count=len(rows),
            dispatched_count=dispatched_count,
            deduped_count=deduped_count,
            failed_count=failed_count,
            last_seq=committed_seq,
            next_from_seq=committed_seq + 1,
            from_seq=start_seq,
            to_seq=upper_seq,
        )

    def _upsert_replay_anchor(
        self,
        *,
        anchor_id: str,
        topic_pattern: str,
        last_seq: int,
    ) -> None:
        now = self._utc_iso()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO replay_anchor (anchor_id, topic_pattern, last_seq, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(anchor_id)
                    DO UPDATE SET
                        topic_pattern = excluded.topic_pattern,
                        last_seq = excluded.last_seq,
                        updated_at = excluded.updated_at
                    """,
                    (
                        str(anchor_id),
                        _normalize_topic_token(topic_pattern) or "*",
                        max(0, int(last_seq)),
                        now,
                    ),
                )
                conn.commit()

    def _is_replay_deduped(
        self,
        *,
        anchor_id: str,
        subscription_pattern: str,
        dedupe_key: str,
    ) -> bool:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT 1
                    FROM replay_dedupe
                    WHERE anchor_id = ? AND subscription_pattern = ? AND dedupe_key = ?
                    LIMIT 1
                    """,
                    (str(anchor_id), str(subscription_pattern), str(dedupe_key)),
                ).fetchone()
        return row is not None

    def _mark_replay_deduped(
        self,
        *,
        anchor_id: str,
        subscription_pattern: str,
        dedupe_key: str,
        event_id: str,
        seq: int,
    ) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO replay_dedupe
                    (anchor_id, subscription_pattern, dedupe_key, event_id, seq, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(anchor_id, subscription_pattern, dedupe_key) DO NOTHING
                    """,
                    (
                        str(anchor_id),
                        str(subscription_pattern),
                        str(dedupe_key),
                        str(event_id),
                        max(0, int(seq)),
                        self._utc_iso(),
                    ),
                )
                conn.commit()

    def replay(
        self,
        *,
        topic_pattern: str | None = None,
        from_seq: int = 1,
        to_seq: int | None = None,
        from_timestamp: str | None = None,
        to_timestamp: str | None = None,
        limit: int = 1_000,
    ) -> List[Dict[str, Any]]:
        normalized_pattern = _normalize_topic_token(topic_pattern or "") if topic_pattern else ""
        lower_seq = max(1, int(from_seq))
        upper_seq = int(to_seq) if to_seq is not None else None
        max_rows = max(1, int(limit))
        lower_ts = str(from_timestamp or "").strip()
        upper_ts = str(to_timestamp or "").strip()
        lower_partition = self._partition_from_timestamp(lower_ts) if lower_ts else ""
        upper_partition = self._partition_from_timestamp(upper_ts) if upper_ts else ""

        query = """
        SELECT seq, topic, envelope_json
        FROM topic_event
        WHERE seq >= ?
        """
        params: List[Any] = [lower_seq]
        if upper_seq is not None:
            query += " AND seq <= ?"
            params.append(upper_seq)
        if lower_partition:
            query += " AND partition_ym >= ?"
            params.append(lower_partition)
        if upper_partition:
            query += " AND partition_ym <= ?"
            params.append(upper_partition)
        if lower_ts:
            query += " AND timestamp >= ?"
            params.append(lower_ts)
        if upper_ts:
            query += " AND timestamp <= ?"
            params.append(upper_ts)
        query += " ORDER BY seq ASC LIMIT ?"
        params.append(max_rows)

        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(query, params).fetchall()

        result: List[Dict[str, Any]] = []
        for row in rows:
            try:
                envelope = json.loads(str(row["envelope_json"] or "{}"))
            except json.JSONDecodeError:
                continue
            if not isinstance(envelope, dict):
                continue
            envelope["seq"] = int(row["seq"])
            envelope["topic"] = str(row["topic"] or envelope.get("topic") or "")
            if normalized_pattern and not fnmatch.fnmatchcase(str(envelope.get("topic") or ""), normalized_pattern):
                continue
            result.append(envelope)
        return result

    def list_time_partitions(self, *, limit: int = 36) -> List[str]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT partition_ym
                    FROM topic_event
                    WHERE coalesce(partition_ym, '') <> ''
                    GROUP BY partition_ym
                    ORDER BY partition_ym DESC
                    LIMIT ?
                    """,
                    (max(1, int(limit)),),
                ).fetchall()
        return [str(row["partition_ym"] or "") for row in rows if str(row["partition_ym"] or "")]

    def read_recent(self, *, limit: int = 100, topic_pattern: str | None = None) -> List[Dict[str, Any]]:
        upper = self._latest_seq()
        if upper <= 0:
            return []
        lower = max(1, upper - max(1, int(limit)) + 1)
        return self.replay(topic_pattern=topic_pattern, from_seq=lower, to_seq=upper, limit=max(1, int(limit)))

    def _latest_seq(self) -> int:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT MAX(seq) AS max_seq FROM topic_event").fetchone()
        if row is None:
            return 0
        return int(row["max_seq"] or 0)

    def list_topics(self, *, limit: int = 200) -> List[str]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT topic
                    FROM topic_event
                    GROUP BY topic
                    ORDER BY MAX(seq) DESC
                    LIMIT ?
                    """,
                    (max(1, int(limit)),),
                ).fetchall()
        return [str(row["topic"] or "") for row in rows if str(row["topic"] or "")]

    def get_dead_letters(self, *, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT dlq_id, event_id, topic, subscription_pattern, error, retry_count, created_at, updated_at
                    FROM dead_letter_event
                    ORDER BY dlq_id DESC
                    LIMIT ?
                    """,
                    (max(1, int(limit)),),
                ).fetchall()
        return [
            {
                "dlq_id": int(row["dlq_id"]),
                "event_id": str(row["event_id"] or ""),
                "topic": str(row["topic"] or ""),
                "subscription_pattern": str(row["subscription_pattern"] or ""),
                "error": str(row["error"] or ""),
                "retry_count": int(row["retry_count"] or 0),
                "created_at": str(row["created_at"] or ""),
                "updated_at": str(row["updated_at"] or ""),
            }
            for row in rows
        ]

    def retry_dead_letter(self, event_id: str) -> bool:
        target_event_id = str(event_id or "").strip()
        if not target_event_id:
            return False

        with self._lock:
            with self._connect() as conn:
                event_row = conn.execute(
                    "SELECT envelope_json FROM topic_event WHERE event_id = ? ORDER BY seq DESC LIMIT 1",
                    (target_event_id,),
                ).fetchone()
                if event_row is None:
                    return False
                dlq_rows = conn.execute(
                    "SELECT dlq_id FROM dead_letter_event WHERE event_id = ?",
                    (target_event_id,),
                ).fetchall()

        try:
            envelope = json.loads(str(event_row["envelope_json"] or "{}"))
        except json.JSONDecodeError:
            return False
        if not isinstance(envelope, dict):
            return False

        self._dispatch_to_subscribers(envelope)
        if not dlq_rows:
            return True

        dlq_ids = [int(row["dlq_id"]) for row in dlq_rows]
        with self._lock:
            with self._connect() as conn:
                conn.executemany("DELETE FROM dead_letter_event WHERE dlq_id = ?", [(dlq_id,) for dlq_id in dlq_ids])
                conn.commit()
        return True

    def iter_subscriptions(self) -> Iterable[TopicSubscription]:
        with self._lock:
            subscriptions = [item[0] for item in self._subscribers.values()]
        return subscriptions


def _parse_iso_datetime(raw: Any) -> Optional[datetime]:
    text = str(raw or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def resolve_topic_db_path_from_mirror(file_path: Path) -> Path:
    mirror = Path(file_path)
    return mirror.with_name(f"{mirror.stem}_topics.db")


def should_enable_jsonl_mirror() -> bool:
    raw = str(os.environ.get("NAGA_EVENT_BUS_JSONL_MIRROR", "")).strip().lower()
    return raw in {"1", "true", "yes", "on", "y"}


__all__ = [
    "EventHandler",
    "ReplayDispatchResult",
    "TopicEventBus",
    "TopicSubscription",
    "infer_event_topic",
    "resolve_topic_db_path_from_mirror",
    "should_enable_jsonl_mirror",
]
