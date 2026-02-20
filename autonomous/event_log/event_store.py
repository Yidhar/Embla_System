"""Lightweight JSONL event store for autonomous workflows."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class EventStore:
    """Append-only JSONL event store."""

    file_path: Path

    def __post_init__(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        row = {
            "timestamp": _utc_iso(),
            "event_type": event_type,
            "payload": payload,
        }
        line = json.dumps(row, ensure_ascii=False)
        with self._lock:
            with self.file_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def read_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        if limit <= 0 or not self.file_path.exists():
            return []
        lines = self.file_path.read_text(encoding="utf-8").splitlines()
        rows: List[Dict[str, Any]] = []
        for line in lines[-limit:]:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows
