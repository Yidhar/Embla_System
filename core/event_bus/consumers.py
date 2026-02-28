"""Default event-bus consumers for runtime posture / incidents / release gate."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from core.event_bus.event_store import EventStore
from core.event_bus.topic_bus import TopicSubscription


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _safe_dict(payload: Any) -> Dict[str, Any]:
    return dict(payload) if isinstance(payload, dict) else {}


@dataclass(frozen=True)
class EventConsumerHooks:
    posture_subscription: TopicSubscription
    incident_subscription: TopicSubscription
    release_subscription: TopicSubscription
    posture_state_file: str
    incident_file: str
    release_gate_file: str


class RuntimePostureConsumer:
    """Maintains lightweight event posture counters as a runtime state file."""

    def __init__(self, *, state_file: Path, recent_limit: int = 50) -> None:
        self.state_file = Path(state_file)
        self.recent_limit = max(10, int(recent_limit))
        self._lock = threading.Lock()

    def handle(self, event: Dict[str, Any]) -> Dict[str, Any]:
        payload = _safe_dict(event)
        event_type = str(payload.get("event_type") or "unknown")
        severity = str(payload.get("severity") or "info").strip().lower() or "info"
        topic = str(payload.get("topic") or "")
        event_id = str(payload.get("event_id") or "")
        timestamp = str(payload.get("timestamp") or _utc_iso_now())

        with self._lock:
            state = _read_json(self.state_file)
            event_counts = _safe_dict(state.get("event_type_counts"))
            severity_counts = _safe_dict(state.get("severity_counts"))
            recent = state.get("recent_events")
            recent_events: List[Dict[str, Any]] = list(recent) if isinstance(recent, list) else []

            event_counts[event_type] = int(event_counts.get(event_type) or 0) + 1
            severity_counts[severity] = int(severity_counts.get(severity) or 0) + 1
            recent_events.append(
                {
                    "event_id": event_id,
                    "event_type": event_type,
                    "severity": severity,
                    "topic": topic,
                    "timestamp": timestamp,
                }
            )
            recent_events = recent_events[-self.recent_limit :]

            total_events = int(state.get("total_events") or 0) + 1
            snapshot = {
                "generated_at": _utc_iso_now(),
                "total_events": total_events,
                "event_type_counts": event_counts,
                "severity_counts": severity_counts,
                "last_event_type": event_type,
                "last_severity": severity,
                "last_topic": topic,
                "last_event_id": event_id,
                "last_event_timestamp": timestamp,
                "recent_events": recent_events,
                "state_file": _to_unix(self.state_file),
            }
            _write_json(self.state_file, snapshot)
        return {"ok": True}


class IncidentConsumer:
    """Persists incident-like events into a dedicated JSONL feed."""

    _INCIDENT_EVENT_TYPES = {
        "IncidentOpened",
        "ReleaseGateRejected",
        "TaskRejected",
        "WatchdogThresholdExceeded",
        "ProcessGuardZombieDetected",
        "ProcessGuardOrphanReaped",
        "KillSwitchEngaged",
        "BudgetGuardTriggered",
        "RuntimeFuseTriggeredCritical",
        "RuntimeFuseTriggeredWarning",
        "ReleaseRollbackTriggered",
        "ReleaseRollbackFailed",
    }

    def __init__(self, *, incident_file: Path, include_warning: bool = True) -> None:
        self.incident_file = Path(incident_file)
        self.include_warning = bool(include_warning)
        self._lock = threading.Lock()

    def handle(self, event: Dict[str, Any]) -> Dict[str, Any]:
        payload = _safe_dict(event)
        event_type = str(payload.get("event_type") or "")
        severity = str(payload.get("severity") or "info").strip().lower() or "info"

        should_record = (
            event_type in self._INCIDENT_EVENT_TYPES
            or severity == "critical"
            or (self.include_warning and severity in {"warn", "warning"})
        )
        if not should_record:
            return {"ok": True, "recorded": False}

        data = _safe_dict(payload.get("data"))
        row = {
            "generated_at": _utc_iso_now(),
            "event_id": str(payload.get("event_id") or ""),
            "event_type": event_type,
            "topic": str(payload.get("topic") or ""),
            "severity": severity,
            "timestamp": str(payload.get("timestamp") or ""),
            "reason_code": str(data.get("reason_code") or ""),
            "reason_text": str(data.get("reason_text") or ""),
            "workflow_id": str(data.get("workflow_id") or payload.get("workflow_id") or ""),
            "task_id": str(data.get("task_id") or ""),
        }
        with self._lock:
            _append_jsonl(self.incident_file, row)
        return {"ok": True, "recorded": True}


class ReleaseGateConsumer:
    """Tracks release-gate decision counters from bus events."""

    def __init__(self, *, state_file: Path) -> None:
        self.state_file = Path(state_file)
        self._lock = threading.Lock()

    def handle(self, event: Dict[str, Any]) -> Dict[str, Any]:
        payload = _safe_dict(event)
        event_type = str(payload.get("event_type") or "")

        with self._lock:
            state = _read_json(self.state_file)
            counters = _safe_dict(state.get("counters"))
            counters["task_approved"] = int(counters.get("task_approved") or 0) + (
                1 if event_type == "TaskApproved" else 0
            )
            counters["task_rejected"] = int(counters.get("task_rejected") or 0) + (
                1 if event_type == "TaskRejected" else 0
            )
            counters["release_gate_rejected"] = int(counters.get("release_gate_rejected") or 0) + (
                1 if event_type == "ReleaseGateRejected" else 0
            )

            snapshot = {
                "generated_at": _utc_iso_now(),
                "last_event_type": event_type,
                "counters": counters,
                "state_file": _to_unix(self.state_file),
            }
            _write_json(self.state_file, snapshot)
        return {"ok": True}


def register_default_consumers(
    *,
    event_store: EventStore,
    repo_root: Path,
    include_warning_incidents: bool = True,
) -> EventConsumerHooks:
    root = Path(repo_root).resolve()
    posture_state_file = root / "scratch" / "runtime" / "event_bus_runtime_posture_ws28_029.json"
    incident_file = root / "scratch" / "runtime" / "event_bus_incidents_ws28_029.jsonl"
    release_gate_file = root / "scratch" / "runtime" / "event_bus_release_gate_ws28_029.json"

    posture = RuntimePostureConsumer(state_file=posture_state_file)
    incident = IncidentConsumer(incident_file=incident_file, include_warning=include_warning_incidents)
    release = ReleaseGateConsumer(state_file=release_gate_file)

    posture_sub = event_store.subscribe("*", posture.handle, timeout_ms=3_000, max_retries=1)
    incident_sub = event_store.subscribe("*", incident.handle, timeout_ms=3_000, max_retries=1)
    release_sub = event_store.subscribe("agent.*", release.handle, timeout_ms=3_000, max_retries=1)

    return EventConsumerHooks(
        posture_subscription=posture_sub,
        incident_subscription=incident_sub,
        release_subscription=release_sub,
        posture_state_file=_to_unix(posture_state_file),
        incident_file=_to_unix(incident_file),
        release_gate_file=_to_unix(release_gate_file),
    )


__all__ = [
    "EventConsumerHooks",
    "IncidentConsumer",
    "ReleaseGateConsumer",
    "RuntimePostureConsumer",
    "register_default_consumers",
]

