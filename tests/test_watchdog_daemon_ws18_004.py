"""WS18-004 watchdog daemon threshold and action tests."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from system.watchdog_daemon import WatchdogDaemon, WatchdogThresholds


class DummyEmitter:
    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    def emit(self, event_type: str, payload: Dict[str, Any], **kwargs: Any) -> None:
        self.events.append({"event_type": event_type, "payload": dict(payload), "kwargs": dict(kwargs)})


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


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


def test_watchdog_daemon_run_daemon_writes_state_file() -> None:
    case_root = _make_case_root("test_watchdog_daemon_ws18_004")
    try:
        state_file = case_root / "watchdog_state.json"
        daemon = WatchdogDaemon(
            thresholds=WatchdogThresholds(cpu_percent=99, memory_percent=99, disk_percent=99, io_read_bps=1e9, io_write_bps=1e9, cost_per_hour=100),
            metrics_provider=lambda: {
                "cpu_percent": 10.0,
                "memory_percent": 20.0,
                "disk_percent": 30.0,
                "io_read_bps": 1.0,
                "io_write_bps": 2.0,
                "cost_per_hour": 0.1,
            },
            warn_only=True,
        )
        result = daemon.run_daemon(state_file=state_file, interval_seconds=0.0, max_ticks=2)
        assert int(result["ticks_completed"]) == 2
        assert state_file.exists() is True
        payload = json.loads(state_file.read_text(encoding="utf-8"))
        assert payload["tick"] == 2
        assert payload["mode"] == "daemon"
        assert payload["status"] == "ok"
    finally:
        _cleanup_case_root(case_root)


def test_watchdog_daemon_read_state_marks_stale() -> None:
    case_root = _make_case_root("test_watchdog_daemon_ws18_004")
    try:
        state_file = case_root / "watchdog_state.json"
        state_file.write_text(
            json.dumps(
                {
                    "generated_at": "2026-02-20T00:00:00+00:00",
                    "pid": 1234,
                    "mode": "daemon",
                    "tick": 5,
                    "status": "ok",
                    "warn_only": True,
                    "threshold_hit": False,
                    "snapshot": {},
                    "action": None,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        state = WatchdogDaemon.read_daemon_state(
            state_file,
            now_ts=datetime(2026, 2, 20, 1, 0, tzinfo=timezone.utc).timestamp(),
            stale_warning_seconds=30.0,
            stale_critical_seconds=60.0,
        )
        assert state["status"] == "critical"
        assert state["reason_code"] == "WATCHDOG_DAEMON_STALE_CRITICAL"
    finally:
        _cleanup_case_root(case_root)
