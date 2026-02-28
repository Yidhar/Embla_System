"""WS18-001 event schema helpers for Event Bus records."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

EVENT_SCHEMA_VERSION = "ws18-001-v1"
DEFAULT_EVENT_SOURCE = "autonomous.event_bus"
_SEVERITY_LEVELS = {"info", "warn", "error", "critical"}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_hash(parts: Dict[str, Any]) -> str:
    normalized = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _infer_severity(event_type: str, data: Dict[str, Any]) -> str:
    if isinstance(data.get("severity"), str) and data["severity"] in _SEVERITY_LEVELS:
        return data["severity"]

    lowered = str(event_type or "").lower()
    if any(token in lowered for token in ("critical", "panic")):
        return "critical"
    if any(token in lowered for token in ("error", "failed", "rollback", "killed")):
        return "error"
    if any(token in lowered for token in ("warn", "degraded", "retry")):
        return "warn"
    return "info"


def _build_idempotency_key(event_type: str, data: Dict[str, Any], timestamp: str) -> str:
    material = {
        "event_type": event_type,
        "workflow_id": data.get("workflow_id"),
        "task_id": data.get("task_id"),
        "trace_id": data.get("trace_id"),
        "timestamp": timestamp,
    }
    return f"{event_type}:{_stable_hash(material)[:16]}"


def is_event_envelope(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("event_type")) and "data" in payload and bool(payload.get("schema_version"))


def build_event_envelope(
    event_type: str,
    data: Dict[str, Any] | None = None,
    *,
    source: str | None = None,
    severity: str | None = None,
    idempotency_key: str | None = None,
    timestamp: str | None = None,
    event_id: str | None = None,
    schema_version: str = EVENT_SCHEMA_VERSION,
) -> Dict[str, Any]:
    payload = dict(data or {})
    ts = str(timestamp or payload.get("timestamp") or _utc_iso())
    source_value = str(source or payload.get("source") or DEFAULT_EVENT_SOURCE)
    severity_value = severity if severity in _SEVERITY_LEVELS else _infer_severity(event_type, payload)
    idem = str(idempotency_key or payload.get("idempotency_key") or _build_idempotency_key(event_type, payload, ts))

    envelope: Dict[str, Any] = {
        "event_id": str(event_id or payload.get("event_id") or f"evt_{uuid.uuid4().hex[:24]}"),
        "schema_version": str(schema_version or payload.get("schema_version") or EVENT_SCHEMA_VERSION),
        "timestamp": ts,
        "event_type": event_type,
        "source": source_value,
        "severity": severity_value,
        "idempotency_key": idem,
        "data": payload,
    }
    if "workflow_id" in payload and "workflow_id" not in envelope:
        envelope["workflow_id"] = payload.get("workflow_id")
    if "trace_id" in payload and "trace_id" not in envelope:
        envelope["trace_id"] = payload.get("trace_id")
    return envelope


def normalize_event_envelope(
    record: Dict[str, Any],
    *,
    fallback_event_type: str = "",
    fallback_timestamp: str = "",
) -> Dict[str, Any]:
    if is_event_envelope(record):
        raw_data = record.get("data")
        data = dict(raw_data) if isinstance(raw_data, dict) else {"raw": raw_data}
        event_type = str(record.get("event_type") or fallback_event_type or "UnknownEvent")
        timestamp = str(record.get("timestamp") or fallback_timestamp or _utc_iso())
        source = str(record.get("source") or DEFAULT_EVENT_SOURCE)
        severity = str(record.get("severity") or _infer_severity(event_type, data))
        if severity not in _SEVERITY_LEVELS:
            severity = _infer_severity(event_type, data)
        idempotency_key = str(record.get("idempotency_key") or _build_idempotency_key(event_type, data, timestamp))
        envelope = {
            "event_id": str(record.get("event_id") or f"evt_{_stable_hash({'event_type': event_type, 'timestamp': timestamp, 'data': data})[:24]}"),
            "schema_version": str(record.get("schema_version") or EVENT_SCHEMA_VERSION),
            "timestamp": timestamp,
            "event_type": event_type,
            "source": source,
            "severity": severity,
            "idempotency_key": idempotency_key,
            "data": data,
        }
        workflow_id = record.get("workflow_id") or data.get("workflow_id")
        if workflow_id is not None:
            envelope["workflow_id"] = workflow_id
        trace_id = record.get("trace_id") or data.get("trace_id")
        if trace_id is not None:
            envelope["trace_id"] = trace_id
        return envelope

    payload = record.get("payload")
    if isinstance(payload, dict):
        data = dict(payload)
    else:
        data = {}
    event_type = str(record.get("event_type") or fallback_event_type or "UnknownEvent")
    timestamp = str(record.get("timestamp") or record.get("created_at") or fallback_timestamp or _utc_iso())
    return build_event_envelope(
        event_type,
        data,
        source=str(record.get("source") or DEFAULT_EVENT_SOURCE),
        severity=str(record.get("severity") or _infer_severity(event_type, data)),
        idempotency_key=str(record.get("idempotency_key") or _build_idempotency_key(event_type, data, timestamp)),
        timestamp=timestamp,
        event_id=str(record.get("event_id") or f"evt_{_stable_hash({'event_type': event_type, 'timestamp': timestamp, 'data': data})[:24]}"),
    )
