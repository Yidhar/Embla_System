from __future__ import annotations

from pathlib import Path

from core.event_bus.event_store import EventStore
from core.event_bus.topic_bus import resolve_topic_db_path_from_mirror


def test_event_store_uses_db_primary_without_jsonl_mirror(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("NAGA_EVENT_BUS_JSONL_MIRROR", raising=False)
    event_file = tmp_path / "logs" / "autonomous" / "events.jsonl"
    store = EventStore(event_file)

    store.emit("TaskExecutionCompleted", {"task_id": "task-1", "success": True}, source="unit-test")

    event_db = resolve_topic_db_path_from_mirror(event_file)
    assert event_db.exists()
    assert not event_file.exists()

    rows = store.read_recent(limit=10)
    assert rows
    assert rows[-1]["event_type"] == "TaskExecutionCompleted"


def test_event_store_exposes_time_partitions(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("NAGA_EVENT_BUS_JSONL_MIRROR", raising=False)
    event_file = tmp_path / "logs" / "autonomous" / "events.jsonl"
    store = EventStore(event_file)

    store.topic_bus.publish(
        "agent.task.execution",
        {"task_id": "jan"},
        event_type="TaskExecutionCompleted",
        timestamp="2026-01-15T10:00:00+00:00",
    )
    store.topic_bus.publish(
        "agent.task.execution",
        {"task_id": "feb"},
        event_type="TaskExecutionCompleted",
        timestamp="2026-02-15T10:00:00+00:00",
    )

    partitions = store.list_time_partitions(limit=12)
    assert "202601" in partitions
    assert "202602" in partitions
