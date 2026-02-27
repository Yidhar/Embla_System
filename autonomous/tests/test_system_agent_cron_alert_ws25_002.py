from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

from autonomous.system_agent import SystemAgent
from autonomous.types import OptimizationTask


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


def test_system_agent_run_cycle_publishes_cron_topic_event_ws25_002() -> None:
    case_root = _make_case_root("test_system_agent_cron_alert_ws25_002")
    try:
        repo = case_root / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        _write_policy(repo / "policy" / "gate_policy.yaml")

        agent = SystemAgent(
            config={
                "enabled": False,
                "lease": {"enabled": False},
                "release": {"enabled": True, "gate_policy_path": "policy/gate_policy.yaml"},
            },
            repo_dir=str(repo),
        )

        agent.sensor.scan_codebase = lambda: []  # type: ignore[method-assign]
        agent.sensor.scan_logs = lambda: []  # type: ignore[method-assign]
        agent.planner.generate_tasks = lambda findings: []  # type: ignore[method-assign]

        asyncio.run(agent.run_cycle(fencing_epoch=1))
        cron_rows = agent.event_store.replay_by_topic(topic_pattern="cron.system_agent.*", limit=20)
        assert any(str(item.get("event_type") or "") == "CronScheduleTriggered" for item in cron_rows)
    finally:
        _cleanup_case_root(case_root)


def test_watchdog_gate_publishes_alert_topic_event_ws25_002() -> None:
    case_root = _make_case_root("test_system_agent_cron_alert_ws25_002")
    try:
        repo = case_root / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        _write_policy(repo / "policy" / "gate_policy.yaml")

        agent = SystemAgent(
            config={
                "enabled": False,
                "lease": {"enabled": False},
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

        outcome = agent._evaluate_watchdog_gate(
            task=OptimizationTask(task_id="task-alert", instruction="watchdog alert"),
            workflow_id="wf-alert",
            attempt=1,
            runtime_mode="subagent",
            fencing_epoch=1,
        )
        assert outcome is not None
        assert outcome.approved is False

        alert_rows = agent.event_store.replay_by_topic(topic_pattern="alert.watchdog", limit=20)
        assert len(alert_rows) >= 1
        assert any(str(item.get("event_type") or "") == "AlertRaised" for item in alert_rows)
    finally:
        _cleanup_case_root(case_root)
