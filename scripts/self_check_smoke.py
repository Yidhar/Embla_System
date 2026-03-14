"""Minimal self-check smoke tests for Embla System autonomous core.

Run: python scripts/self_check_smoke.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path


def main() -> int:
    # ---- WorkflowStore + GlobalMutex: idempotency / outbox-inbox / live lease ----
    from agents.runtime.workflow_store import WorkflowStore
    from core.security.lease_fencing import GlobalMutexManager

    tmp_root = Path("logs") / "self_check"
    tmp_root.mkdir(parents=True, exist_ok=True)
    db_path = tmp_root / "workflow_smoke.db"
    lease_state_path = tmp_root / "global_mutex_lease.json"
    lease_audit_path = tmp_root / "global_mutex_events.jsonl"
    for stale_file in (db_path, lease_state_path, lease_audit_path):
        if stale_file.exists():
            stale_file.unlink()

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

    mutex = GlobalMutexManager(
        state_file=lease_state_path,
        audit_file=lease_audit_path,
    )
    mutex.ensure_initialized(ttl_seconds=1)
    lease_a = asyncio.run(
        mutex.acquire(
            owner_id="agent-A",
            job_id="global_orchestrator",
            ttl_seconds=1,
            wait_timeout_seconds=0.5,
            poll_interval_seconds=0.05,
        )
    )
    assert lease_a.fencing_epoch == 1
    assert asyncio.run(mutex.release(lease_a)) is True
    lease_b = asyncio.run(
        mutex.acquire(
            owner_id="agent-B",
            job_id="global_orchestrator",
            ttl_seconds=1,
            wait_timeout_seconds=0.5,
            poll_interval_seconds=0.05,
        )
    )
    assert lease_b.owner_id == "agent-B"
    assert lease_b.fencing_epoch > lease_a.fencing_epoch

    # ---- ReleaseController: canary decision should promote on synthetic windows ----
    from agents.release import ReleaseController

    rc = ReleaseController(repo_dir=str(Path(".")), policy_path=Path("policy/gate_policy.yaml"))
    decision = rc.evaluate_canary(observations=None)
    assert decision.outcome in {"promote", "observing", "rollback"}

    print("SELF_CHECK_SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
