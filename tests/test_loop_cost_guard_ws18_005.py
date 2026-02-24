"""WS18-005 loop detector and cost breaker tests."""

from __future__ import annotations

from typing import Any, Dict, List

from system.loop_cost_guard import LoopCostGuard, LoopCostThresholds
from system.watchdog_daemon import WatchdogDaemon


class DummyEmitter:
    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    def emit(self, event_type: str, payload: Dict[str, Any], **kwargs: Any) -> None:
        self.events.append({"event_type": event_type, "payload": dict(payload), "kwargs": dict(kwargs)})


def test_loop_cost_guard_triggers_on_consecutive_errors() -> None:
    now = [1000.0]
    guard = LoopCostGuard(
        thresholds=LoopCostThresholds(consecutive_error_limit=3, tool_call_limit_per_minute=99, task_cost_limit=100, daily_cost_limit=1000),
        now_fn=lambda: now[0],
    )

    action = None
    for _ in range(3):
        action = guard.observe_tool_call(task_id="task-a", tool_name="os_bash", success=False, call_cost=0.1)
        now[0] += 1.0

    assert action is not None
    assert action.reason == "consecutive_error_limit_exceeded"
    assert action.action == "kill_agent_loop"


def test_loop_cost_guard_resets_error_streak_after_success() -> None:
    now = [2000.0]
    guard = LoopCostGuard(
        thresholds=LoopCostThresholds(consecutive_error_limit=3, tool_call_limit_per_minute=99, task_cost_limit=100, daily_cost_limit=1000),
        now_fn=lambda: now[0],
    )
    guard.observe_tool_call(task_id="task-b", tool_name="read_file", success=False, call_cost=0.0)
    now[0] += 1.0
    guard.observe_tool_call(task_id="task-b", tool_name="read_file", success=True, call_cost=0.0)
    now[0] += 1.0
    action = guard.observe_tool_call(task_id="task-b", tool_name="read_file", success=False, call_cost=0.0)
    assert action is None


def test_loop_cost_guard_triggers_on_tool_call_storm() -> None:
    now = [3000.0]
    guard = LoopCostGuard(
        thresholds=LoopCostThresholds(consecutive_error_limit=99, tool_call_limit_per_minute=3, task_cost_limit=100, daily_cost_limit=1000),
        now_fn=lambda: now[0],
    )
    action = None
    for _ in range(4):
        action = guard.observe_tool_call(task_id="task-c", tool_name="artifact_reader", success=True, call_cost=0.0)
        now[0] += 5.0
    assert action is not None
    assert action.reason == "tool_call_rate_limit_exceeded"
    assert action.action == "kill_agent_loop"


def test_loop_cost_guard_triggers_task_and_daily_budget_breakers() -> None:
    now = [4000.0]
    emitter = DummyEmitter()
    guard = LoopCostGuard(
        thresholds=LoopCostThresholds(consecutive_error_limit=99, tool_call_limit_per_minute=99, task_cost_limit=3.0, daily_cost_limit=5.0),
        now_fn=lambda: now[0],
        event_emitter=emitter,
    )

    action_task = guard.observe_tool_call(task_id="task-d", tool_name="llm_call", success=True, call_cost=3.5)
    assert action_task is not None
    assert action_task.reason == "task_cost_limit_exceeded"
    assert action_task.action == "terminate_task_budget_exceeded"

    now[0] += 1.0
    action_day = guard.observe_tool_call(task_id="task-e", tool_name="llm_call", success=True, call_cost=2.0)
    assert action_day is not None
    assert action_day.reason == "daily_cost_limit_exceeded"
    assert action_day.action == "freeze_noncritical_budget"
    assert any(event["event_type"] == "budget.task.exceeded" for event in emitter.events)
    assert any(event["event_type"] == "budget.daily.exhausted" for event in emitter.events)


def test_watchdog_daemon_can_bridge_loop_cost_actions() -> None:
    now = [5000.0]
    emitter = DummyEmitter()
    guard = LoopCostGuard(
        thresholds=LoopCostThresholds(consecutive_error_limit=2, tool_call_limit_per_minute=99, task_cost_limit=100, daily_cost_limit=1000),
        now_fn=lambda: now[0],
    )
    daemon = WatchdogDaemon(
        metrics_provider=lambda: {
            "cpu_percent": 1.0,
            "memory_percent": 1.0,
            "disk_percent": 1.0,
            "io_read_bps": 0.0,
            "io_write_bps": 0.0,
            "cost_per_hour": 0.01,
        },
        event_emitter=emitter,
        loop_cost_guard=guard,
    )

    assert daemon.observe_tool_call(task_id="task-f", tool_name="os_bash", success=False, call_cost=0.0) is None
    now[0] += 1.0
    payload = daemon.observe_tool_call(task_id="task-f", tool_name="os_bash", success=False, call_cost=0.0)
    assert payload is not None
    assert payload["reason"] == "consecutive_error_limit_exceeded"
    assert any(event["event_type"] == "WatchdogLoopCostAction" for event in emitter.events)
