"""Lightweight JSONL event store for autonomous workflows."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List

from core.event_bus.event_schema import normalize_event_envelope
from core.event_bus.topic_bus import ReplayDispatchResult, TopicEventBus, TopicSubscription, infer_event_topic


@dataclass
class EventStore:
    """Append-only JSONL event store."""

    file_path: Path

    def __post_init__(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        topic_db_path = self.file_path.with_name(f"{self.file_path.stem}_topics.db")
        self.topic_bus = TopicEventBus(db_path=topic_db_path, mirror_file_path=self.file_path)

    def emit(
        self,
        event_type: str,
        payload: Dict[str, Any],
        *,
        source: str | None = None,
        severity: str | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        topic = infer_event_topic(event_type, dict(payload or {}))
        self.topic_bus.publish(
            topic,
            payload,
            event_type=event_type,
            source=source,
            severity=severity,
            idempotency_key=idempotency_key,
        )

    def publish(
        self,
        topic: str,
        payload: Dict[str, Any],
        *,
        event_type: str,
        source: str | None = None,
        severity: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        return self.topic_bus.publish(
            topic,
            payload,
            event_type=event_type,
            source=source,
            severity=severity,
            idempotency_key=idempotency_key,
        )

    def subscribe(
        self,
        pattern: str,
        handler: Callable[[Dict[str, Any]], Any],
        *,
        timeout_ms: int = 5_000,
        max_retries: int = 1,
    ) -> TopicSubscription:
        return self.topic_bus.subscribe(
            pattern,
            handler,
            timeout_ms=timeout_ms,
            max_retries=max_retries,
        )

    def unsubscribe(self, subscription: TopicSubscription | str) -> None:
        self.topic_bus.unsubscribe(subscription)

    def _read_raw_rows(self) -> List[Dict[str, Any]]:
        if not self.file_path.exists():
            return []
        lines = self.file_path.read_text(encoding="utf-8").splitlines()
        rows: List[Dict[str, Any]] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
        return rows

    def read_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        if limit <= 0:
            return []
        rows = self._read_raw_rows()
        normalized_rows: List[Dict[str, Any]] = []
        for row in rows[-limit:]:
            envelope = normalize_event_envelope(
                row,
                fallback_event_type=str(row.get("event_type") or ""),
                fallback_timestamp=str(row.get("timestamp") or ""),
            )
            normalized_rows.append({**envelope, "payload": dict(envelope.get("data") or {})})
        return normalized_rows

    def replay(
        self,
        *,
        limit: int = 1000,
        event_type: str | None = None,
        workflow_id: str | None = None,
        trace_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        rows = self.read_recent(limit=limit)
        result: List[Dict[str, Any]] = []
        for row in rows:
            if event_type and str(row.get("event_type")) != event_type:
                continue
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            row_workflow_id = str(row.get("workflow_id") or data.get("workflow_id") or "")
            row_trace_id = str(row.get("trace_id") or data.get("trace_id") or "")
            if workflow_id and row_workflow_id != workflow_id:
                continue
            if trace_id and row_trace_id != trace_id:
                continue
            result.append(row)
        return result

    def replay_by_topic(
        self,
        *,
        topic_pattern: str | None = None,
        from_seq: int = 1,
        to_seq: int | None = None,
        limit: int = 1_000,
    ) -> List[Dict[str, Any]]:
        return self.topic_bus.replay(
            topic_pattern=topic_pattern,
            from_seq=from_seq,
            to_seq=to_seq,
            limit=limit,
        )

    def replay_dispatch(
        self,
        *,
        anchor_id: str,
        topic_pattern: str | None = None,
        from_seq: int | None = None,
        to_seq: int | None = None,
        limit: int = 1_000,
    ) -> ReplayDispatchResult:
        return self.topic_bus.replay_dispatch(
            anchor_id=anchor_id,
            topic_pattern=topic_pattern,
            from_seq=from_seq,
            to_seq=to_seq,
            limit=limit,
        )

    def get_replay_anchor(self, anchor_id: str, *, topic_pattern: str | None = None) -> Dict[str, Any]:
        return self.topic_bus.get_replay_anchor(anchor_id, topic_pattern=topic_pattern)

    def reset_replay_anchor(
        self,
        anchor_id: str,
        *,
        last_seq: int = 0,
        topic_pattern: str | None = None,
        clear_dedupe: bool = False,
    ) -> Dict[str, Any]:
        return self.topic_bus.reset_replay_anchor(
            anchor_id,
            last_seq=last_seq,
            topic_pattern=topic_pattern,
            clear_dedupe=clear_dedupe,
        )

    def list_topics(self, *, limit: int = 200) -> List[str]:
        return self.topic_bus.list_topics(limit=limit)
