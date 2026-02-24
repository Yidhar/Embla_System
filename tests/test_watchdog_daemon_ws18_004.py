"""WS18-004 watchdog daemon threshold and action tests."""

from __future__ import annotations

from typing import Any, Dict, List

from system.watchdog_daemon import WatchdogDaemon, WatchdogThresholds


class DummyEmitter:
    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    def emit(self, event_type: str, payload: Dict[str, Any], **kwargs: Any) -> None:
        self.events.append({"event_type": event_type, "payload": dict(payload), "kwargs": dict(kwargs)})


def test_watchdog_run_once_no_threshold_hit() -> None:
    emitter = DummyEmitter()
    daemon = WatchdogDaemon(
        thresholds=WatchdogThresholds(cpu_percent=90, memory_percent=90, disk_percent=95, io_read_bps=1e9, io_write_bps=1e9, cost_per_hour=100),
        metrics_provider=lambda: {
            "cpu_percent": 20.0,
            "memory_percent": 30.0,
            "disk_percent": 40.0,
            "io_read_bps": 1024.0,
            "io_write_bps": 2048.0,
            "cost_per_hour": 0.3,
        },
        event_emitter=emitter,
    )
    action = daemon.run_once()
    assert action is None
    assert len(emitter.events) == 1
    assert emitter.events[0]["event_type"] == "WatchdogMetricsSampled"
    assert emitter.events[0]["payload"]["threshold_hit"] is False


def test_watchdog_warn_only_emits_alert_only_action() -> None:
    emitter = DummyEmitter()
    daemon = WatchdogDaemon(
        thresholds=WatchdogThresholds(cpu_percent=80, memory_percent=80, disk_percent=90, io_read_bps=10, io_write_bps=10, cost_per_hour=1.0),
        metrics_provider=lambda: {
            "cpu_percent": 82.0,
            "memory_percent": 84.0,
            "disk_percent": 92.0,
            "io_read_bps": 20.0,
            "io_write_bps": 30.0,
            "cost_per_hour": 1.2,
        },
        event_emitter=emitter,
        warn_only=True,
    )
    action = daemon.run_once()
    assert action is not None
    assert action.action == "alert_only"
    assert action.level in {"warn", "critical"}
    assert any("cpu_percent" in reason for reason in action.reasons)
    assert emitter.events[-1]["event_type"] == "WatchdogThresholdExceeded"
    assert emitter.events[-1]["payload"]["warn_only"] is True


def test_watchdog_non_warn_mode_critical_intervention() -> None:
    emitter = DummyEmitter()
    daemon = WatchdogDaemon(
        thresholds=WatchdogThresholds(cpu_percent=80, memory_percent=80, disk_percent=90, io_read_bps=10, io_write_bps=10, cost_per_hour=1.0),
        metrics_provider=lambda: {
            "cpu_percent": 97.0,  # critical (+17)
            "memory_percent": 92.0,  # critical (+12)
            "disk_percent": 96.0,  # critical (+6)
            "io_read_bps": 200.0,
            "io_write_bps": 300.0,
            "cost_per_hour": 2.0,  # critical (2x)
        },
        event_emitter=emitter,
        warn_only=False,
    )
    action = daemon.run_once()
    assert action is not None
    assert action.level == "critical"
    assert action.action == "pause_dispatch_and_escalate"
    assert emitter.events[-1]["event_type"] == "WatchdogThresholdExceeded"
    assert emitter.events[-1]["payload"]["action"] == "pause_dispatch_and_escalate"


def test_watchdog_non_warn_mode_warn_level_throttles() -> None:
    daemon = WatchdogDaemon(
        thresholds=WatchdogThresholds(cpu_percent=80, memory_percent=80, disk_percent=90, io_read_bps=10, io_write_bps=10, cost_per_hour=2.0),
        metrics_provider=lambda: {
            "cpu_percent": 81.0,
            "memory_percent": 79.0,
            "disk_percent": 85.0,
            "io_read_bps": 5.0,
            "io_write_bps": 5.0,
            "cost_per_hour": 1.5,
        },
        warn_only=False,
    )
    action = daemon.run_once()
    assert action is not None
    assert action.level == "warn"
    assert action.action == "throttle_new_workloads"
