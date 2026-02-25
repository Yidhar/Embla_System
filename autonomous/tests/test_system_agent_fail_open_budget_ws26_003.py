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


def _build_dispatch_result(task_id: str) -> DispatchResult:
    return DispatchResult(
        selected_cli="codex",
        result=CliTaskResult(
            task_id=task_id,
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


def test_fail_open_budget_exhausted_auto_degrades_non_write_tasks_to_legacy() -> None:
    case_root = _make_case_root("test_system_agent_fail_open_budget_ws26_003")
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
                    "rollout_percent": 100,
                    "fail_open": True,
                    "fail_open_budget_ratio": 0.4,
                },
                "release": {"enabled": True, "gate_policy_path": "policy/gate_policy.yaml"},
            },
            repo_dir=str(repo),
        )

        runtime_called = {"count": 0}
        alert_calls: list[dict] = []
        events: list[tuple[str, dict, dict]] = []
        agent._emit = lambda event_type, payload, **kwargs: events.append((event_type, dict(payload), dict(kwargs)))  # type: ignore[method-assign]

        def _emit_alert(**kwargs):
            alert_calls.append(dict(kwargs))

        agent.alert_event_producer.emit_alert = _emit_alert  # type: ignore[method-assign]

        async def _runtime_fail_open(**kwargs):
            runtime_called["count"] += 1
            task = kwargs["task"]
            return SubAgentRuntimeResult(
                runtime_id=f"sar-{runtime_called['count']}",
                workflow_id=kwargs["workflow_id"],
                task_id=task.task_id,
                trace_id=kwargs["trace_id"],
                session_id=kwargs["session_id"],
                success=False,
                approved=False,
                gate_failure="scaffold",
                reasons=["scaffold_apply_failed"],
                fail_open_recommended=True,
            )

        async def _dispatch_ok(task: OptimizationTask) -> DispatchResult:
            return _build_dispatch_result(task.task_id)

        agent.subagent_runtime.run = _runtime_fail_open  # type: ignore[method-assign]
        agent.dispatcher.dispatch = _dispatch_ok  # type: ignore[method-assign]
        agent.evaluator.evaluate = lambda task, result: EvaluationReport(approved=True)  # type: ignore[method-assign]

        first_task = OptimizationTask(task_id="task-ws26-budget-1", instruction="first non-write task")
        asyncio.run(agent._run_task(first_task, fencing_epoch=1))

        second_task = OptimizationTask(task_id="task-ws26-budget-2", instruction="second non-write task")
        asyncio.run(agent._run_task(second_task, fencing_epoch=1))

        assert runtime_called["count"] == 1
        decisions = [payload for event_type, payload, _ in events if event_type == "SubAgentRuntimeRolloutDecision"]
        assert len(decisions) >= 2
        assert decisions[-1].get("runtime_mode") == "legacy"
        assert decisions[-1].get("decision_reason") == "fail_open_budget_exhausted_auto_degrade"
        assert any(event_type == "SubAgentRuntimeAutoDegraded" for event_type, _, _ in events)
        assert any(
            event_type == "ReleaseGateRejected" and payload.get("gate") == "fail_open_budget"
            for event_type, payload, _ in events
        )
        assert alert_calls
        assert str(alert_calls[-1].get("alert_key")) == "subagent_fail_open_budget_exhausted"
    finally:
        _cleanup_case_root(case_root)


def test_fail_open_budget_auto_degrade_keeps_write_tasks_on_subagent_path() -> None:
    case_root = _make_case_root("test_system_agent_fail_open_budget_ws26_003")
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
                    "rollout_percent": 100,
                    "fail_open": True,
                    "fail_open_budget_ratio": 0.4,
                },
                "release": {"enabled": True, "gate_policy_path": "policy/gate_policy.yaml"},
            },
            repo_dir=str(repo),
        )

        runtime_calls: list[str] = []
        events: list[tuple[str, dict, dict]] = []
        agent._emit = lambda event_type, payload, **kwargs: events.append((event_type, dict(payload), dict(kwargs)))  # type: ignore[method-assign]

        async def _runtime_stub(**kwargs):
            task = kwargs["task"]
            runtime_calls.append(task.task_id)
            if task.task_id == "task-ws26-degrade-trigger":
                return SubAgentRuntimeResult(
                    runtime_id="sar-fail-open",
                    workflow_id=kwargs["workflow_id"],
                    task_id=task.task_id,
                    trace_id=kwargs["trace_id"],
                    session_id=kwargs["session_id"],
                    success=False,
                    approved=False,
                    gate_failure="runtime",
                    reasons=["runtime_unavailable"],
                    fail_open_recommended=True,
                )
            return SubAgentRuntimeResult(
                runtime_id="sar-write-ok",
                workflow_id=kwargs["workflow_id"],
                task_id=task.task_id,
                trace_id=kwargs["trace_id"],
                session_id=kwargs["session_id"],
                success=True,
                approved=True,
            )

        async def _dispatch_ok(task: OptimizationTask) -> DispatchResult:
            return _build_dispatch_result(task.task_id)

        agent.subagent_runtime.run = _runtime_stub  # type: ignore[method-assign]
        agent.dispatcher.dispatch = _dispatch_ok  # type: ignore[method-assign]
        agent.evaluator.evaluate = lambda task, result: EvaluationReport(approved=True)  # type: ignore[method-assign]

        degrade_task = OptimizationTask(task_id="task-ws26-degrade-trigger", instruction="trigger degrade")
        asyncio.run(agent._run_task(degrade_task, fencing_epoch=1))

        write_task = OptimizationTask(
            task_id="task-ws26-write-still-subagent",
            instruction="write task keeps subagent",
            metadata={
                "subtasks": [
                    {
                        "subtask_id": "backend",
                        "role": "backend",
                        "instruction": "write patch",
                        "contract_schema": {"request": {"id": "string"}},
                        "patches": [{"path": "service.txt", "content": "PATCHED"}],
                    }
                ]
            },
        )
        asyncio.run(agent._run_task(write_task, fencing_epoch=1))

        assert runtime_calls == ["task-ws26-degrade-trigger", "task-ws26-write-still-subagent"]
        write_decisions = [
            payload
            for event_type, payload, _ in events
            if event_type == "SubAgentRuntimeRolloutDecision" and payload.get("task_id") == "task-ws26-write-still-subagent"
        ]
        assert write_decisions
        assert write_decisions[-1].get("runtime_mode") == "subagent"
        assert write_decisions[-1].get("decision_reason") == "write_path_enforced"
    finally:
        _cleanup_case_root(case_root)
