from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from autonomous.event_log import EVENT_SCHEMA_VERSION, EventStore


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_event_store_emit_includes_ws18_envelope() -> None:
    case_root = _make_case_root("test_event_store_ws18_001")
    try:
        store = EventStore(file_path=case_root / "events.jsonl")
        store.emit("TaskApproved", {"workflow_id": "wf-001", "trace_id": "trace-001", "result": "ok"})

        rows = store.read_recent(limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert row["schema_version"] == EVENT_SCHEMA_VERSION
        assert row["event_type"] == "TaskApproved"
        assert row["source"]
        assert row["severity"] in {"info", "warn", "error", "critical"}
        assert row["idempotency_key"]
        assert row["payload"]["workflow_id"] == "wf-001"
        assert row["data"]["trace_id"] == "trace-001"
    finally:
        _cleanup_case_root(case_root)


def test_event_store_replay_filters_by_event_and_trace() -> None:
    case_root = _make_case_root("test_event_store_ws18_001")
    try:
        store = EventStore(file_path=case_root / "events.jsonl")
        store.emit("TaskApproved", {"workflow_id": "wf-a", "trace_id": "trace-a", "ok": True})
        store.emit("TaskApproved", {"workflow_id": "wf-b", "trace_id": "trace-b", "ok": True})
        store.emit("TaskRejected", {"workflow_id": "wf-a", "trace_id": "trace-a", "ok": False})

        replay = store.replay(limit=20, event_type="TaskApproved", trace_id="trace-a")
        assert len(replay) == 1
        assert replay[0]["event_type"] == "TaskApproved"
        assert replay[0]["data"]["workflow_id"] == "wf-a"
    finally:
        _cleanup_case_root(case_root)


def test_event_store_read_recent_normalizes_legacy_rows() -> None:
    case_root = _make_case_root("test_event_store_ws18_001")
    try:
        file_path = case_root / "legacy_events.jsonl"
        legacy_row = {
            "timestamp": "2026-02-24T00:00:00+00:00",
            "event_type": "LegacyEvent",
            "payload": {"workflow_id": "wf-legacy", "step": "x"},
        }
        file_path.write_text(json.dumps(legacy_row, ensure_ascii=False) + "\n", encoding="utf-8")

        store = EventStore(file_path=file_path)
        rows = store.read_recent(limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert row["schema_version"] == EVENT_SCHEMA_VERSION
        assert row["event_type"] == "LegacyEvent"
        assert row["payload"]["workflow_id"] == "wf-legacy"
    finally:
        _cleanup_case_root(case_root)
