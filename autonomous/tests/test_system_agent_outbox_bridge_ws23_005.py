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


def test_outbox_dispatch_emits_brainstem_bridge_event_with_metadata() -> None:
    case_root = _make_case_root("test_system_agent_outbox_bridge_ws23_005")
    try:
        repo = case_root / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        _write_policy(repo / "policy" / "gate_policy.yaml")
        agent = _create_agent(repo)

        workflow_id = "wf-outbox-bridge"
        agent.workflow_store.create_workflow(workflow_id, task_id="task-outbox-bridge", initial_state="ReleaseCandidate")
        outbox_id = agent.workflow_store.enqueue_outbox(
            workflow_id,
            "ChangePromoted",
            {
                "workflow_id": workflow_id,
                "task_id": "task-outbox-bridge",
                "session_id": "session-outbox-bridge",
                "trace_id": "trace-outbox-bridge",
            },
            max_attempts=3,
        )
        event = agent.workflow_store.read_pending_outbox(limit=10)[0]
        assert int(event["outbox_id"]) == int(outbox_id)

        captured: list[tuple[str, dict, dict]] = []

        def _capture(event_type: str, payload: dict, **kwargs) -> None:
            captured.append((event_type, dict(payload), dict(kwargs)))

        agent._emit = _capture  # type: ignore[method-assign]
        asyncio.run(agent._dispatch_single_outbox_event(event, consumer="release-controller", fencing_epoch=1))

        bridged = [payload for event_type, payload, _ in captured if event_type == "BrainstemEventBridged"]
        assert len(bridged) == 1
        bridge_payload = bridged[0]
        assert bridge_payload["outbox_id"] == int(outbox_id)
        assert bridge_payload["workflow_id"] == workflow_id
        assert bridge_payload["event_type"] == "ChangePromoted"
        assert bridge_payload["task_id"] == "task-outbox-bridge"
        assert bridge_payload["trace_id"] == "trace-outbox-bridge"
        assert bridge_payload["session_id"] == "session-outbox-bridge"
        assert bridge_payload["consumer"] == "release-controller"
        assert bridge_payload["event_id"]
        assert bridge_payload["idempotency_key"]
        assert bridge_payload["event_timestamp"]
        assert bridge_payload["dispatch_attempts"] == 0
        assert bridge_payload["max_attempts"] == 3
        assert isinstance(bridge_payload["event_payload"], dict)
        assert isinstance(bridge_payload["event_envelope"], dict)

        event_types = [event_type for event_type, _, _ in captured]
        assert "OutboxNoop" in event_types
        assert "OutboxDispatched" in event_types
    finally:
        _cleanup_case_root(case_root)


def test_outbox_dedup_hit_skips_brainstem_bridge_event() -> None:
    case_root = _make_case_root("test_system_agent_outbox_bridge_ws23_005")
    try:
        repo = case_root / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        _write_policy(repo / "policy" / "gate_policy.yaml")
        agent = _create_agent(repo)

        workflow_id = "wf-outbox-dedup"
        agent.workflow_store.create_workflow(workflow_id, task_id="task-outbox-dedup", initial_state="ReleaseCandidate")
        outbox_id = agent.workflow_store.enqueue_outbox(
            workflow_id,
            "ChangePromoted",
            {"workflow_id": workflow_id, "task_id": "task-outbox-dedup"},
            max_attempts=2,
        )
        event = agent.workflow_store.read_pending_outbox(limit=10)[0]
        with agent.workflow_store._connect() as conn:  # noqa: SLF001
            conn.execute(
                """
                INSERT OR IGNORE INTO inbox_dedup
                (consumer, message_id, processed_at)
                VALUES (?, ?, ?)
                """,
                ("release-controller", str(outbox_id), "2026-02-25T12:00:00+00:00"),
            )
            conn.commit()

        captured: list[tuple[str, dict, dict]] = []

        def _capture(event_type: str, payload: dict, **kwargs) -> None:
            captured.append((event_type, dict(payload), dict(kwargs)))

        agent._emit = _capture  # type: ignore[method-assign]
        asyncio.run(agent._dispatch_single_outbox_event(event, consumer="release-controller", fencing_epoch=1))

        event_types = [event_type for event_type, _, _ in captured]
        assert "OutboxDedupHit" in event_types
        assert "BrainstemEventBridged" not in event_types
    finally:
        _cleanup_case_root(case_root)

