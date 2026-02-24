from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

from autonomous.dispatcher import DispatchResult
from autonomous.system_agent import SystemAgent
from autonomous.tools.cli_adapter import CliTaskResult
from autonomous.types import EvaluationReport, OptimizationTask


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


def test_system_agent_subagent_bridge_approves_task_via_scaffold_runtime() -> None:
    case_root = _make_case_root("test_system_agent_subagent_bridge")
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
                    "fail_open": True,
                    "require_contract_negotiation": True,
                },
                "release": {
                    "enabled": True,
                    "gate_policy_path": "policy/gate_policy.yaml",
                    "auto_rollback_enabled": False,
                },
            },
            repo_dir=str(repo),
        )

        events: list[tuple[str, dict, dict]] = []

        def _capture(event_type: str, payload: dict, **kwargs) -> None:
            events.append((event_type, dict(payload), dict(kwargs)))

        agent._emit = _capture  # type: ignore[method-assign]

        task = OptimizationTask(
            task_id="task-ws22-bridge-approve",
            instruction="patch service file",
            metadata={
                "subtasks": [
                    {
                        "subtask_id": "backend",
                        "role": "backend",
                        "instruction": "apply patch",
                        "contract_schema": {"request": {"id": "string"}},
                        "patches": [{"path": "service.txt", "content": "PATCHED"}],
                    }
                ]
            },
        )

        asyncio.run(agent._run_task(task, fencing_epoch=1))

        assert target.read_text(encoding="utf-8") == "PATCHED"
        assert any(event_type == "SubTaskApproved" for event_type, _, _ in events)
        approved = [payload for event_type, payload, _ in events if event_type == "TaskApproved"]
        assert len(approved) == 1
        assert approved[0].get("subagent_runtime_id")
    finally:
        _cleanup_case_root(case_root)


def test_system_agent_subagent_fail_open_falls_back_to_legacy_attempt() -> None:
    case_root = _make_case_root("test_system_agent_subagent_bridge")
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
                    "fail_open": True,
                    "require_contract_negotiation": True,
                },
                "release": {
                    "enabled": True,
                    "gate_policy_path": "policy/gate_policy.yaml",
                    "auto_rollback_enabled": False,
                },
            },
            repo_dir=str(repo),
        )

        events: list[tuple[str, dict, dict]] = []

        def _capture(event_type: str, payload: dict, **kwargs) -> None:
            events.append((event_type, dict(payload), dict(kwargs)))

        agent._emit = _capture  # type: ignore[method-assign]

        async def _dispatch_ok(_task: OptimizationTask) -> DispatchResult:
            return DispatchResult(
                selected_cli="codex",
                result=CliTaskResult(
                    task_id=_task.task_id,
                    cli_name="codex",
                    exit_code=0,
                    stdout="ok",
                    stderr="",
                    files_changed=[],
                    duration_seconds=0.1,
                    success=True,
                    execution_snapshots=[],
                ),
            )

        agent.dispatcher.dispatch = _dispatch_ok  # type: ignore[method-assign]
        agent.evaluator.evaluate = lambda task, result: EvaluationReport(approved=True)  # type: ignore[method-assign]

        # No patches -> scaffold gate fail -> fail_open -> legacy success
        task = OptimizationTask(
            task_id="task-ws22-fail-open",
            instruction="fallback to legacy",
            metadata={
                "subtasks": [
                    {
                        "subtask_id": "backend",
                        "role": "backend",
                        "instruction": "no patch intent",
                        "contract_schema": {"request": {"id": "string"}},
                        "patches": [],
                    }
                ]
            },
        )

        asyncio.run(agent._run_task(task, fencing_epoch=1))

        assert any(event_type == "SubAgentRuntimeFailOpen" for event_type, _, _ in events)
        assert any(event_type == "SubAgentGateMetricUpdated" for event_type, _, _ in events)
        assert any(event_type == "TaskApproved" for event_type, _, _ in events)
    finally:
        _cleanup_case_root(case_root)
