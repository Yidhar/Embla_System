from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from scripts.run_ws27_oob_repair_drill_ws27_003 import main, run_ws27_oob_repair_drill_ws27_003


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_run_ws27_oob_repair_drill_function_path_generates_report() -> None:
    case_root = _make_case_root("test_run_ws27_oob_repair_drill_ws27_003")
    try:
        repo_root = case_root / "repo"
        output = repo_root / "scratch" / "reports" / "ws27_oob_repair_drill.json"
        report = run_ws27_oob_repair_drill_ws27_003(
            repo_root=repo_root,
            output_file=Path("scratch/reports/ws27_oob_repair_drill.json"),
            scratch_root=Path("scratch/ws27_oob_repair_drill"),
            rollback_window_minutes=90,
            oob_allowlist=["10.0.0.0/24", "bastion.example.com"],
            probe_targets=["10.0.0.10", "bastion.example.com"],
        )
        assert report["task_id"] == "NGA-WS27-003"
        assert report["passed"] is True
        assert report["case_count_planned"] == 3
        assert report["case_count_executed"] == 3
        checks = report["checks"]
        assert checks["snapshot_recovery_path"] is True
        assert checks["safe_baseline_without_snapshot_path"] is True
        assert checks["oob_bundle_validation_path"] is True
        case_results = report["case_results"]
        assert len(case_results) == 3
        assert all(bool(item.get("passed")) for item in case_results)
        assert output.exists() is True

        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["passed"] is True
    finally:
        _cleanup_case_root(case_root)


def test_run_ws27_oob_repair_drill_cli_main_smoke(monkeypatch) -> None:
    case_root = _make_case_root("test_run_ws27_oob_repair_drill_ws27_003_cli")
    try:
        repo_root = case_root / "repo"
        output = repo_root / "scratch" / "reports" / "ws27_oob_repair_drill_cli.json"
        monkeypatch.setattr(
            "sys.argv",
            [
                "run_ws27_oob_repair_drill_ws27_003.py",
                "--repo-root",
                str(repo_root),
                "--output",
                "scratch/reports/ws27_oob_repair_drill_cli.json",
                "--scratch-root",
                "scratch/ws27_oob_repair_drill_cli",
                "--rollback-window-minutes",
                "60",
                "--oob-allowlist",
                "10.0.0.0/24",
                "bastion.example.com",
                "--probe-targets",
                "10.0.0.10",
                "bastion.example.com",
            ],
        )
        exit_code = main()
        assert exit_code == 0
        assert output.exists() is True
    finally:
        _cleanup_case_root(case_root)
