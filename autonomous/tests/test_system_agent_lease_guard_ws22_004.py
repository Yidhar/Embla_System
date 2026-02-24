from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

from autonomous.dispatcher import DispatchResult
from autonomous.system_agent import SystemAgent
from autonomous.tools.cli_adapter import CliTaskResult
from autonomous.tools.subagent_runtime import SubAgentRuntimeResult
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


def test_system_agent_subagent_failure_without_fail_open_stays_rejected() -> None:
    case_root = _make_case_root("test_system_agent_lease_guard")
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
            task_id="task-ws22-no-fail-open",
            instruction="should be rejected",
            metadata={
                "subtasks": [
                    {
                        "subtask_id": "backend",
                        "role": "backend",
                        "instruction": "no patch",
                        "contract_schema": {"request": {"id": "string"}},
                        "patches": [],
                    }
                ]
            },
        )

        asyncio.run(agent._run_task(task, fencing_epoch=1))

        assert any(event_type == "TaskRejected" for event_type, _, _ in events)
        assert not any(event_type == "TaskApproved" for event_type, _, _ in events)
    finally:
        _cleanup_case_root(case_root)


def test_system_agent_subagent_guardrail_rejects_too_many_subtasks() -> None:
    case_root = _make_case_root("test_system_agent_lease_guard")
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
                    "fail_open": False,
                    "max_subtasks": 16,
                },
                "release": {"enabled": True, "gate_policy_path": "policy/gate_policy.yaml"},
            },
            repo_dir=str(repo),
        )

        events: list[tuple[str, dict, dict]] = []
        agent._emit = lambda event_type, payload, **kwargs: events.append((event_type, dict(payload), dict(kwargs)))  # type: ignore[method-assign]

        subtasks = []
        for idx in range(40):
            subtasks.append(
                {
                    "subtask_id": f"st-{idx}",
                    "role": "worker",
                    "instruction": f"task {idx}",
                    "patches": [{"path": f"f{idx}.txt", "content": f"v{idx}"}],
                }
            )
        task = OptimizationTask(
            task_id="task-ws22-max-subtasks",
            instruction="stress max_subtasks",
            metadata={"subtasks": subtasks},
        )

        asyncio.run(agent._run_task(task, fencing_epoch=1))
        rejected_payloads = [payload for event_type, payload, _ in events if event_type == "TaskRejected"]
        assert rejected_payloads
        assert any("max_subtasks" in " ".join(map(str, payload.get("reasons", []))) for payload in rejected_payloads)
    finally:
        _cleanup_case_root(case_root)


def test_system_agent_lease_loss_like_runtime_failure_can_fail_open_to_legacy() -> None:
    case_root = _make_case_root("test_system_agent_lease_guard")
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
                },
                "release": {"enabled": True, "gate_policy_path": "policy/gate_policy.yaml"},
            },
            repo_dir=str(repo),
        )

        async def _runtime_fail(**kwargs):
            task = kwargs["task"]
            return SubAgentRuntimeResult(
                runtime_id="sar-lease-fail",
                workflow_id=kwargs["workflow_id"],
                task_id=task.task_id,
                trace_id=kwargs["trace_id"],
                session_id=kwargs["session_id"],
                success=False,
                approved=False,
                gate_failure="runtime",
                reasons=["lease_lost_during_subtask_dispatch"],
                fail_open_recommended=True,
            )

        agent.subagent_runtime.run = _runtime_fail  # type: ignore[method-assign]

        async def _dispatch_ok(task: OptimizationTask) -> DispatchResult:
            return DispatchResult(
                selected_cli="codex",
                result=CliTaskResult(
                    task_id=task.task_id,
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

        events: list[tuple[str, dict, dict]] = []
        agent._emit = lambda event_type, payload, **kwargs: events.append((event_type, dict(payload), dict(kwargs)))  # type: ignore[method-assign]

        task = OptimizationTask(task_id="task-ws22-lease-fail-open", instruction="lease-fail-open")
        asyncio.run(agent._run_task(task, fencing_epoch=1))

        assert any(event_type == "SubAgentRuntimeFailOpen" for event_type, _, _ in events)
        assert any(event_type == "TaskApproved" for event_type, _, _ in events)
    finally:
        _cleanup_case_root(case_root)
