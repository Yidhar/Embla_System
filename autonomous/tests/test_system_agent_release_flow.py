from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

from autonomous.system_agent import SystemAgent


def _write_policy(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
gates:
  deploy:
    canary_window_min: 15
    min_sample_count: 200
    healthy_windows_for_promotion: 3
    bad_windows_for_rollback: 2
""".strip(),
        encoding="utf-8",
    )


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _create_agent(repo: Path) -> SystemAgent:
    return SystemAgent(
        config={
            "enabled": False,
            "release": {
                "enabled": True,
                "gate_policy_path": "policy/gate_policy.yaml",
                "auto_rollback_enabled": False,
                "rollback_command": "",
            },
        },
        repo_dir=str(repo),
    )


def test_release_rollback_event_contains_canary_audit_fields() -> None:
    case_root = _make_case_root("test_system_agent_release_flow")
    try:
        repo = case_root / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        _write_policy(repo / "policy" / "gate_policy.yaml")

        agent = _create_agent(repo)

        workflow_id = "wf-ws17-007"
        agent.workflow_store.create_workflow(workflow_id, task_id="task-ws17-007", initial_state="ReleaseCandidate")

        captured: list[tuple[str, dict, dict]] = []

        def _capture(event_type: str, payload: dict, **kwargs) -> None:
            captured.append((event_type, dict(payload), dict(kwargs)))

        agent._emit = _capture  # type: ignore[method-assign]
        event = {
            "outbox_id": 101,
            "workflow_id": workflow_id,
            "payload": {
                "task_id": "task-ws17-007",
                "canary_observations": [
                    {
                        "window_minutes": 15,
                        "sample_count": 230,
                        "error_rate": 0.11,
                        "latency_p95_ms": 2600,
                        "kpi_ratio": 0.81,
                    },
                    {
                        "window_minutes": 15,
                        "sample_count": 210,
                        "error_rate": 0.14,
                        "latency_p95_ms": 3000,
                        "kpi_ratio": 0.79,
                    },
                ],
            },
        }
        asyncio.run(agent._handle_task_approved_event(event, fencing_epoch=1))

        rollback_events = [payload for event_type, payload, _ in captured if event_type == "ReleaseRolledBack"]
        assert len(rollback_events) == 1

        rollback_payload = rollback_events[0]
        decision = rollback_payload["decision"]
        assert decision["outcome"] == "rollback"
        assert "policy_snapshot" in decision
        assert "threshold_snapshot" in decision
        assert "stats" in decision
        assert decision["trigger_window_index"] == 2
        assert rollback_payload["rollback_result"]["enabled"] is False
        assert rollback_payload["rollback_result"]["status"] == "skipped"

        structured = [payload for event_type, payload, _ in captured if event_type == "ReleaseRollbackTriggered"]
        assert len(structured) == 1
        assert structured[0]["severity"] == "critical"
        assert structured[0]["reason_code"] == "CANARY_ROLLBACK_TRIGGERED"
        assert structured[0]["trigger"] == "automatic_canary_rollback"

        opened = [
            payload
            for event_type, payload, _ in captured
            if event_type == "IncidentOpened" and payload.get("incident_event_type") == "ReleaseRollbackTriggered"
        ]
        assert len(opened) == 1
        assert opened[0]["reason_code"] == "CANARY_ROLLBACK_TRIGGERED"
        assert opened[0]["details"]["rollback_result"]["status"] == "skipped"
    finally:
        _cleanup_case_root(case_root)


def test_release_rollback_failure_emits_structured_incident() -> None:
    case_root = _make_case_root("test_system_agent_release_flow")
    try:
        repo = case_root / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        _write_policy(repo / "policy" / "gate_policy.yaml")
        agent = SystemAgent(
            config={
                "enabled": False,
                "release": {
                    "enabled": True,
                    "gate_policy_path": "policy/gate_policy.yaml",
                    "auto_rollback_enabled": True,
                    "rollback_command": "rollback-now",
                },
            },
            repo_dir=str(repo),
        )
        agent.release_controller.execute_rollback = lambda _cmd: (False, "simulated rollback failure")  # type: ignore[method-assign]

        workflow_id = "wf-ws17-007-rollback-fail"
        agent.workflow_store.create_workflow(workflow_id, task_id="task-ws17-007-rollback-fail", initial_state="ReleaseCandidate")

        captured: list[tuple[str, dict, dict]] = []

        def _capture(event_type: str, payload: dict, **kwargs) -> None:
            captured.append((event_type, dict(payload), dict(kwargs)))

        agent._emit = _capture  # type: ignore[method-assign]
        event = {
            "outbox_id": 102,
            "workflow_id": workflow_id,
            "payload": {
                "task_id": "task-ws17-007-rollback-fail",
                "canary_observations": [
                    {
                        "window_minutes": 15,
                        "sample_count": 230,
                        "error_rate": 0.11,
                        "latency_p95_ms": 2600,
                        "kpi_ratio": 0.81,
                    },
                    {
                        "window_minutes": 15,
                        "sample_count": 210,
                        "error_rate": 0.14,
                        "latency_p95_ms": 3000,
                        "kpi_ratio": 0.79,
                    },
                ],
            },
        }
        asyncio.run(agent._handle_task_approved_event(event, fencing_epoch=1))

        rollback_failed = [payload for event_type, payload, _ in captured if event_type == "ReleaseRollbackFailed"]
        assert len(rollback_failed) == 1
        assert rollback_failed[0]["severity"] == "critical"
        assert rollback_failed[0]["reason_code"] == "ROLLBACK_COMMAND_FAILED"
        assert rollback_failed[0]["details"]["rollback_result"]["status"] == "failed"

        opened = [
            payload
            for event_type, payload, _ in captured
            if event_type == "IncidentOpened" and payload.get("incident_event_type") == "ReleaseRollbackFailed"
        ]
        assert len(opened) == 1
        assert opened[0]["reason_code"] == "ROLLBACK_COMMAND_FAILED"
        assert "simulated rollback failure" in opened[0]["reason_text"]
    finally:
        _cleanup_case_root(case_root)


def test_outbox_dispatch_failure_schedules_retry() -> None:
    case_root = _make_case_root("test_system_agent_release_flow")
    try:
        repo = case_root / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        _write_policy(repo / "policy" / "gate_policy.yaml")
        agent = _create_agent(repo)

        workflow_id = "wf-outbox-retry"
        agent.workflow_store.create_workflow(workflow_id, task_id="task-outbox-retry", initial_state="ReleaseCandidate")
        agent.workflow_store.enqueue_outbox(
            workflow_id,
            "TaskApproved",
            {"task_id": "task-outbox-retry", "workflow_id": workflow_id},
            max_attempts=2,
        )
        event = agent.workflow_store.read_pending_outbox(limit=10)[0]

        captured: list[tuple[str, dict]] = []

        def _capture(event_type: str, payload: dict, **kwargs) -> None:
            captured.append((event_type, dict(payload)))

        agent._emit = _capture  # type: ignore[method-assign]

        async def _boom(*args, **kwargs):
            raise RuntimeError("outbox transient failure")

        agent._handle_outbox_business_event = _boom  # type: ignore[method-assign]
        asyncio.run(agent._dispatch_single_outbox_event(event, consumer="release-controller", fencing_epoch=1))

        with agent.workflow_store._connect() as conn:  # noqa: SLF001
            row = conn.execute(
                """
                SELECT status, dispatch_attempts, max_attempts, last_error, next_retry_at
                FROM outbox_event
                WHERE outbox_id = ?
                """,
                (event["outbox_id"],),
            ).fetchone()

        assert row is not None
        assert row["status"] == "pending"
        assert int(row["dispatch_attempts"]) == 1
        assert int(row["max_attempts"]) == 2
        assert "outbox transient failure" in str(row["last_error"] or "")
        assert row["next_retry_at"]
        assert any(event_type == "OutboxDispatchRetryScheduled" for event_type, _ in captured)
    finally:
        _cleanup_case_root(case_root)


def test_outbox_dispatch_failure_moves_to_dead_letter_when_exhausted() -> None:
    case_root = _make_case_root("test_system_agent_release_flow")
    try:
        repo = case_root / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        _write_policy(repo / "policy" / "gate_policy.yaml")
        agent = _create_agent(repo)

        workflow_id = "wf-outbox-dead-letter"
        agent.workflow_store.create_workflow(workflow_id, task_id="task-outbox-dead-letter", initial_state="ReleaseCandidate")
        agent.workflow_store.enqueue_outbox(
            workflow_id,
            "TaskApproved",
            {"task_id": "task-outbox-dead-letter", "workflow_id": workflow_id},
            max_attempts=1,
        )
        event = agent.workflow_store.read_pending_outbox(limit=10)[0]

        captured: list[tuple[str, dict]] = []

        def _capture(event_type: str, payload: dict, **kwargs) -> None:
            captured.append((event_type, dict(payload)))

        agent._emit = _capture  # type: ignore[method-assign]

        async def _boom(*args, **kwargs):
            raise RuntimeError("outbox fatal failure")

        agent._handle_outbox_business_event = _boom  # type: ignore[method-assign]
        asyncio.run(agent._dispatch_single_outbox_event(event, consumer="release-controller", fencing_epoch=1))

        pending = agent.workflow_store.read_pending_outbox(limit=10)
        assert pending == []

        with agent.workflow_store._connect() as conn:  # noqa: SLF001
            row = conn.execute(
                """
                SELECT status, dispatch_attempts, max_attempts, last_error, next_retry_at
                FROM outbox_event
                WHERE outbox_id = ?
                """,
                (event["outbox_id"],),
            ).fetchone()

        assert row is not None
        assert row["status"] == "dead_letter"
        assert int(row["dispatch_attempts"]) == 1
        assert int(row["max_attempts"]) == 1
        assert "outbox fatal failure" in str(row["last_error"] or "")
        assert row["next_retry_at"] is None
        assert any(event_type == "OutboxDispatchDeadLetter" for event_type, _ in captured)
    finally:
        _cleanup_case_root(case_root)
