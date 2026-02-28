from __future__ import annotations

import json
from pathlib import Path

from core.event_bus.consumers import register_default_consumers
from core.event_bus.event_store import EventStore


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        rows.append(json.loads(text))
    return rows


def test_event_bus_default_consumers_emit_posture_incident_and_release_views(tmp_path: Path) -> None:
    event_path = tmp_path / "logs" / "autonomous" / "events.jsonl"
    event_store = EventStore(event_path)
    hooks = register_default_consumers(event_store=event_store, repo_root=tmp_path, include_warning_incidents=True)

    event_store.emit(
        "TaskApproved",
        {"workflow_id": "wf-001", "task_id": "task-001"},
        source="unit.test",
        severity="info",
    )
    event_store.emit(
        "ReleaseGateRejected",
        {
            "workflow_id": "wf-001",
            "task_id": "task-001",
            "reason_code": "WATCHDOG_FUSE_PAUSE_DISPATCH_AND_ESCALATE",
            "reason_text": "watchdog fuse blocked dispatch",
        },
        source="unit.test",
        severity="critical",
    )

    posture_path = Path(hooks.posture_state_file)
    incident_path = Path(hooks.incident_file)
    release_gate_path = Path(hooks.release_gate_file)
    assert posture_path.exists() is True
    assert incident_path.exists() is True
    assert release_gate_path.exists() is True

    posture_payload = _read_json(posture_path)
    assert int(posture_payload["total_events"]) >= 2
    assert int(posture_payload["event_type_counts"]["TaskApproved"]) >= 1
    assert int(posture_payload["event_type_counts"]["ReleaseGateRejected"]) >= 1

    incidents = _read_jsonl(incident_path)
    assert any(str(item.get("event_type")) == "ReleaseGateRejected" for item in incidents)
    assert any(str(item.get("severity")) == "critical" for item in incidents)

    release_gate_payload = _read_json(release_gate_path)
    counters = release_gate_payload["counters"]
    assert int(counters["task_approved"]) >= 1
    assert int(counters["release_gate_rejected"]) >= 1
