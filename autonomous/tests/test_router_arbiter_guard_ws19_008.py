from __future__ import annotations

from agents.router_arbiter_guard import RouterArbiterGuard


def test_router_arbiter_guard_escalates_after_max_delegate_turns() -> None:
    guard = RouterArbiterGuard(max_delegate_turns=3)
    d1 = guard.register_delegate_turn(
        task_id="task-1",
        from_agent="frontend",
        to_agent="backend",
        reason="contract mismatch",
        conflict_ticket="ct-1",
    )
    d2 = guard.register_delegate_turn(
        task_id="task-1",
        from_agent="frontend",
        to_agent="backend",
        reason="contract mismatch",
        conflict_ticket="ct-1",
    )
    d3 = guard.register_delegate_turn(
        task_id="task-1",
        from_agent="frontend",
        to_agent="backend",
        reason="contract mismatch",
        conflict_ticket="ct-1",
    )

    assert d1.escalated is False
    assert d2.escalated is False
    assert d3.escalated is True
    assert d3.freeze is True
    assert d3.hitl is True
    assert guard.should_freeze_task("task-1") is True


def test_router_arbiter_guard_resets_turns_when_conflict_ticket_changes() -> None:
    guard = RouterArbiterGuard(max_delegate_turns=3)
    guard.register_delegate_turn(
        task_id="task-2",
        from_agent="frontend",
        to_agent="backend",
        reason="field a missing",
        conflict_ticket="ct-a",
    )
    guard.register_delegate_turn(
        task_id="task-2",
        from_agent="frontend",
        to_agent="backend",
        reason="field a missing",
        conflict_ticket="ct-a",
    )
    switched = guard.register_delegate_turn(
        task_id="task-2",
        from_agent="frontend",
        to_agent="backend",
        reason="new conflict in auth flow",
        conflict_ticket="ct-b",
    )

    assert switched.delegate_turns == 1
    assert switched.escalated is False
    assert guard.should_freeze_task("task-2") is False


def test_router_arbiter_guard_observes_workspace_conflict_signal() -> None:
    guard = RouterArbiterGuard(max_delegate_turns=3)
    call = {"agentType": "native", "tool_name": "workspace_txn_apply"}
    result = {"status": "error", "result": "workspace transaction failed: conflict_ticket=ct-ws-1"}

    d1 = guard.observe_workspace_conflict(task_id="task-ws-1", call=call, result=result)
    d2 = guard.observe_workspace_conflict(task_id="task-ws-1", call=call, result=result)
    d3 = guard.observe_workspace_conflict(task_id="task-ws-1", call=call, result=result)

    assert d1 is not None and d1.escalated is False
    assert d2 is not None and d2.escalated is False
    assert d3 is not None and d3.escalated is True
    assert d3.reason == "router_delegate_threshold_exceeded"


def test_router_arbiter_guard_builds_summary_and_can_reset_task() -> None:
    guard = RouterArbiterGuard(max_delegate_turns=3)
    guard.register_delegate_turn(
        task_id="task-3",
        from_agent="frontend",
        to_agent="backend",
        reason="schema mismatch",
        conflict_ticket="ct-3",
        candidate_decisions=["use backend schema v2"],
    )
    summary = guard.build_conflict_summary("task-3")
    assert summary["task_id"] == "task-3"
    assert summary["delegate_turns"] == 1
    assert "schema mismatch" in summary["conflict_points"]
    assert "use backend schema v2" in summary["candidate_decisions"]

    guard.reset_task("task-3")
    cleared = guard.build_conflict_summary("task-3")
    assert cleared["delegate_turns"] == 0
    assert cleared["freeze"] is False
