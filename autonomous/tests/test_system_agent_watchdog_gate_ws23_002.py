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


def test_system_agent_watchdog_critical_action_blocks_dispatch_and_rejects_task() -> None:
    case_root = _make_case_root("test_system_agent_watchdog_gate_ws23_002")
    try:
        repo = case_root / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        _write_policy(repo / "policy" / "gate_policy.yaml")
        agent = SystemAgent(
            config={
                "enabled": False,
                "cli_tools": {"max_retries": 0},
                "lease": {"enabled": False},
                "subagent_runtime": {"enabled": False},
                "watchdog": {
                    "enabled": True,
                    "warn_only": False,
                    "cpu_percent": 80.0,
                    "memory_percent": 80.0,
                    "disk_percent": 90.0,
                    "io_read_bps": 10.0,
                    "io_write_bps": 10.0,
                    "cost_per_hour": 1.0,
                },
                "release": {"enabled": True, "gate_policy_path": "policy/gate_policy.yaml"},
            },
            repo_dir=str(repo),
        )

        assert agent.watchdog_daemon is not None
        agent.watchdog_daemon.metrics_provider = lambda: {
            "cpu_percent": 97.0,
            "memory_percent": 92.0,
            "disk_percent": 96.0,
            "io_read_bps": 200.0,
            "io_write_bps": 300.0,
            "cost_per_hour": 2.0,
        }

        async def _dispatch_should_not_run(_task: OptimizationTask) -> DispatchResult:
            raise AssertionError("dispatch should not run when watchdog blocks")

        agent.dispatcher.dispatch = _dispatch_should_not_run  # type: ignore[method-assign]

        events: list[tuple[str, dict, dict]] = []
        agent._emit = lambda event_type, payload, **kwargs: events.append((event_type, dict(payload), dict(kwargs)))  # type: ignore[method-assign]

        task = OptimizationTask(task_id="task-ws23-watchdog-block", instruction="watchdog gate block test")
        asyncio.run(agent._run_task(task, fencing_epoch=1))

        assert any(event_type == "WatchdogThresholdExceeded" for event_type, _, _ in events)
        gate_rejected = [payload for event_type, payload, _ in events if event_type == "ReleaseGateRejected"]
        assert len(gate_rejected) == 1
        assert gate_rejected[0]["gate"] == "watchdog"
        assert gate_rejected[0]["watchdog_action"] == "pause_dispatch_and_escalate"

        task_rejected = [payload for event_type, payload, _ in events if event_type == "TaskRejected"]
        assert len(task_rejected) == 1
        assert "watchdog:pause_dispatch_and_escalate" in task_rejected[0]["reasons"]
        assert all(event_type != "CliExecutionCompleted" for event_type, _, _ in events)
    finally:
        _cleanup_case_root(case_root)


def test_system_agent_watchdog_warn_only_emits_alert_but_keeps_dispatch() -> None:
    case_root = _make_case_root("test_system_agent_watchdog_gate_ws23_002")
    try:
        repo = case_root / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        _write_policy(repo / "policy" / "gate_policy.yaml")
        agent = SystemAgent(
            config={
                "enabled": False,
                "cli_tools": {"max_retries": 0},
                "lease": {"enabled": False},
                "subagent_runtime": {"enabled": False},
                "watchdog": {
                    "enabled": True,
                    "warn_only": True,
                    "cpu_percent": 80.0,
                    "memory_percent": 80.0,
                    "disk_percent": 90.0,
                    "io_read_bps": 10.0,
                    "io_write_bps": 10.0,
                    "cost_per_hour": 1.0,
                },
                "release": {"enabled": True, "gate_policy_path": "policy/gate_policy.yaml"},
            },
            repo_dir=str(repo),
        )

        assert agent.watchdog_daemon is not None
        agent.watchdog_daemon.metrics_provider = lambda: {
            "cpu_percent": 82.0,
            "memory_percent": 84.0,
            "disk_percent": 92.0,
            "io_read_bps": 20.0,
            "io_write_bps": 30.0,
            "cost_per_hour": 1.2,
        }

        dispatch_called = {"value": False}

        async def _dispatch_ok(task: OptimizationTask) -> DispatchResult:
            dispatch_called["value"] = True
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

        task = OptimizationTask(task_id="task-ws23-watchdog-warn-only", instruction="watchdog warn only")
        asyncio.run(agent._run_task(task, fencing_epoch=1))

        assert dispatch_called["value"] is True
        assert any(event_type == "WatchdogThresholdExceeded" for event_type, _, _ in events)
        assert any(event_type == "TaskApproved" for event_type, _, _ in events)
        assert all(
            not (event_type == "ReleaseGateRejected" and str(payload.get("gate")) == "watchdog")
            for event_type, payload, _ in events
        )
    finally:
        _cleanup_case_root(case_root)
