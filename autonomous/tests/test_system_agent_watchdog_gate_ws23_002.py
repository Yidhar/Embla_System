from __future__ import annotations

import asyncio
import json
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
        assert all(event_type != "TaskExecutionCompleted" for event_type, _, _ in events)
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

        runtime_called = {"value": False}

        async def _runtime_ok(**kwargs):
            runtime_called["value"] = True
            task = kwargs["task"]
            return SubAgentRuntimeResult(
                runtime_id="sar-watchdog-warn-only",
                workflow_id=kwargs["workflow_id"],
                task_id=task.task_id,
                trace_id=kwargs["trace_id"],
                session_id=kwargs["session_id"],
                success=True,
                approved=True,
            )

        agent.subagent_runtime.run = _runtime_ok  # type: ignore[method-assign]

        events: list[tuple[str, dict, dict]] = []
        agent._emit = lambda event_type, payload, **kwargs: events.append((event_type, dict(payload), dict(kwargs)))  # type: ignore[method-assign]

        task = OptimizationTask(task_id="task-ws23-watchdog-warn-only", instruction="watchdog warn only")
        asyncio.run(agent._run_task(task, fencing_epoch=1))

        assert runtime_called["value"] is True
        assert any(event_type == "WatchdogThresholdExceeded" for event_type, _, _ in events)
        assert any(event_type == "TaskApproved" for event_type, _, _ in events)
        assert all(
            not (event_type == "ReleaseGateRejected" and str(payload.get("gate")) == "watchdog")
            for event_type, payload, _ in events
        )
    finally:
        _cleanup_case_root(case_root)


def test_system_agent_watchdog_consumes_daemon_state_file_and_blocks_without_run_once() -> None:
    case_root = _make_case_root("test_system_agent_watchdog_gate_ws23_002")
    try:
        repo = case_root / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        _write_policy(repo / "policy" / "gate_policy.yaml")
        state_file = repo / "scratch" / "runtime" / "watchdog_daemon_state_ws28_025.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps(
                {
                    "generated_at": "2026-02-27T10:00:00+00:00",
                    "pid": 52001,
                    "mode": "daemon",
                    "tick": 7,
                    "warn_only": False,
                    "threshold_hit": True,
                    "status": "critical",
                    "snapshot": {"cpu_percent": 97.0},
                    "action": {
                        "level": "critical",
                        "action": "pause_dispatch_and_escalate",
                        "reasons": ["cpu_percent=97.00>=80.00"],
                        "snapshot": {"cpu_percent": 97.0},
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        agent = SystemAgent(
            config={
                "enabled": False,
                "cli_tools": {"max_retries": 0},
                "lease": {"enabled": False},
                "subagent_runtime": {"enabled": False},
                "watchdog": {
                    "enabled": True,
                    "warn_only": False,
                    "prefer_daemon_state": True,
                    "daemon_state_file": "scratch/runtime/watchdog_daemon_state_ws28_025.json",
                },
                "release": {"enabled": True, "gate_policy_path": "policy/gate_policy.yaml"},
            },
            repo_dir=str(repo),
        )

        assert agent.watchdog_daemon is not None
        agent.watchdog_daemon.run_once = lambda: (_ for _ in ()).throw(AssertionError("run_once should not be called"))  # type: ignore[method-assign]

        events: list[tuple[str, dict, dict]] = []
        agent._emit = lambda event_type, payload, **kwargs: events.append((event_type, dict(payload), dict(kwargs)))  # type: ignore[method-assign]

        task = OptimizationTask(task_id="task-ws23-watchdog-daemon-block", instruction="watchdog daemon gate block test")
        asyncio.run(agent._run_task(task, fencing_epoch=1))

        consumed = [payload for event_type, payload, _ in events if event_type == "WatchdogDaemonStateConsumed"]
        assert len(consumed) == 1
        assert consumed[0]["status"] == "critical"
        gate_rejected = [payload for event_type, payload, _ in events if event_type == "ReleaseGateRejected"]
        assert len(gate_rejected) == 1
        assert gate_rejected[0]["gate"] == "watchdog"
        assert gate_rejected[0]["watchdog_action"] == "pause_dispatch_and_escalate"
    finally:
        _cleanup_case_root(case_root)
