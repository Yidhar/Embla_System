from pathlib import Path

from autonomous.state import WorkflowStore


def test_workflow_store_state_and_command(tmp_path: Path):
    db_path = tmp_path / "workflow.db"
    store = WorkflowStore(db_path=db_path)

    workflow_id = "wf-test-1"
    store.create_workflow(workflow_id=workflow_id, task_id="task-1", initial_state="GoalAccepted", max_retries=2)

    data = store.get_workflow(workflow_id)
    assert data is not None
    assert data["current_state"] == "GoalAccepted"
    assert data["max_retries"] == 2

    store.transition(workflow_id, "PlanDrafted", reason="planned")
    data = store.get_workflow(workflow_id)
    assert data is not None
    assert data["current_state"] == "PlanDrafted"

    command_id = store.create_command(
        workflow_id=workflow_id,
        step_name="implement_verify",
        command_type="cli_execute",
        idempotency_key="task-1:cli:1",
        attempt=1,
        max_attempt=2,
    )
    assert command_id
    store.update_command(command_id, status="succeeded")

    # Idempotency key should return the same command id on retry/replay.
    same_command_id = store.create_command(
        workflow_id=workflow_id,
        step_name="implement_verify",
        command_type="cli_execute",
        idempotency_key="task-1:cli:1",
        attempt=1,
        max_attempt=2,
    )
    assert same_command_id == command_id


def test_workflow_store_outbox(tmp_path: Path):
    db_path = tmp_path / "workflow.db"
    store = WorkflowStore(db_path=db_path)
    workflow_id = "wf-test-outbox"
    store.create_workflow(workflow_id=workflow_id, task_id="task-outbox")

    outbox_id = store.enqueue_outbox(workflow_id, "TaskApproved", {"ok": True})
    pending = store.read_pending_outbox(limit=10)
    assert len(pending) == 1
    assert pending[0]["outbox_id"] == outbox_id
    assert pending[0]["event_type"] == "TaskApproved"

    store.mark_outbox_dispatched(outbox_id)
    pending = store.read_pending_outbox(limit=10)
    assert pending == []


def test_workflow_store_outbox_inbox_atomic_completion(tmp_path: Path):
    db_path = tmp_path / "workflow.db"
    store = WorkflowStore(db_path=db_path)
    workflow_id = "wf-outbox-inbox-1"
    store.create_workflow(workflow_id=workflow_id, task_id="task-outbox-inbox")

    outbox_id = store.enqueue_outbox(workflow_id, "TaskApproved", {"ok": True})
    assert store.is_inbox_processed("release-controller", str(outbox_id)) is False

    store.complete_outbox_for_consumer(outbox_id, "release-controller", str(outbox_id))
    assert store.is_inbox_processed("release-controller", str(outbox_id)) is True
    assert store.read_pending_outbox(limit=10) == []


def test_workflow_store_lease_fencing(tmp_path: Path):
    db_path = tmp_path / "workflow.db"
    store = WorkflowStore(db_path=db_path)

    lease_a = store.try_acquire_or_renew_lease("global_orchestrator", "agent-A", ttl_seconds=1)
    assert lease_a.is_owner is True
    assert lease_a.fencing_epoch == 1
    assert store.is_lease_owner("global_orchestrator", "agent-A", 1) is True

    lease_b = store.try_acquire_or_renew_lease("global_orchestrator", "agent-B", ttl_seconds=1)
    assert lease_b.is_owner is False
    assert lease_b.owner_id == "agent-A"

    # Renew by owner keeps same epoch.
    renew_a = store.try_acquire_or_renew_lease("global_orchestrator", "agent-A", ttl_seconds=1)
    assert renew_a.is_owner is True
    assert renew_a.fencing_epoch == 1
