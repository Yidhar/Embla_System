from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from autonomous.event_log import EventStore, TopicEventBus


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_replay_dispatch_anchor_dedupe_prevents_duplicate_side_effects_ws25_003() -> None:
    case_root = _make_case_root("test_topic_event_bus_replay_idempotency_ws25_003")
    try:
        bus = TopicEventBus(
            db_path=case_root / "event_bus.db",
            mirror_file_path=case_root / "events.jsonl",
        )
        bus.publish(
            "agent.workflow.state",
            {"workflow_id": "wf-idem", "trace_id": "trace-idem", "step": "approved"},
            event_type="TaskApproved",
            source="unit-test",
            idempotency_key="idem:task-approved",
        )

        side_effects: list[str] = []
        sub = bus.subscribe("agent.*", lambda event: side_effects.append(str(event.get("event_id") or "")))
        try:
            first = bus.replay_dispatch(
                anchor_id="consumer-agent-a",
                topic_pattern="agent.*",
                from_seq=1,
                limit=20,
            )
            second = bus.replay_dispatch(
                anchor_id="consumer-agent-a",
                topic_pattern="agent.*",
                from_seq=1,
                limit=20,
            )
        finally:
            bus.unsubscribe(sub)

        assert first.scanned_count == 1
        assert first.dispatched_count == 1
        assert first.failed_count == 0
        assert second.scanned_count == 1
        assert second.dispatched_count == 0
        assert second.deduped_count == 1
        assert side_effects and len(side_effects) == 1
    finally:
        _cleanup_case_root(case_root)


def test_replay_dispatch_rewinds_anchor_when_delivery_fails_ws25_003() -> None:
    case_root = _make_case_root("test_topic_event_bus_replay_idempotency_ws25_003")
    try:
        bus = TopicEventBus(
            db_path=case_root / "event_bus.db",
            mirror_file_path=case_root / "events.jsonl",
        )
        bus.publish(
            "agent.workflow.execution",
            {"workflow_id": "wf-flaky", "trace_id": "trace-flaky"},
            event_type="TaskExecutionCompleted",
            source="unit-test",
            idempotency_key="idem:task-exec",
        )

        state = {"attempts": 0}
        side_effects: list[str] = []

        def flaky_handler(event: dict) -> None:
            state["attempts"] += 1
            if state["attempts"] == 1:
                raise RuntimeError("simulated replay delivery failure")
            side_effects.append(str(event.get("event_id") or ""))

        sub = bus.subscribe("agent.*", flaky_handler, max_retries=1)
        try:
            first = bus.replay_dispatch(
                anchor_id="consumer-tool-b",
                topic_pattern="agent.*",
                from_seq=1,
                limit=20,
            )
            anchor_after_first = bus.get_replay_anchor("consumer-tool-b")
            second = bus.replay_dispatch(
                anchor_id="consumer-tool-b",
                topic_pattern="agent.*",
                limit=20,
            )
        finally:
            bus.unsubscribe(sub)

        assert first.failed_count == 1
        assert first.dispatched_count == 0
        assert anchor_after_first["last_seq"] == 0
        assert second.failed_count == 0
        assert second.dispatched_count == 1
        assert side_effects and len(side_effects) == 1
    finally:
        _cleanup_case_root(case_root)


def test_event_store_replay_dispatch_anchor_wrappers_ws25_003() -> None:
    case_root = _make_case_root("test_topic_event_bus_replay_idempotency_ws25_003")
    try:
        store = EventStore(file_path=case_root / "events.jsonl")
        store.emit(
            "TaskExecutionCompleted",
            {"workflow_id": "wf-store", "trace_id": "trace-store", "runtime_mode": "subagent", "success": True},
        )

        side_effects: list[str] = []
        sub = store.subscribe("agent.*", lambda event: side_effects.append(str(event.get("event_id") or "")))
        try:
            first = store.replay_dispatch(
                anchor_id="store-consumer",
                topic_pattern="agent.*",
                from_seq=1,
                limit=20,
            )
            second = store.replay_dispatch(
                anchor_id="store-consumer",
                topic_pattern="agent.*",
                from_seq=1,
                limit=20,
            )
            anchor = store.get_replay_anchor("store-consumer")
            reset = store.reset_replay_anchor("store-consumer", last_seq=0, clear_dedupe=True)
            third = store.replay_dispatch(
                anchor_id="store-consumer",
                topic_pattern="agent.*",
                limit=20,
            )
        finally:
            store.unsubscribe(sub)

        assert first.dispatched_count == 1
        assert second.dispatched_count == 0
        assert second.deduped_count == 1
        assert anchor["last_seq"] >= 1
        assert reset["last_seq"] == 0
        assert third.dispatched_count == 1
        assert len(side_effects) == 2
    finally:
        _cleanup_case_root(case_root)
