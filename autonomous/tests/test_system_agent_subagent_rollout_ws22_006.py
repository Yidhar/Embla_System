from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

from autonomous.system_agent import SystemAgent
from autonomous.tools.subagent_runtime import SubAgentRuntimeResult
from autonomous.types import OptimizationTask


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


def test_system_agent_rollout_zero_still_uses_subagent_under_subagent_only_cutover() -> None:
    case_root = _make_case_root("test_system_agent_subagent_rollout")
    try:
        repo = case_root / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        _write_policy(repo / "policy" / "gate_policy.yaml")

        agent = SystemAgent(
            config={
                "enabled": False,
                "cli_tools": {"max_retries": 0},
                "subagent_runtime": {
                    "enabled": True,
                    "rollout_percent": 0,
                    "fail_open": True,
                },
                "release": {"enabled": True, "gate_policy_path": "policy/gate_policy.yaml"},
            },
            repo_dir=str(repo),
        )

        events: list[tuple[str, dict, dict]] = []
        agent._emit = lambda event_type, payload, **kwargs: events.append((event_type, dict(payload), dict(kwargs)))  # type: ignore[method-assign]

        runtime_called = {"count": 0}

        async def _runtime_stub(**kwargs):
            runtime_called["count"] += 1
            task = kwargs["task"]
            return SubAgentRuntimeResult(
                runtime_id="sar-rollout-zero",
                workflow_id=kwargs["workflow_id"],
                task_id=task.task_id,
                trace_id=kwargs["trace_id"],
                session_id=kwargs["session_id"],
                success=True,
                approved=True,
            )

        agent.subagent_runtime.run = _runtime_stub  # type: ignore[method-assign]

        task = OptimizationTask(task_id="task-ws22-rollout-zero", instruction="subagent-only path")
        asyncio.run(agent._run_task(task, fencing_epoch=1))

        assert runtime_called["count"] == 1
        approved = [payload for event_type, payload, _ in events if event_type == "TaskApproved"]
        assert len(approved) == 1
        assert approved[0]["runtime_mode"] == "subagent"
        decisions = [payload for event_type, payload, _ in events if event_type == "SubAgentRuntimeRolloutDecision"]
        assert decisions
        assert decisions[-1]["decision_reason"] == "rollout_zero_but_subagent_only"
    finally:
        _cleanup_case_root(case_root)


def test_system_agent_task_forced_subagent_marks_forced_reason() -> None:
    case_root = _make_case_root("test_system_agent_subagent_rollout")
    try:
        repo = case_root / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        _write_policy(repo / "policy" / "gate_policy.yaml")
        target = repo / "service.txt"
        target.write_text("BASE", encoding="utf-8")

        agent = SystemAgent(
            config={
                "enabled": False,
                "cli_tools": {"max_retries": 0},
                "subagent_runtime": {
                    "enabled": True,
                    "rollout_percent": 0,
                    "fail_open": False,
                    "require_contract_negotiation": True,
                },
                "release": {"enabled": True, "gate_policy_path": "policy/gate_policy.yaml"},
            },
            repo_dir=str(repo),
        )

        events: list[tuple[str, dict, dict]] = []
        agent._emit = lambda event_type, payload, **kwargs: events.append((event_type, dict(payload), dict(kwargs)))  # type: ignore[method-assign]

        task = OptimizationTask(
            task_id="task-ws22-rollout-forced-subagent",
            instruction="force subagent path",
            metadata={
                "runtime_mode": "subagent",
                "subtasks": [
                    {
                        "subtask_id": "backend",
                        "role": "backend",
                        "instruction": "apply patch",
                        "contract_schema": {"request": {"id": "string"}},
                        "patches": [{"path": "service.txt", "content": "PATCHED"}],
                    }
                ],
            },
        )

        asyncio.run(agent._run_task(task, fencing_epoch=1))

        assert target.read_text(encoding="utf-8") == "PATCHED"
        approved = [payload for event_type, payload, _ in events if event_type == "TaskApproved"]
        assert len(approved) == 1
        assert approved[0]["runtime_mode"] == "subagent"
        decisions = [payload for event_type, payload, _ in events if event_type == "SubAgentRuntimeRolloutDecision"]
        assert decisions
        assert decisions[-1]["decision_reason"] == "task_forced_subagent"
    finally:
        _cleanup_case_root(case_root)
