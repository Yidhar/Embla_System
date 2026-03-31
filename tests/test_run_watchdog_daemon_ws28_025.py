from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from scripts.run_watchdog_daemon_ws28_025 import main


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_run_watchdog_daemon_ws28_025_cli_run_and_status(monkeypatch) -> None:
    case_root = _make_case_root("test_run_watchdog_daemon_ws28_025")
    try:
        state_file = case_root / "watchdog_state.json"
        output_run = case_root / "watchdog_run_report.json"
        output_status = case_root / "watchdog_status_report.json"

        monkeypatch.setattr(
            "sys.argv",
            [
                "run_watchdog_daemon_ws28_025.py",
                "--repo-root",
                ".",
                "--mode",
                "run",
                "--state-file",
                str(state_file),
                "--output",
                str(output_run),
                "--interval-seconds",
                "0",
                "--max-ticks",
                "1",
                "--strict",
            ],
        )
        exit_code = main()
        assert exit_code == 0
        run_payload = json.loads(output_run.read_text(encoding="utf-8"))
        assert run_payload["passed"] is True
        assert run_payload["checks"]["state_file_exists"] is True

        monkeypatch.setattr(
            "sys.argv",
            [
                "run_watchdog_daemon_ws28_025.py",
                "--repo-root",
                ".",
                "--mode",
                "status",
                "--state-file",
                str(state_file),
                "--output",
                str(output_status),
                "--strict",
            ],
        )
        exit_code = main()
        assert exit_code == 0
        status_payload = json.loads(output_status.read_text(encoding="utf-8"))
        assert status_payload["passed"] is True
        assert status_payload["checks"]["state_status_known"] is True
    finally:
        _cleanup_case_root(case_root)
