from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from scripts.export_ws26_runtime_snapshot_ws26_002 import main


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_export_ws26_runtime_snapshot_cli_main_smoke(monkeypatch) -> None:
    case_root = _make_case_root("test_export_ws26_runtime_snapshot_ws26_002")
    try:
        repo_root = case_root / "repo"
        repo_root.mkdir(parents=True, exist_ok=True)
        (repo_root / "config").mkdir(parents=True, exist_ok=True)
        (repo_root / "logs" / "autonomous").mkdir(parents=True, exist_ok=True)

        (repo_root / "config" / "autonomous_runtime.yaml").write_text(
            "\n".join(
                [
                    "autonomous:",
                    "  lease:",
                    "    lease_name: global_orchestrator",
                    "    ttl_seconds: 10",
                    "  subagent_runtime:",
                    "    rollout_percent: 80",
                    "    fail_open_budget_ratio: 0.3",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        now = datetime.now(timezone.utc)
        events = [
            {
                "timestamp": now.isoformat(),
                "event_type": "SubAgentRuntimeRolloutDecision",
                "payload": {"runtime_mode": "subagent", "decision_reason": "rollout_bucket_hit"},
            },
            {
                "timestamp": now.isoformat(),
                "event_type": "SubAgentRuntimeCompleted",
                "payload": {"runtime_id": "sar-1"},
            },
            {
                "timestamp": now.isoformat(),
                "event_type": "LeaseAcquired",
                "payload": {"fencing_epoch": 1},
            },
        ]
        (repo_root / "logs" / "autonomous" / "events.jsonl").write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in events) + "\n",
            encoding="utf-8",
        )

        output = (repo_root / "scratch" / "reports" / "ws26.json").resolve()
        monkeypatch.setattr(
            "sys.argv",
            [
                "export_ws26_runtime_snapshot_ws26_002.py",
                "--repo-root",
                str(repo_root),
                "--output",
                str(output),
            ],
        )
        exit_code = main()
        assert exit_code == 0
        assert output.exists() is True
        report = json.loads(output.read_text(encoding="utf-8"))
        assert report["task_id"] == "NGA-WS26-002"
        assert report["scenario"] == "runtime_rollout_fail_open_lease_unified_snapshot"
        assert report["checks"]["has_runtime_rollout"] is True
        assert report["checks"]["has_runtime_fail_open"] is True
        assert report["checks"]["has_runtime_lease"] is True
    finally:
        _cleanup_case_root(case_root)
