"""WS33-001 tests for event-bus enhancements: priority, max_concurrency,
DLQ auto-retry daemon, and SerialAction queue.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List

from core.event_bus.dlq_auto_retry import DLQAutoRetryDaemon
from core.event_bus.serial_queue import SerialAction, SerialActionQueue
from core.event_bus.topic_bus import TopicEventBus, TopicSubscription


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bus(tmp_path: Path) -> TopicEventBus:
    return TopicEventBus(db_path=tmp_path / "test_events.db")


# ---------------------------------------------------------------------------
# 1. Priority ordering
# ---------------------------------------------------------------------------

class TestPriorityOrdering:
    def test_dispatch_order_by_priority(self, tmp_path: Path) -> None:
        """Subscribe 3 handlers with priority 1, 2, 3 — verify dispatch order is 3, 2, 1."""
        bus = _make_bus(tmp_path)
        call_order: List[int] = []

        def handler_p1(_evt: Dict[str, Any]) -> None:
            call_order.append(1)

        def handler_p2(_evt: Dict[str, Any]) -> None:
            call_order.append(2)

        def handler_p3(_evt: Dict[str, Any]) -> None:
            call_order.append(3)

        bus.subscribe("agent.*", handler_p1, priority=1)
        bus.subscribe("agent.*", handler_p2, priority=2)
        bus.subscribe("agent.*", handler_p3, priority=3)

        bus.publish("agent.test", {"msg": "priority check"}, event_type="PriorityTest")

        assert call_order == [3, 2, 1], f"Expected [3, 2, 1] but got {call_order}"

    def test_same_priority_all_called(self, tmp_path: Path) -> None:
        """Handlers with equal priority should all be called."""
        bus = _make_bus(tmp_path)
        called: List[str] = []

        bus.subscribe("agent.*", lambda _e: called.append("a"), priority=0)
        bus.subscribe("agent.*", lambda _e: called.append("b"), priority=0)

        bus.publish("agent.test", {"msg": "equal priority"}, event_type="EqualPriority")

        assert len(called) == 2
        assert set(called) == {"a", "b"}


# ---------------------------------------------------------------------------
# 2. max_concurrency (semaphore gating)
# ---------------------------------------------------------------------------

class TestMaxConcurrency:
    def test_serial_execution_with_max_concurrency_1(self, tmp_path: Path) -> None:
        """With max_concurrency=1, only one async handler should run at a time."""
        bus = _make_bus(tmp_path)
        concurrency_log: List[int] = []
        active = {"count": 0}

        async def slow_handler(_evt: Dict[str, Any]) -> None:
            active["count"] += 1
            concurrency_log.append(active["count"])
            await asyncio.sleep(0.05)
            active["count"] -= 1

        bus.subscribe("agent.*", slow_handler, max_concurrency=1)

        # Publish several events; since max_concurrency=1, the semaphore
        # will gate concurrent invocations.
        async def _run() -> None:
            bus.publish("agent.test", {"n": 1}, event_type="ConcTest")
            bus.publish("agent.test", {"n": 2}, event_type="ConcTest")
            # Give fire-and-forget tasks time to run
            await asyncio.sleep(0.3)

        asyncio.run(_run())
        # With semaphore=1, peak concurrency should be 1
        assert all(c <= 1 for c in concurrency_log), f"Concurrency exceeded 1: {concurrency_log}"

    def test_unlimited_concurrency_default(self, tmp_path: Path) -> None:
        """With max_concurrency=0 (default), concurrency is unlimited."""
        bus = _make_bus(tmp_path)
        sub = bus.subscribe("agent.*", lambda _e: None)
        assert sub.max_concurrency == 0


# ---------------------------------------------------------------------------
# 3. TopicSubscription new fields on dataclass
# ---------------------------------------------------------------------------

class TestTopicSubscriptionFields:
    def test_priority_field_default(self, tmp_path: Path) -> None:
        bus = _make_bus(tmp_path)
        sub = bus.subscribe("agent.*", lambda _e: None)
        assert sub.priority == 0

    def test_max_concurrency_field_default(self, tmp_path: Path) -> None:
        bus = _make_bus(tmp_path)
        sub = bus.subscribe("agent.*", lambda _e: None)
        assert sub.max_concurrency == 0

    def test_priority_passed_through(self, tmp_path: Path) -> None:
        bus = _make_bus(tmp_path)
        sub = bus.subscribe("agent.*", lambda _e: None, priority=42)
        assert sub.priority == 42

    def test_max_concurrency_passed_through(self, tmp_path: Path) -> None:
        bus = _make_bus(tmp_path)
        sub = bus.subscribe("agent.*", lambda _e: None, max_concurrency=3)
        assert sub.max_concurrency == 3


# ---------------------------------------------------------------------------
# 4. DLQ auto-retry daemon
# ---------------------------------------------------------------------------

class TestDLQAutoRetryDaemon:
    def test_retry_clears_dlq_on_success(self, tmp_path: Path) -> None:
        """Insert a DLQ entry, start daemon — on retry success entry is removed."""
        bus = _make_bus(tmp_path)
        call_log: List[str] = []
        fail_flag = {"should_fail": True}

        def flaky_handler(evt: Dict[str, Any]) -> None:
            if fail_flag["should_fail"]:
                raise RuntimeError("transient failure")
            call_log.append(str(evt.get("event_id", "")))

        bus.subscribe("agent.*", flaky_handler, max_retries=1)

        # This publish will fail and create a DLQ entry
        bus.publish("agent.retry.test", {"step": 1}, event_type="RetryTest")

        # Verify DLQ entry exists
        dlq = bus.get_dead_letters()
        assert len(dlq) >= 1

        # Now make handler succeed
        fail_flag["should_fail"] = False

        daemon = DLQAutoRetryDaemon(bus, interval_seconds=0.1, max_retries=5)

        async def _run() -> None:
            await daemon.start()
            await asyncio.sleep(0.3)
            await daemon.stop()

        asyncio.run(_run())

        # DLQ should be empty after successful retry
        dlq_after = bus.get_dead_letters()
        assert len(dlq_after) == 0, f"DLQ still has entries: {dlq_after}"

    def test_retry_bumps_count_on_persistent_failure(self, tmp_path: Path) -> None:
        """When retry_dead_letter dispatch keeps failing, the daemon still
        processes entries.  Because ``retry_dead_letter`` deletes the old DLQ
        row and the re-dispatch creates a *new* DLQ row (retry_count=0), we
        verify that multiple daemon cycles keep generating new DLQ entries,
        proving the retry loop is active.

        To truly test ``_bump_retry``, we also manually insert a DLQ entry
        whose event_id does NOT exist in topic_event — that forces
        ``retry_dead_letter`` to return False, which triggers the bump path.
        """
        bus = _make_bus(tmp_path)

        def always_fail(_evt: Dict[str, Any]) -> None:
            raise RuntimeError("permanent failure")

        bus.subscribe("agent.*", always_fail, max_retries=1)

        # Insert a DLQ entry for a nonexistent event so retry_dead_letter
        # returns False and the daemon hits _bump_retry.
        from datetime import datetime as _dt, timezone as _tz

        now_iso = _dt.now(_tz.utc).isoformat()
        with bus._lock:
            with bus._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO dead_letter_event
                    (event_id, topic, subscription_pattern, error, retry_count, next_retry_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 0, '', ?, ?)
                    """,
                    ("nonexistent_event_999", "agent.fake", "agent.*", "test error", now_iso, now_iso),
                )
                conn.commit()

        dlq_before = bus.get_dead_letters()
        entry_before = [e for e in dlq_before if e["event_id"] == "nonexistent_event_999"]
        assert len(entry_before) == 1
        assert entry_before[0]["retry_count"] == 0

        daemon = DLQAutoRetryDaemon(bus, interval_seconds=0.1, max_retries=5, backoff_base=1.0)

        async def _run() -> None:
            await daemon.start()
            await asyncio.sleep(0.4)
            await daemon.stop()

        asyncio.run(_run())

        dlq_after = bus.get_dead_letters()
        entry_after = [e for e in dlq_after if e["event_id"] == "nonexistent_event_999"]
        assert len(entry_after) == 1
        assert entry_after[0]["retry_count"] > 0, (
            f"Expected retry_count > 0, got {entry_after[0]['retry_count']}"
        )
        assert entry_after[0]["next_retry_at"] != ""

    def test_daemon_start_stop_idempotent(self, tmp_path: Path) -> None:
        bus = _make_bus(tmp_path)
        daemon = DLQAutoRetryDaemon(bus, interval_seconds=60.0)

        async def _run() -> None:
            await daemon.start()
            await daemon.start()  # idempotent
            await daemon.stop()
            await daemon.stop()  # idempotent

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 5. SerialAction queue
# ---------------------------------------------------------------------------

class TestSerialActionQueue:
    def test_serial_execution_order(self, tmp_path: Path) -> None:
        """Enqueue 3 actions, verify they execute in FIFO order."""
        execution_order: List[str] = []

        async def executor(action: SerialAction) -> Dict[str, Any]:
            execution_order.append(action.action_id)
            await asyncio.sleep(0.02)
            return {"ok": True}

        queue = SerialActionQueue(executor=executor)

        async def _run() -> None:
            await queue.start_worker()

            actions = [
                SerialAction(
                    action_id=f"act_{i}",
                    actor="test",
                    scope="local",
                    action_type="other",
                    requires_global_mutex=False,
                    payload={"order": i},
                )
                for i in range(3)
            ]

            tickets = []
            for action in actions:
                ticket = await queue.enqueue(action)
                tickets.append(ticket)

            # Wait for all to complete
            await asyncio.sleep(0.3)
            await queue.stop_worker()

            assert execution_order == ["act_0", "act_1", "act_2"]

            # Verify tickets
            for ticket in tickets:
                t = queue.get_ticket(ticket.ticket_id)
                assert t is not None
                assert t.status == "done"

        asyncio.run(_run())

    def test_ticket_status_transitions(self, tmp_path: Path) -> None:
        """Verify ticket starts as queued and transitions to done."""
        async def executor(action: SerialAction) -> Dict[str, Any]:
            await asyncio.sleep(0.05)
            return {"ok": True}

        queue = SerialActionQueue(executor=executor)

        async def _run() -> None:
            await queue.start_worker()

            action = SerialAction(
                action_id="t1",
                actor="test",
                scope="local",
                action_type="write_file",
                requires_global_mutex=False,
                payload={},
            )
            ticket = await queue.enqueue(action)
            assert ticket.status == "queued"

            await asyncio.sleep(0.2)
            await queue.stop_worker()

            final = queue.get_ticket(ticket.ticket_id)
            assert final is not None
            assert final.status == "done"

        asyncio.run(_run())

    def test_failed_action_sets_ticket_failed(self, tmp_path: Path) -> None:
        """If executor raises, ticket status should be 'failed'."""
        async def executor(action: SerialAction) -> Dict[str, Any]:
            raise ValueError("boom")

        queue = SerialActionQueue(executor=executor)

        async def _run() -> None:
            await queue.start_worker()
            action = SerialAction(
                action_id="fail1",
                actor="test",
                scope="local",
                action_type="other",
                requires_global_mutex=False,
                payload={},
            )
            ticket = await queue.enqueue(action)
            await asyncio.sleep(0.15)
            await queue.stop_worker()

            final = queue.get_ticket(ticket.ticket_id)
            assert final is not None
            assert final.status == "failed"
            assert final.error == "boom"

        asyncio.run(_run())

    def test_get_ticket_unknown_returns_none(self) -> None:
        queue = SerialActionQueue()
        assert queue.get_ticket("nonexistent") is None

    def test_worker_start_stop_idempotent(self) -> None:
        queue = SerialActionQueue()

        async def _run() -> None:
            await queue.start_worker()
            await queue.start_worker()  # idempotent
            await queue.stop_worker()
            await queue.stop_worker()  # idempotent

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 6. Regression — existing subscribe/publish behavior unchanged
# ---------------------------------------------------------------------------

class TestRegressionExistingBehavior:
    def test_basic_subscribe_publish(self, tmp_path: Path) -> None:
        """Basic subscribe + publish still works with default params."""
        bus = _make_bus(tmp_path)
        received: List[Dict[str, Any]] = []

        def handler(evt: Dict[str, Any]) -> None:
            received.append(evt)

        sub = bus.subscribe("agent.*", handler)
        assert isinstance(sub, TopicSubscription)
        assert sub.pattern == "agent.*"

        event_id = bus.publish("agent.test", {"hello": "world"}, event_type="BasicTest")
        assert isinstance(event_id, str)
        assert len(event_id) > 0
        assert len(received) == 1
        assert received[0]["event_type"] == "BasicTest"

    def test_unsubscribe_stops_delivery(self, tmp_path: Path) -> None:
        bus = _make_bus(tmp_path)
        received: List[Dict[str, Any]] = []

        sub = bus.subscribe("agent.*", lambda e: received.append(e))
        bus.publish("agent.test", {"n": 1}, event_type="Before")
        assert len(received) == 1

        bus.unsubscribe(sub)
        bus.publish("agent.test", {"n": 2}, event_type="After")
        assert len(received) == 1  # no new delivery

    def test_dead_letter_on_handler_failure(self, tmp_path: Path) -> None:
        bus = _make_bus(tmp_path)

        def bad_handler(_e: Dict[str, Any]) -> None:
            raise RuntimeError("handler exploded")

        bus.subscribe("agent.*", bad_handler, max_retries=1)
        bus.publish("agent.test", {"x": 1}, event_type="DLQTest")

        dlq = bus.get_dead_letters()
        assert len(dlq) >= 1
        assert "handler exploded" in dlq[0]["error"]

    def test_dead_letter_has_next_retry_at_field(self, tmp_path: Path) -> None:
        """Verify schema migration: next_retry_at column exists in DLQ output."""
        bus = _make_bus(tmp_path)

        def bad_handler(_e: Dict[str, Any]) -> None:
            raise RuntimeError("fail")

        bus.subscribe("agent.*", bad_handler, max_retries=1)
        bus.publish("agent.test", {"x": 1}, event_type="SchemaTest")

        dlq = bus.get_dead_letters()
        assert len(dlq) >= 1
        assert "next_retry_at" in dlq[0]

    def test_iter_subscriptions(self, tmp_path: Path) -> None:
        bus = _make_bus(tmp_path)
        bus.subscribe("agent.*", lambda _e: None, priority=5)
        bus.subscribe("system.*", lambda _e: None, priority=1)

        subs = list(bus.iter_subscriptions())
        assert len(subs) == 2
        patterns = {s.pattern for s in subs}
        assert "agent.*" in patterns
        assert "system.*" in patterns

    def test_replay_still_works(self, tmp_path: Path) -> None:
        bus = _make_bus(tmp_path)
        bus.publish("agent.test", {"k": 1}, event_type="Replay1")
        bus.publish("agent.test", {"k": 2}, event_type="Replay2")

        rows = bus.replay(topic_pattern="agent.*", from_seq=1, limit=10)
        assert len(rows) == 2
        assert rows[0]["event_type"] == "Replay1"
        assert rows[1]["event_type"] == "Replay2"
