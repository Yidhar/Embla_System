from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

from autonomous.system_agent import SystemAgent


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


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


def test_system_agent_run_cycle_uses_meta_agent_and_gc_pipeline_ws28_032() -> None:
    case_root = _make_case_root("test_system_agent_meta_planner_ws28_032")
    try:
        repo = case_root / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        _write_policy(repo / "policy" / "gate_policy.yaml")

        agent = SystemAgent(
            config={
                "enabled": False,
                "lease": {"enabled": False},
                "memory_gc": {"enabled": True, "dry_run": True},
                "release": {"enabled": True, "gate_policy_path": "policy/gate_policy.yaml"},
            },
            repo_dir=str(repo),
        )

        agent.sensor.scan_codebase = lambda: [  # type: ignore[method-assign]
            {"kind": "test_gap", "severity": "medium", "summary": "add regression checks"}
        ]
        agent.sensor.scan_logs = lambda: []  # type: ignore[method-assign]

        async def _fake_run_task(task, *, fencing_epoch: int):  # type: ignore[no-untyped-def]
            workflow_id = f"wf-{task.task_id}"
            agent.workflow_store.create_workflow(
                workflow_id=workflow_id,
                task_id=task.task_id,
                initial_state="GoalAccepted",
                max_retries=agent.config.max_retries,
            )
            agent.workflow_store.transition(workflow_id, "ReleaseCandidate", reason="meta_test_approved")
            _ = fencing_epoch

        agent._run_task = _fake_run_task  # type: ignore[method-assign]

        events: list[str] = []

        def _capture(event_type: str, payload: dict, **kwargs) -> None:  # type: ignore[no-untyped-def]
            _ = (payload, kwargs)
            events.append(event_type)

        agent._emit = _capture  # type: ignore[method-assign]

        asyncio.run(agent.run_cycle(fencing_epoch=1))

        assert "MetaAgentGoalAccepted" in events
        assert "MetaAgentReflectionUpdated" in events
        assert "MemoryGCPipelineCompleted" in events
    finally:
        _cleanup_case_root(case_root)

