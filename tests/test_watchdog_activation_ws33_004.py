"""WS33-004 watchdog activation — event emission, actuator callback, and backward compat tests."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.supervisor.watchdog_actuator import WatchdogActuator
from core.supervisor.watchdog_daemon import WatchdogDaemon, WatchdogThresholds


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


def _low_metrics() -> Dict[str, float]:
    return {
        "cpu_percent": 10.0,
        "memory_percent": 15.0,
        "disk_percent": 20.0,
        "io_read_bps": 5.0,
        "io_write_bps": 5.0,
        "cost_per_hour": 0.1,
    }


def _critical_metrics() -> Dict[str, float]:
    """Metrics that exceed thresholds at the critical level."""
    return {
        "cpu_percent": 97.0,
        "memory_percent": 95.0,
        "disk_percent": 97.0,
        "io_read_bps": 500.0,
        "io_write_bps": 600.0,
        "cost_per_hour": 10.0,
    }


def _warn_metrics() -> Dict[str, float]:
    """Metrics that exceed thresholds at the warn level (not critical)."""
    return {
        "cpu_percent": 86.0,
        "memory_percent": 86.0,
        "disk_percent": 91.0,
        "io_read_bps": 5.0,
        "io_write_bps": 5.0,
        "cost_per_hour": 1.0,
    }


_THRESHOLDS = WatchdogThresholds(
    cpu_percent=80,
    memory_percent=80,
    disk_percent=90,
    io_read_bps=10,
    io_write_bps=10,
    cost_per_hour=2.0,
)


# -----------------------------------------------------------------------
# 1. warn_only=False + event_emitter emits events
# -----------------------------------------------------------------------

def test_warn_only_false_with_event_emitter_emits_threshold_exceeded() -> None:
    """WatchdogDaemon with warn_only=False and event_emitter emits WatchdogThresholdExceeded."""
    emitter = DummyEmitter()
    daemon = WatchdogDaemon(
        thresholds=_THRESHOLDS,
        metrics_provider=_critical_metrics,
        event_emitter=emitter,
        warn_only=False,
    )
    action = daemon.run_once()
    assert action is not None
    assert action.level == "critical"
    assert action.action == "pause_dispatch_and_escalate"

    threshold_events = [e for e in emitter.events if e["event_type"] == "WatchdogThresholdExceeded"]
    assert len(threshold_events) == 1
    assert threshold_events[0]["payload"]["warn_only"] is False
    assert threshold_events[0]["payload"]["action"] == "pause_dispatch_and_escalate"


def test_warn_only_false_warn_level_emits_throttle_event() -> None:
    """Warn-level breach with warn_only=False emits throttle_new_workloads."""
    emitter = DummyEmitter()
    daemon = WatchdogDaemon(
        thresholds=_THRESHOLDS,
        metrics_provider=_warn_metrics,
        event_emitter=emitter,
        warn_only=False,
    )
    action = daemon.run_once()
    assert action is not None
    assert action.level == "warn"
    assert action.action == "throttle_new_workloads"

    threshold_events = [e for e in emitter.events if e["event_type"] == "WatchdogThresholdExceeded"]
    assert len(threshold_events) == 1
    assert threshold_events[0]["payload"]["action"] == "throttle_new_workloads"


def test_no_threshold_hit_emits_sampled_event() -> None:
    """When metrics are under thresholds, a WatchdogMetricsSampled event is emitted."""
    emitter = DummyEmitter()
    daemon = WatchdogDaemon(
        thresholds=_THRESHOLDS,
        metrics_provider=_low_metrics,
        event_emitter=emitter,
        warn_only=False,
    )
    action = daemon.run_once()
    assert action is None

    sampled_events = [e for e in emitter.events if e["event_type"] == "WatchdogMetricsSampled"]
    assert len(sampled_events) == 1
    assert sampled_events[0]["payload"]["threshold_hit"] is False


# -----------------------------------------------------------------------
# 2. Actuator callback invocation on critical thresholds
# -----------------------------------------------------------------------

def test_actuator_callback_invoked_on_critical_threshold() -> None:
    """Actuator callback is called when action != alert_only (critical -> pause_dispatch_and_escalate)."""
    emitter = DummyEmitter()
    callback_invocations: List[Dict[str, Any]] = []

    def _capture_callback(action_dict: Dict[str, Any]) -> None:
        callback_invocations.append(dict(action_dict))

    daemon = WatchdogDaemon(
        thresholds=_THRESHOLDS,
        metrics_provider=_critical_metrics,
        event_emitter=emitter,
        warn_only=False,
        actuator_callback=_capture_callback,
    )
    action = daemon.run_once()
    assert action is not None
    assert action.action == "pause_dispatch_and_escalate"

    # Callback should have been invoked exactly once
    assert len(callback_invocations) == 1
    assert callback_invocations[0]["action"] == "pause_dispatch_and_escalate"
    assert callback_invocations[0]["level"] == "critical"


def test_actuator_callback_invoked_on_warn_throttle() -> None:
    """Actuator callback is called for throttle_new_workloads."""
    callback_invocations: List[Dict[str, Any]] = []

    def _capture_callback(action_dict: Dict[str, Any]) -> None:
        callback_invocations.append(dict(action_dict))

    daemon = WatchdogDaemon(
        thresholds=_THRESHOLDS,
        metrics_provider=_warn_metrics,
        warn_only=False,
        actuator_callback=_capture_callback,
    )
    action = daemon.run_once()
    assert action is not None
    assert action.action == "throttle_new_workloads"

    assert len(callback_invocations) == 1
    assert callback_invocations[0]["action"] == "throttle_new_workloads"


def test_actuator_callback_not_invoked_for_alert_only() -> None:
    """Actuator callback is NOT called when action == alert_only (warn_only=True)."""
    callback_invocations: List[Dict[str, Any]] = []

    def _capture_callback(action_dict: Dict[str, Any]) -> None:
        callback_invocations.append(dict(action_dict))

    daemon = WatchdogDaemon(
        thresholds=_THRESHOLDS,
        metrics_provider=_critical_metrics,
        warn_only=True,
        actuator_callback=_capture_callback,
    )
    action = daemon.run_once()
    assert action is not None
    assert action.action == "alert_only"

    # Callback should NOT be called for alert_only
    assert len(callback_invocations) == 0


def test_actuator_callback_not_invoked_when_no_threshold_hit() -> None:
    """Actuator callback is not called when there is no threshold hit."""
    callback_invocations: List[Dict[str, Any]] = []

    def _capture_callback(action_dict: Dict[str, Any]) -> None:
        callback_invocations.append(dict(action_dict))

    daemon = WatchdogDaemon(
        thresholds=_THRESHOLDS,
        metrics_provider=_low_metrics,
        warn_only=False,
        actuator_callback=_capture_callback,
    )
    action = daemon.run_once()
    assert action is None
    assert len(callback_invocations) == 0


# -----------------------------------------------------------------------
# 3. Backward compat: warn_only=True still produces only alert_only
# -----------------------------------------------------------------------

def test_backward_compat_warn_only_true_produces_alert_only() -> None:
    """With warn_only=True, all threshold breaches produce alert_only regardless of severity."""
    emitter = DummyEmitter()
    daemon = WatchdogDaemon(
        thresholds=_THRESHOLDS,
        metrics_provider=_critical_metrics,
        event_emitter=emitter,
        warn_only=True,
    )
    action = daemon.run_once()
    assert action is not None
    assert action.action == "alert_only"
    assert action.level == "critical"

    threshold_events = [e for e in emitter.events if e["event_type"] == "WatchdogThresholdExceeded"]
    assert len(threshold_events) == 1
    assert threshold_events[0]["payload"]["warn_only"] is True
    assert threshold_events[0]["payload"]["action"] == "alert_only"


def test_backward_compat_warn_only_true_warn_level() -> None:
    """Warn-level breach with warn_only=True also produces alert_only."""
    emitter = DummyEmitter()
    daemon = WatchdogDaemon(
        thresholds=_THRESHOLDS,
        metrics_provider=_warn_metrics,
        event_emitter=emitter,
        warn_only=True,
    )
    action = daemon.run_once()
    assert action is not None
    assert action.action == "alert_only"
    assert action.level == "warn"

    threshold_events = [e for e in emitter.events if e["event_type"] == "WatchdogThresholdExceeded"]
    assert len(threshold_events) == 1
    assert threshold_events[0]["payload"]["action"] == "alert_only"


def test_backward_compat_no_event_emitter() -> None:
    """WatchdogDaemon works without event_emitter (backward compat)."""
    daemon = WatchdogDaemon(
        thresholds=_THRESHOLDS,
        metrics_provider=_critical_metrics,
        warn_only=True,
    )
    # Should not raise
    action = daemon.run_once()
    assert action is not None
    assert action.action == "alert_only"


def test_backward_compat_no_actuator_callback() -> None:
    """WatchdogDaemon works without actuator_callback (backward compat)."""
    daemon = WatchdogDaemon(
        thresholds=_THRESHOLDS,
        metrics_provider=_critical_metrics,
        warn_only=False,
    )
    # Should not raise even though action is pause_dispatch_and_escalate
    action = daemon.run_once()
    assert action is not None
    assert action.action == "pause_dispatch_and_escalate"


# -----------------------------------------------------------------------
# 4. WatchdogActuator unit tests
# -----------------------------------------------------------------------

def test_watchdog_actuator_handle_action_pause() -> None:
    """WatchdogActuator handles pause_dispatch_and_escalate and emits event."""
    emitter = DummyEmitter()
    actuator = WatchdogActuator(event_emitter=emitter)
    result = actuator.handle_action({"action": "pause_dispatch_and_escalate", "level": "critical", "reasons": ["cpu"]})
    assert result["executed"] == "pause_dispatch_and_escalate"

    action_events = [e for e in emitter.events if e["event_type"] == "WatchdogActionExecuted"]
    assert len(action_events) == 1
    assert action_events[0]["payload"]["action"] == "pause_dispatch_and_escalate"


def test_watchdog_actuator_handle_action_throttle() -> None:
    """WatchdogActuator handles throttle_new_workloads and emits event."""
    emitter = DummyEmitter()
    actuator = WatchdogActuator(event_emitter=emitter)
    result = actuator.handle_action({"action": "throttle_new_workloads", "level": "warn", "reasons": ["io"]})
    assert result["executed"] == "throttle_new_workloads"

    action_events = [e for e in emitter.events if e["event_type"] == "WatchdogActionExecuted"]
    assert len(action_events) == 1


def test_watchdog_actuator_handle_action_alert_only() -> None:
    """WatchdogActuator handles alert_only (no signal file written, still emits event)."""
    emitter = DummyEmitter()
    actuator = WatchdogActuator(event_emitter=emitter)
    result = actuator.handle_action({"action": "alert_only", "level": "warn"})
    assert result["executed"] == "alert_only"

    action_events = [e for e in emitter.events if e["event_type"] == "WatchdogActionExecuted"]
    assert len(action_events) == 1


def test_watchdog_actuator_no_emitter() -> None:
    """WatchdogActuator works without event_emitter."""
    actuator = WatchdogActuator()
    result = actuator.handle_action({"action": "pause_dispatch_and_escalate", "level": "critical"})
    assert result["executed"] == "pause_dispatch_and_escalate"


# -----------------------------------------------------------------------
# 5. Integration: daemon + actuator callback in daemon run
# -----------------------------------------------------------------------

def test_daemon_run_with_actuator_callback_invokes_on_threshold() -> None:
    """Full daemon run invokes actuator callback on threshold breach."""
    emitter = DummyEmitter()
    callback_invocations: List[Dict[str, Any]] = []

    def _capture(action_dict: Dict[str, Any]) -> None:
        callback_invocations.append(dict(action_dict))

    case_root = _make_case_root("test_watchdog_activation_ws33_004")
    try:
        state_file = case_root / "watchdog_state.json"
        daemon = WatchdogDaemon(
            thresholds=_THRESHOLDS,
            metrics_provider=_critical_metrics,
            event_emitter=emitter,
            warn_only=False,
            actuator_callback=_capture,
        )
        result = daemon.run_daemon(state_file=state_file, interval_seconds=0.0, max_ticks=3)
        assert int(result["ticks_completed"]) == 3

        # Every tick should have triggered the callback
        assert len(callback_invocations) == 3
        for inv in callback_invocations:
            assert inv["action"] == "pause_dispatch_and_escalate"

        # State file should reflect critical status
        payload = json.loads(state_file.read_text(encoding="utf-8"))
        assert payload["status"] == "critical"
        assert payload["warn_only"] is False
    finally:
        _cleanup_case_root(case_root)
