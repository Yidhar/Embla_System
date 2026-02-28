from __future__ import annotations

from pathlib import Path

from core.security import BudgetGuardController, KillSwitchController
from system.loop_cost_guard import LoopCostThresholds


def test_killswitch_controller_persists_active_state(tmp_path: Path) -> None:
    controller = KillSwitchController(state_file=tmp_path / "killswitch_state.json")
    plan = controller.create_freeze_plan(
        oob_allowlist=["127.0.0.1/32"],
        dns_allow=True,
        requested_by="unit-test",
        approval_ticket="CAB-WS28",
        activate=True,
    )
    assert plan.mode == "freeze_with_oob_allowlist"
    state = controller.read_state()
    assert state["status"] == "critical"
    assert state["active"] is True
    assert state["reason_code"] == "KILLSWITCH_ENGAGED"

    released = controller.release(requested_by="unit-test", approval_ticket="CAB-WS28")
    assert released["status"] == "ok"
    assert released["active"] is False


def test_budget_guard_controller_persists_trigger_state(tmp_path: Path) -> None:
    controller = BudgetGuardController(
        thresholds=LoopCostThresholds(
            consecutive_error_limit=2,
            tool_call_limit_per_minute=999,
            task_cost_limit=999.0,
            daily_cost_limit=9999.0,
            loop_window_seconds=60,
        ),
        state_file=tmp_path / "budget_guard_state.json",
    )
    assert controller.observe_tool_call(task_id="task-1", tool_name="run_cmd", success=False, call_cost=0.0) is None
    payload = controller.observe_tool_call(task_id="task-1", tool_name="run_cmd", success=False, call_cost=0.0)
    assert payload is not None
    assert payload["reason"] == "consecutive_error_limit_exceeded"

    state = controller.read_state()
    assert state["status"] == "critical"
    assert state["reason_code"] == "CONSECUTIVE_ERROR_LIMIT_EXCEEDED"
    assert state["task_id"] == "task-1"
