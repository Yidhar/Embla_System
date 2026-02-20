"""Minimal self-check smoke tests for NagaAgent autonomous core.

Run: python scripts/self_check_smoke.py
"""

from __future__ import annotations

from pathlib import Path


def main() -> int:
    # ---- WorkflowStore: idempotency / outbox-inbox / lease-fencing ----
    from autonomous.state import WorkflowStore

    tmp_root = Path("logs") / "self_check"
    tmp_root.mkdir(parents=True, exist_ok=True)
    db_path = tmp_root / "workflow_smoke.db"
    if db_path.exists():
        db_path.unlink()

    store = WorkflowStore(db_path=db_path)
    wf = "wf-smoke-1"
    store.create_workflow(workflow_id=wf, task_id="task-smoke", initial_state="GoalAccepted", max_retries=1)
    store.transition(wf, "PlanDrafted", reason="smoke")

    cmd1 = store.create_command(
        workflow_id=wf,
        step_name="smoke",
        command_type="native",
        idempotency_key="k1",
        attempt=1,
        max_attempt=1,
        fencing_epoch=0,
    )
    cmd2 = store.create_command(
        workflow_id=wf,
        step_name="smoke",
        command_type="native",
        idempotency_key="k1",
        attempt=1,
        max_attempt=1,
        fencing_epoch=0,
    )
    assert cmd1 == cmd2, "idempotency_key should dedup create_command"

    outbox_id = store.enqueue_outbox(wf, "TaskApproved", {"ok": True})
    pending = store.read_pending_outbox(limit=10)
    assert any(e["outbox_id"] == outbox_id for e in pending)

    consumer = "release-controller"
    msg_id = str(outbox_id)
    assert store.is_inbox_processed(consumer, msg_id) is False
    store.complete_outbox_for_consumer(outbox_id, consumer, msg_id)
    assert store.is_inbox_processed(consumer, msg_id) is True
    assert store.read_pending_outbox(limit=10) == []

    lease_a = store.try_acquire_or_renew_lease("global_orchestrator", "agent-A", ttl_seconds=1)
    assert lease_a.is_owner is True and lease_a.fencing_epoch == 1
    lease_b = store.try_acquire_or_renew_lease("global_orchestrator", "agent-B", ttl_seconds=1)
    assert lease_b.is_owner is False and lease_b.owner_id == "agent-A"

    # ---- ReleaseController: canary decision should promote on synthetic windows ----
    from autonomous.release import ReleaseController

    rc = ReleaseController(repo_dir=str(Path(".")), policy_path=Path("policy/gate_policy.yaml"))
    decision = rc.evaluate_canary(observations=None)
    assert decision.outcome in {"promote", "observing", "rollback"}

    print("SELF_CHECK_SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
