"""WS18-003 replay tooling for Event Bus recovery workflows."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.event_bus.event_store import EventStore


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str | None) -> Optional[datetime]:
    text = str(value or "").strip()
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


@dataclass(frozen=True)
class ReplayRequest:
    trace_id: str | None = None
    workflow_id: str | None = None
    event_type: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    limit: int = 2000
    read_only: bool = True
    operator: str = "unknown"
    reason: str = ""


@dataclass
class ReplayResult:
    request: ReplayRequest
    matched_events: List[Dict[str, Any]] = field(default_factory=list)
    recovery_plan: List[Dict[str, Any]] = field(default_factory=list)
    audit_record: Dict[str, Any] = field(default_factory=dict)


class EventReplayTool:
    """Read-only replay utility with audit logging."""

    def __init__(
        self,
        *,
        event_store: EventStore,
        audit_file: Path,
    ) -> None:
        self.event_store = event_store
        self.audit_file = audit_file
        self.audit_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def replay(self, request: ReplayRequest) -> ReplayResult:
        if not request.trace_id and not request.workflow_id and not request.event_type:
            raise ValueError("ReplayRequest requires at least one filter: trace_id/workflow_id/event_type")

        start_dt = _parse_iso(request.start_time)
        end_dt = _parse_iso(request.end_time)
        rows = self.event_store.replay(
            limit=max(1, int(request.limit)),
            event_type=request.event_type,
            workflow_id=request.workflow_id,
            trace_id=request.trace_id,
        )
        filtered = self._filter_by_window(rows, start_dt=start_dt, end_dt=end_dt)
        plan = self._build_recovery_plan(filtered)

        audit = {
            "ts": _utc_iso(),
            "request": {
                "trace_id": request.trace_id,
                "workflow_id": request.workflow_id,
                "event_type": request.event_type,
                "start_time": request.start_time,
                "end_time": request.end_time,
                "limit": int(request.limit),
                "read_only": bool(request.read_only),
                "operator": request.operator,
                "reason": request.reason,
            },
            "matched_count": len(filtered),
            "matched_event_ids": [str(row.get("event_id") or "") for row in filtered],
            "matched_event_types": sorted({str(row.get("event_type") or "") for row in filtered}),
            "trace_ids": sorted({str(row.get("trace_id") or row.get("data", {}).get("trace_id") or "") for row in filtered if str(row.get("trace_id") or row.get("data", {}).get("trace_id") or "")}),
            "workflow_ids": sorted({str(row.get("workflow_id") or row.get("data", {}).get("workflow_id") or "") for row in filtered if str(row.get("workflow_id") or row.get("data", {}).get("workflow_id") or "")}),
        }
        self._append_audit(audit)

        return ReplayResult(
            request=request,
            matched_events=filtered,
            recovery_plan=plan,
            audit_record=audit,
        )

    @staticmethod
    def _filter_by_window(
        rows: List[Dict[str, Any]],
        *,
        start_dt: Optional[datetime],
        end_dt: Optional[datetime],
    ) -> List[Dict[str, Any]]:
        if start_dt is None and end_dt is None:
            return list(rows)

        result: List[Dict[str, Any]] = []
        for row in rows:
            ts = _parse_iso(str(row.get("timestamp") or ""))
            if ts is None:
                continue
            if start_dt and ts < start_dt:
                continue
            if end_dt and ts > end_dt:
                continue
            result.append(row)
        return result

    @staticmethod
    def _build_recovery_plan(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not rows:
            return []

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            workflow_id = str(row.get("workflow_id") or data.get("workflow_id") or "unknown_workflow")
            grouped.setdefault(workflow_id, []).append(row)

        plans: List[Dict[str, Any]] = []
        for workflow_id, events in grouped.items():
            sorted_events = sorted(events, key=lambda item: str(item.get("timestamp") or ""))
            event_types = [str(item.get("event_type") or "") for item in sorted_events]
            plans.append(
                {
                    "workflow_id": workflow_id,
                    "event_count": len(sorted_events),
                    "first_ts": sorted_events[0].get("timestamp"),
                    "last_ts": sorted_events[-1].get("timestamp"),
                    "event_types": event_types,
                    "steps": [
                        f"replay({idx + 1}/{len(sorted_events)}): {event_type}"
                        for idx, event_type in enumerate(event_types)
                    ],
                }
            )
        plans.sort(key=lambda item: str(item.get("workflow_id") or ""))
        return plans

    def _append_audit(self, payload: Dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            with self.audit_file.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
