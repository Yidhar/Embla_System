import shutil
import uuid
from pathlib import Path

from autonomous.state import WorkflowStore


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_workflow_store_state_and_command():
    case_root = _make_case_root("test_workflow_store")
    try:
        db_path = case_root / "workflow.db"
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
            command_type="legacy_execute",
            idempotency_key="task-1:legacy:1",
            attempt=1,
            max_attempt=2,
        )
        assert command_id
        store.update_command(command_id, status="succeeded")

        # Idempotency key should return the same command id on retry/replay.
        same_command_id = store.create_command(
            workflow_id=workflow_id,
            step_name="implement_verify",
            command_type="legacy_execute",
            idempotency_key="task-1:legacy:1",
            attempt=1,
            max_attempt=2,
        )
        assert same_command_id == command_id
    finally:
        _cleanup_case_root(case_root)


def test_workflow_store_outbox():
    case_root = _make_case_root("test_workflow_store")
    try:
        db_path = case_root / "workflow.db"
        store = WorkflowStore(db_path=db_path)
        workflow_id = "wf-test-outbox"
        store.create_workflow(workflow_id=workflow_id, task_id="task-outbox")

        outbox_id = store.enqueue_outbox(workflow_id, "TaskApproved", {"ok": True})
        pending = store.read_pending_outbox(limit=10)
        assert len(pending) == 1
        assert pending[0]["outbox_id"] == outbox_id
        assert pending[0]["event_type"] == "TaskApproved"
        assert pending[0]["schema_version"] == "ws18-001-v1"
        assert pending[0]["payload"]["ok"] is True
        assert pending[0]["event_envelope"]["data"]["ok"] is True

        store.mark_outbox_dispatched(outbox_id)
        pending = store.read_pending_outbox(limit=10)
        assert pending == []
    finally:
        _cleanup_case_root(case_root)


def test_workflow_store_outbox_inbox_atomic_completion():
    case_root = _make_case_root("test_workflow_store")
    try:
        db_path = case_root / "workflow.db"
        store = WorkflowStore(db_path=db_path)
        workflow_id = "wf-outbox-inbox-1"
        store.create_workflow(workflow_id=workflow_id, task_id="task-outbox-inbox")

        outbox_id = store.enqueue_outbox(workflow_id, "TaskApproved", {"ok": True})
        assert store.is_inbox_processed("release-controller", str(outbox_id)) is False

        store.complete_outbox_for_consumer(outbox_id, "release-controller", str(outbox_id))
        assert store.is_inbox_processed("release-controller", str(outbox_id)) is True
        assert store.read_pending_outbox(limit=10) == []
    finally:
        _cleanup_case_root(case_root)


def test_workflow_store_read_pending_outbox_normalizes_legacy_payload():
    case_root = _make_case_root("test_workflow_store")
    try:
        db_path = case_root / "workflow.db"
        store = WorkflowStore(db_path=db_path)
        workflow_id = "wf-outbox-legacy"
        store.create_workflow(workflow_id=workflow_id, task_id="task-legacy")

        # Simulate a legacy row written before ws18 schema rollout.
        with store._connect() as conn:  # noqa: SLF001
            now = "2026-02-24T00:00:00+00:00"
            conn.execute(
                """
                INSERT INTO outbox_event
                (workflow_id, event_type, payload_json, status, created_at, updated_at)
                VALUES (?, ?, ?, 'pending', ?, ?)
                """,
                (workflow_id, "LegacyEvent", '{"legacy": true}', now, now),
            )
            conn.commit()

        pending = store.read_pending_outbox(limit=10)
        assert len(pending) == 1
        row = pending[0]
        assert row["event_type"] == "LegacyEvent"
        assert row["schema_version"] == "ws18-001-v1"
        assert row["payload"]["legacy"] is True
        assert row["event_envelope"]["event_type"] == "LegacyEvent"
    finally:
        _cleanup_case_root(case_root)


def test_workflow_store_outbox_retry_and_dead_letter():
    case_root = _make_case_root("test_workflow_store")
    try:
        db_path = case_root / "workflow.db"
        store = WorkflowStore(db_path=db_path)
        workflow_id = "wf-outbox-retry"
        store.create_workflow(workflow_id=workflow_id, task_id="task-retry")

        outbox_id = store.enqueue_outbox(workflow_id, "TaskApproved", {"ok": True}, max_attempts=2)

        first = store.record_outbox_attempt_failure(
            outbox_id,
            "transient failure",
            base_backoff_seconds=0,
            max_backoff_seconds=0,
        )
        assert first["status"] == "pending"
        assert first["attempts"] == 1
        assert first["exhausted"] is False

        pending_after_first = store.read_pending_outbox(limit=10)
        assert len(pending_after_first) == 1
        assert pending_after_first[0]["outbox_id"] == outbox_id
        assert pending_after_first[0]["dispatch_attempts"] == 1
        assert pending_after_first[0]["last_error"] == "transient failure"

        second = store.record_outbox_attempt_failure(
            outbox_id,
            "fatal failure",
            base_backoff_seconds=0,
            max_backoff_seconds=0,
        )
        assert second["status"] == "dead_letter"
        assert second["attempts"] == 2
        assert second["exhausted"] is True

        pending_after_second = store.read_pending_outbox(limit=10)
        assert pending_after_second == []
    finally:
        _cleanup_case_root(case_root)


def test_workflow_store_lease_fencing():
    case_root = _make_case_root("test_workflow_store")
    try:
        db_path = case_root / "workflow.db"
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
    finally:
        _cleanup_case_root(case_root)
