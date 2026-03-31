"""WS33-007 — Chronos scheduling subsystem tests."""

import threading
import time

import pytest

from core.scheduler.chronos import ChronosScheduler, get_default_scheduler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeEmitter:
    """Collects emit() calls for assertion."""

    def __init__(self):
        self.events = []
        self._lock = threading.Lock()

    def emit(self, event_type: str, payload: dict):
        with self._lock:
            self.events.append((event_type, dict(payload)))

    def wait_for(self, event_type: str, *, timeout: float = 5.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                for ev_type, payload in self.events:
                    if ev_type == event_type:
                        return payload
            time.sleep(0.05)
        raise TimeoutError(f"Timed out waiting for event {event_type!r}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestChronosLifecycle:
    """Start / shutdown contract."""

    def test_start_and_shutdown(self):
        sched = ChronosScheduler()
        assert not sched.is_running

        sched.start()
        assert sched.is_running

        sched.shutdown()
        assert not sched.is_running

    def test_double_start_is_idempotent(self):
        sched = ChronosScheduler()
        sched.start()
        sched.start()  # must not raise
        assert sched.is_running
        sched.shutdown()

    def test_double_shutdown_is_idempotent(self):
        sched = ChronosScheduler()
        sched.start()
        sched.shutdown()
        sched.shutdown()  # must not raise
        assert not sched.is_running


class TestCronJob:
    """add_cron_job with a simple callable."""

    def test_cron_job_registers_and_appears_in_list(self):
        sched = ChronosScheduler()
        sched.start()
        try:
            sched.add_cron_job("test_cron_1", lambda: None, cron_expr="*/1 * * * *")
            jobs = sched.list_jobs()
            assert any(j["id"] == "test_cron_1" for j in jobs)
        finally:
            sched.shutdown()

    def test_cron_expr_validation_rejects_bad_fields(self):
        sched = ChronosScheduler()
        sched.start()
        try:
            with pytest.raises(ValueError, match="5 fields"):
                sched.add_cron_job("bad", lambda: None, cron_expr="*/1 *")
        finally:
            sched.shutdown()

    def test_remove_job(self):
        sched = ChronosScheduler()
        sched.start()
        try:
            sched.add_cron_job("removable", lambda: None, cron_expr="0 0 * * *")
            sched.remove_job("removable")
            assert not any(j["id"] == "removable" for j in sched.list_jobs())
        finally:
            sched.shutdown()

    def test_remove_nonexistent_job_does_not_raise(self):
        sched = ChronosScheduler()
        sched.start()
        try:
            sched.remove_job("ghost_job")  # must not raise
        finally:
            sched.shutdown()


class TestIntervalJob:
    """add_interval_job fires repeatedly."""

    def test_interval_job_executes(self):
        counter = {"n": 0}
        lock = threading.Lock()

        def tick():
            with lock:
                counter["n"] += 1

        sched = ChronosScheduler()
        sched.start()
        try:
            sched.add_interval_job("ticker", tick, seconds=0.1)
            # Wait enough time for at least 2 executions
            time.sleep(0.6)
            with lock:
                assert counter["n"] >= 2, f"Expected >=2 ticks, got {counter['n']}"
        finally:
            sched.shutdown()


class TestEventEmission:
    """Event emission on job completion and failure."""

    def test_emits_completed_on_success(self):
        emitter = FakeEmitter()
        sched = ChronosScheduler(event_emitter=emitter)
        sched.start()
        try:
            sched.add_interval_job("ok_job", lambda: "done", seconds=0.1)
            payload = emitter.wait_for("CronJobCompleted", timeout=3.0)
            assert payload["job_id"] == "ok_job"
            assert payload["status"] == "success"
        finally:
            sched.shutdown()

    def test_emits_failed_on_exception(self):
        emitter = FakeEmitter()
        sched = ChronosScheduler(event_emitter=emitter)
        sched.start()
        try:

            def boom():
                raise RuntimeError("kaboom")

            sched.add_interval_job("bad_job", boom, seconds=0.1)
            payload = emitter.wait_for("CronJobFailed", timeout=3.0)
            assert payload["job_id"] == "bad_job"
            assert "kaboom" in payload["error"]
        finally:
            sched.shutdown()

    def test_no_emitter_does_not_crash(self):
        """Jobs still run even when no event_emitter is configured."""
        counter = {"n": 0}
        lock = threading.Lock()

        def tick():
            with lock:
                counter["n"] += 1

        sched = ChronosScheduler(event_emitter=None)
        sched.start()
        try:
            sched.add_interval_job("silent", tick, seconds=0.1)
            time.sleep(0.4)
            with lock:
                assert counter["n"] >= 1
        finally:
            sched.shutdown()


class TestGetDefaultScheduler:
    """Singleton factory."""

    def test_returns_same_instance(self):
        import core.scheduler.chronos as mod

        # Reset to ensure clean state
        mod._DEFAULT_SCHEDULER = None
        try:
            a = get_default_scheduler()
            b = get_default_scheduler()
            assert a is b
        finally:
            # Clean up so other tests are unaffected
            if mod._DEFAULT_SCHEDULER is not None and mod._DEFAULT_SCHEDULER.is_running:
                mod._DEFAULT_SCHEDULER.shutdown()
            mod._DEFAULT_SCHEDULER = None

    def test_returns_chronos_scheduler_type(self):
        import core.scheduler.chronos as mod

        mod._DEFAULT_SCHEDULER = None
        try:
            sched = get_default_scheduler()
            assert isinstance(sched, ChronosScheduler)
        finally:
            if mod._DEFAULT_SCHEDULER is not None and mod._DEFAULT_SCHEDULER.is_running:
                mod._DEFAULT_SCHEDULER.shutdown()
            mod._DEFAULT_SCHEDULER = None
