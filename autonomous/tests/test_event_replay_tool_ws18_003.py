from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest

from autonomous.event_log.event_schema import build_event_envelope
from autonomous.event_log.event_store import EventStore
from autonomous.event_log.replay_tool import EventReplayTool, ReplayRequest


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _write_event_rows(path: Path) -> None:
    rows = [
        build_event_envelope(
            "TaskApproved",
            {"workflow_id": "wf-001", "trace_id": "trace-001", "step": "a"},
            timestamp="2026-02-24T00:00:01+00:00",
        ),
        build_event_envelope(
            "OutboxDispatched",
            {"workflow_id": "wf-001", "trace_id": "trace-001", "step": "b"},
            timestamp="2026-02-24T00:00:02+00:00",
        ),
        build_event_envelope(
            "TaskApproved",
            {"workflow_id": "wf-002", "trace_id": "trace-002", "step": "c"},
            timestamp="2026-02-24T00:10:00+00:00",
        ),
    ]
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            payload = {**row, "payload": row["data"]}
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def test_replay_tool_filters_by_trace_and_window_and_writes_audit() -> None:
    case_root = _make_case_root("test_event_replay_tool_ws18_003")
    try:
        event_log = case_root / "events.jsonl"
        audit_log = case_root / "replay_audit.jsonl"
        _write_event_rows(event_log)

        store = EventStore(file_path=event_log)
        tool = EventReplayTool(event_store=store, audit_file=audit_log)
        result = tool.replay(
            ReplayRequest(
                trace_id="trace-001",
                start_time="2026-02-24T00:00:00+00:00",
                end_time="2026-02-24T00:00:03+00:00",
                operator="unit-test",
                reason="drill",
            )
        )

        assert len(result.matched_events) == 2
        assert all((event.get("trace_id") or event.get("data", {}).get("trace_id")) == "trace-001" for event in result.matched_events)
        assert len(result.recovery_plan) == 1
        assert result.recovery_plan[0]["workflow_id"] == "wf-001"
        assert "TaskApproved" in result.recovery_plan[0]["event_types"]
        assert "OutboxDispatched" in result.recovery_plan[0]["event_types"]

        audits = [json.loads(line) for line in audit_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(audits) == 1
        assert audits[0]["matched_count"] == 2
        assert audits[0]["request"]["operator"] == "unit-test"
    finally:
        _cleanup_case_root(case_root)


def test_replay_tool_requires_at_least_one_filter() -> None:
    case_root = _make_case_root("test_event_replay_tool_ws18_003")
    try:
        event_log = case_root / "events.jsonl"
        audit_log = case_root / "replay_audit.jsonl"
        _write_event_rows(event_log)

        store = EventStore(file_path=event_log)
        tool = EventReplayTool(event_store=store, audit_file=audit_log)
        with pytest.raises(ValueError):
            tool.replay(ReplayRequest())
    finally:
        _cleanup_case_root(case_root)
