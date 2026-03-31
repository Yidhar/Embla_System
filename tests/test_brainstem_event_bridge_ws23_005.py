from __future__ import annotations

from system.brainstem_event_bridge import build_brainstem_bridge_payload


def test_build_brainstem_bridge_payload_includes_outbox_and_envelope_metadata() -> None:
    event = {
        "outbox_id": 42,
        "workflow_id": "wf-42",
        "event_type": "TaskApproved",
        "trace_id": "trace-42",
        "source": "autonomous.workflow_store",
        "severity": "info",
        "schema_version": "ws18-001-v1",
        "dispatch_attempts": 1,
        "max_attempts": 5,
        "payload": {
            "task_id": "task-42",
            "session_id": "sess-42",
            "workflow_id": "wf-42",
            "trace_id": "trace-42",
        },
        "event_envelope": {
            "event_id": "evt_42",
            "schema_version": "ws18-001-v1",
            "timestamp": "2026-02-25T10:00:00+00:00",
            "event_type": "TaskApproved",
            "source": "autonomous.workflow_store",
            "severity": "info",
            "idempotency_key": "TaskApproved:abc42",
            "trace_id": "trace-42",
            "data": {
                "workflow_id": "wf-42",
                "task_id": "task-42",
                "session_id": "sess-42",
                "trace_id": "trace-42",
            },
        },
    }

    payload = build_brainstem_bridge_payload(event, consumer="release-controller")

    assert payload["outbox_id"] == 42
    assert payload["consumer"] == "release-controller"
    assert payload["workflow_id"] == "wf-42"
    assert payload["event_type"] == "TaskApproved"
    assert payload["task_id"] == "task-42"
    assert payload["trace_id"] == "trace-42"
    assert payload["session_id"] == "sess-42"
    assert payload["schema_version"] == "ws18-001-v1"
    assert payload["source"] == "autonomous.workflow_store"
    assert payload["severity"] == "info"
    assert payload["event_id"] == "evt_42"
    assert payload["idempotency_key"] == "TaskApproved:abc42"
    assert payload["event_timestamp"] == "2026-02-25T10:00:00+00:00"
    assert payload["dispatch_attempts"] == 1
    assert payload["max_attempts"] == 5


def test_build_brainstem_bridge_payload_uses_payload_fallback_fields() -> None:
    payload = build_brainstem_bridge_payload(
        {
            "outbox_id": "7",
            "payload": {
                "workflow_id": "wf-7",
                "task_id": "task-7",
                "session_id": "sess-7",
                "trace_id": "trace-7",
            },
            "event_envelope": {
                "event_type": "ChangePromoted",
                "timestamp": "2026-02-25T12:00:00+00:00",
                "data": {
                    "workflow_id": "wf-7",
                    "task_id": "task-7",
                },
            },
        },
        consumer="release-controller",
    )

    assert payload["outbox_id"] == 7
    assert payload["workflow_id"] == "wf-7"
    assert payload["event_type"] == "ChangePromoted"
    assert payload["task_id"] == "task-7"
    assert payload["trace_id"] == "trace-7"
    assert payload["session_id"] == "sess-7"
    assert payload["max_attempts"] == 1

