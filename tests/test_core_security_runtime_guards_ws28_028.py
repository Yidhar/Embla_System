from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
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
    assert state["status"] == "ok"
    assert state["active"] is False
    assert state["execution_state"] == "planned"
    assert state["reason_code"] == "KILLSWITCH_PLAN_GENERATED"

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


def test_budget_guard_controller_initializes_baseline_state(tmp_path: Path) -> None:
    controller = BudgetGuardController(state_file=tmp_path / "budget_guard_state.json")
    first = controller.ensure_baseline_state(requested_by="unit-test")
    assert first["baseline_written"] is True
    assert first["status"] == "ok"
    assert first["reason_code"] == "BUDGET_GUARD_BASELINE_READY"
    assert first["details"]["baseline"] is True
    assert first["details"]["requested_by"] == "unit-test"

    second = controller.ensure_baseline_state(requested_by="unit-test")
    assert second["baseline_written"] is False
    assert second["status"] == "ok"


def test_budget_guard_idle_baseline_does_not_become_stale(tmp_path: Path) -> None:
    controller = BudgetGuardController(state_file=tmp_path / "budget_guard_state.json")
    stale_generated_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    controller.state_file.write_text(
        json.dumps(
            {
                "generated_at": stale_generated_at,
                "status": "ok",
                "reason_code": "BUDGET_GUARD_BASELINE_READY",
                "reason_text": "budget guard baseline state initialized",
                "task_id": "",
                "tool_name": "",
                "action": "",
                "details": {
                    "baseline": True,
                    "requested_by": "unit-test",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    state = controller.read_state(stale_warning_seconds=60.0, stale_critical_seconds=120.0)
    assert state["status"] == "ok"
    assert state["reason_code"] == "BUDGET_GUARD_BASELINE_READY"
    assert state["details"]["baseline"] is True


def test_killswitch_controller_normalizes_legacy_native_tool_plan(tmp_path: Path) -> None:
    controller = KillSwitchController(state_file=tmp_path / "killswitch_state.json")
    controller.state_file.write_text(
        json.dumps(
            {
                "generated_at": "2026-03-09T19:14:42.059384+00:00",
                "status": "critical",
                "reason_code": "KILLSWITCH_ENGAGED",
                "reason_text": "KillSwitch freeze plan is active.",
                "mode": "freeze_with_oob_allowlist",
                "active": True,
                "approval_ticket": "",
                "requested_by": "native_tool",
                "oob_allowlist": ["10.0.0.0/24"],
                "commands_count": 8,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    state = controller.read_state()
    assert state["status"] == "ok"
    assert state["active"] is False
    assert state["execution_state"] == "planned"
    assert state["reason_code"] == "KILLSWITCH_PLAN_GENERATED"
