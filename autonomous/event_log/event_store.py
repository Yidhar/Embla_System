"""Lightweight JSONL event store for autonomous workflows."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from autonomous.event_log.event_schema import build_event_envelope, normalize_event_envelope


@dataclass
class EventStore:
    """Append-only JSONL event store."""

    file_path: Path

    def __post_init__(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def emit(
        self,
        event_type: str,
        payload: Dict[str, Any],
        *,
        source: str | None = None,
        severity: str | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        envelope = build_event_envelope(
            event_type,
            payload,
            source=source,
            severity=severity,
            idempotency_key=idempotency_key,
        )
        row = {**envelope, "payload": envelope["data"]}
        line = json.dumps(row, ensure_ascii=False)
        with self._lock:
            with self.file_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

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
