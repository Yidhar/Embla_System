from __future__ import annotations

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


def test_system_agent_emit_publishes_into_topic_bus_ws25_001() -> None:
    case_root = _make_case_root("test_system_agent_topic_bus_ws25_001")
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

        agent._emit("WatchdogThresholdExceeded", {"workflow_id": "wf-topic", "trace_id": "trace-topic", "cpu_percent": 95.0})
        topic_rows = agent.event_store.replay_by_topic(topic_pattern="system.*", limit=20)
        assert any(str(item.get("event_type") or "") == "WatchdogThresholdExceeded" for item in topic_rows)
        assert any(str(item.get("topic") or "").startswith("system.") for item in topic_rows)
    finally:
        _cleanup_case_root(case_root)
