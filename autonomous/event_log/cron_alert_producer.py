"""WS25-002 cron/alert producers that publish into Topic Event Bus."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from autonomous.event_log.event_store import EventStore


@dataclass(frozen=True)
class CronScheduleSpec:
    schedule_id: str
    interval_seconds: float
    topic: str
    event_type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    run_immediately: bool = False


class CronEventProducer:
    """Lightweight in-process cron producer for event bus integration."""

    def __init__(self, *, event_store: EventStore, source: str = "autonomous.cron_scheduler") -> None:
        self.event_store = event_store
        self.source = str(source or "autonomous.cron_scheduler")
        self._schedules: Dict[str, CronScheduleSpec] = {}
        self._next_due_ts: Dict[str, float] = {}

    def add_schedule(
        self,
        *,
        schedule_id: str,
        interval_seconds: float,
        topic: str = "cron.generic",
        event_type: str = "CronScheduleTriggered",
        payload: Optional[Dict[str, Any]] = None,
        run_immediately: bool = False,
        now_ts: Optional[float] = None,
    ) -> CronScheduleSpec:
        normalized_id = str(schedule_id or "").strip()
        if not normalized_id:
            raise ValueError("schedule_id is required")
        interval = max(1.0, float(interval_seconds))
        spec = CronScheduleSpec(
            schedule_id=normalized_id,
            interval_seconds=interval,
            topic=str(topic or "cron.generic"),
            event_type=str(event_type or "CronScheduleTriggered"),
            payload=dict(payload or {}),
            run_immediately=bool(run_immediately),
        )
        self._schedules[normalized_id] = spec
        now = float(now_ts) if now_ts is not None else time.time()
        self._next_due_ts[normalized_id] = now if spec.run_immediately else now + spec.interval_seconds
        return spec

    def remove_schedule(self, schedule_id: str) -> None:
        normalized_id = str(schedule_id or "").strip()
        if not normalized_id:
            return
        self._schedules.pop(normalized_id, None)
        self._next_due_ts.pop(normalized_id, None)

    def run_due(self, *, now_ts: Optional[float] = None) -> List[str]:
        now = float(now_ts) if now_ts is not None else time.time()
        emitted_event_ids: List[str] = []
        for schedule_id, spec in list(self._schedules.items()):
            due_ts = float(self._next_due_ts.get(schedule_id, now + spec.interval_seconds))
            if now < due_ts:
                continue
            event_payload = {
                **dict(spec.payload),
                "schedule_id": schedule_id,
                "interval_seconds": spec.interval_seconds,
                "triggered_at": now,
            }
            event_id = self.event_store.publish(
                spec.topic,
                event_payload,
                event_type=spec.event_type,
                source=self.source,
                severity="info",
            )
            emitted_event_ids.append(event_id)
            self._next_due_ts[schedule_id] = now + spec.interval_seconds
        return emitted_event_ids


class AlertEventProducer:
    """Alert producer with dedupe window, publishing into event bus topics."""

    def __init__(
        self,
        *,
        event_store: EventStore,
        source: str = "autonomous.alert_manager",
        dedupe_window_seconds: float = 60.0,
    ) -> None:
        self.event_store = event_store
        self.source = str(source or "autonomous.alert_manager")
        self.dedupe_window_seconds = max(1.0, float(dedupe_window_seconds))
        self._last_emit_ts: Dict[str, float] = {}

    def emit_alert(
        self,
        *,
        alert_key: str,
        severity: str,
        payload: Optional[Dict[str, Any]] = None,
        topic: str = "alert.generic",
        event_type: str = "AlertRaised",
        now_ts: Optional[float] = None,
    ) -> str:
        key = str(alert_key or "").strip()
        if not key:
            raise ValueError("alert_key is required")
        now = float(now_ts) if now_ts is not None else time.time()
        dedupe_key = f"{key}:{severity}"
        last_ts = float(self._last_emit_ts.get(dedupe_key, 0.0))
        if last_ts > 0 and (now - last_ts) < self.dedupe_window_seconds:
            return ""

        normalized_payload = {
            **dict(payload or {}),
            "alert_key": key,
            "alert_severity": str(severity or "warn"),
            "raised_at": now,
        }
        event_id = self.event_store.publish(
            topic,
            normalized_payload,
            event_type=event_type,
            source=self.source,
            severity=str(severity or "warn"),
        )
        self._last_emit_ts[dedupe_key] = now
        return event_id

    def clear_dedupe_state(self) -> None:
        self._last_emit_ts.clear()


__all__ = [
    "AlertEventProducer",
    "CronEventProducer",
    "CronScheduleSpec",
]
