from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from autonomous.event_log import EventStore, TopicEventBus, infer_event_topic


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_topic_event_bus_publish_subscribe_and_persistence_ws25_001() -> None:
    case_root = _make_case_root("test_topic_event_bus_ws25_001")
    try:
        event_log = case_root / "events.jsonl"
        bus_db = case_root / "event_bus.db"
        bus = TopicEventBus(db_path=bus_db, mirror_file_path=event_log)

        received: list[dict] = []
        sub = bus.subscribe("agent.*", lambda event: received.append(dict(event)))
        try:
            event_id = bus.publish(
                "agent.workflow.state",
                {"workflow_id": "wf-001", "trace_id": "trace-001", "step": "approved"},
                event_type="TaskApproved",
                source="unit-test",
            )
        finally:
            bus.unsubscribe(sub)

        assert event_id
        assert len(received) == 1
        assert received[0]["event_type"] == "TaskApproved"
        assert received[0]["topic"] == "agent.workflow.state"
        assert event_log.exists()

        replay_rows = bus.replay(topic_pattern="agent.*", limit=10)
        assert len(replay_rows) == 1
        assert replay_rows[0]["event_id"] == event_id

        reloaded = TopicEventBus(db_path=bus_db, mirror_file_path=event_log)
        replay_rows_reloaded = reloaded.replay(topic_pattern="agent.*", limit=10)
        assert len(replay_rows_reloaded) == 1
        assert replay_rows_reloaded[0]["event_id"] == event_id
    finally:
        _cleanup_case_root(case_root)


def test_topic_event_bus_records_dead_letter_on_subscriber_error_ws25_001() -> None:
    case_root = _make_case_root("test_topic_event_bus_ws25_001")
    try:
        bus = TopicEventBus(db_path=case_root / "event_bus.db", mirror_file_path=case_root / "events.jsonl")

        def _raise_error(_event: dict) -> None:
            raise RuntimeError("subscriber boom")

        sub = bus.subscribe("system.*", _raise_error)
        try:
            bus.publish(
                "system.cpu.overload",
                {"usage": 95.0, "trace_id": "trace-overload"},
                event_type="WatchdogThresholdExceeded",
                source="unit-test",
            )
        finally:
            bus.unsubscribe(sub)

        dead_letters = bus.get_dead_letters(limit=10)
        assert len(dead_letters) == 1
        assert dead_letters[0]["topic"] == "system.cpu.overload"
        assert "subscriber boom" in dead_letters[0]["error"]
        assert bus.retry_dead_letter(dead_letters[0]["event_id"]) is True
    finally:
        _cleanup_case_root(case_root)


def test_event_store_exposes_topic_replay_and_subscription_ws25_001() -> None:
    case_root = _make_case_root("test_topic_event_bus_ws25_001")
    try:
        store = EventStore(file_path=case_root / "events.jsonl")
        seen_event_types: list[str] = []
        sub = store.subscribe("tool.*", lambda event: seen_event_types.append(str(event.get("event_type") or "")))
        try:
            store.emit(
                "CliExecutionCompleted",
                {"workflow_id": "wf-tool", "trace_id": "trace-tool", "tool_name": "native_executor"},
            )
            store.emit(
                "WatchdogThresholdExceeded",
                {"workflow_id": "wf-system", "trace_id": "trace-system", "cpu_percent": 95.0},
            )
        finally:
            store.unsubscribe(sub)

        assert "CliExecutionCompleted" in seen_event_types
        tool_rows = store.replay_by_topic(topic_pattern="tool.*", limit=20)
        assert len(tool_rows) >= 1
        assert any(str(item.get("event_type") or "") == "CliExecutionCompleted" for item in tool_rows)

        topics = store.list_topics(limit=20)
        assert any(topic.startswith("tool.") for topic in topics)
        assert infer_event_topic("WatchdogThresholdExceeded", {}) == "system.watchdog.threshold.exceeded"
    finally:
        _cleanup_case_root(case_root)
