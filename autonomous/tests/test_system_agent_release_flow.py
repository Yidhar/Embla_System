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


def test_release_rollback_event_contains_canary_audit_fields() -> None:
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
                    "auto_rollback_enabled": False,
                    "rollback_command": "",
                },
            },
            repo_dir=str(repo),
        )

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
    finally:
        _cleanup_case_root(case_root)
