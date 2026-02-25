"""WS23-005 workflow outbox to brainstem event bridge helpers."""

from __future__ import annotations

from typing import Any, Dict

BRIDGED_EVENT_TYPE = "BrainstemEventBridged"


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def build_brainstem_bridge_payload(event: Dict[str, Any], *, consumer: str) -> Dict[str, Any]:
    """Normalize outbox event row into a stable bridge payload."""

    row = _as_dict(event)
    payload = _as_dict(row.get("payload"))
    envelope = _as_dict(row.get("event_envelope"))
    envelope_data = _as_dict(envelope.get("data"))

    outbox_id = _as_int(row.get("outbox_id"), default=0)
    workflow_id = (
        _as_str(row.get("workflow_id")) or _as_str(payload.get("workflow_id")) or _as_str(envelope.get("workflow_id"))
    )
    event_type = _as_str(row.get("event_type")) or _as_str(envelope.get("event_type"))
    trace_id = (
        _as_str(row.get("trace_id"))
        or _as_str(envelope.get("trace_id"))
        or _as_str(payload.get("trace_id"))
        or _as_str(envelope_data.get("trace_id"))
    )
    session_id = _as_str(payload.get("session_id")) or _as_str(envelope_data.get("session_id"))
    task_id = _as_str(payload.get("task_id")) or _as_str(envelope_data.get("task_id"))

    bridge_payload: Dict[str, Any] = {
        "outbox_id": outbox_id,
        "consumer": _as_str(consumer),
        "workflow_id": workflow_id,
        "event_type": event_type,
        "task_id": task_id,
        "trace_id": trace_id,
        "session_id": session_id,
        "dispatch_attempts": _as_int(row.get("dispatch_attempts"), default=0),
        "max_attempts": max(1, _as_int(row.get("max_attempts"), default=1)),
        "schema_version": _as_str(row.get("schema_version")) or _as_str(envelope.get("schema_version")),
        "source": _as_str(row.get("source")) or _as_str(envelope.get("source")),
        "severity": _as_str(row.get("severity")) or _as_str(envelope.get("severity")),
        "event_id": _as_str(envelope.get("event_id")),
        "idempotency_key": _as_str(envelope.get("idempotency_key")),
        "event_timestamp": _as_str(envelope.get("timestamp")) or _as_str(row.get("created_at")),
        "event_payload": payload,
        "event_envelope": envelope,
    }

    return bridge_payload


__all__ = ["BRIDGED_EVENT_TYPE", "build_brainstem_bridge_payload"]

