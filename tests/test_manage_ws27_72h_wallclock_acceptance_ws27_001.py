from __future__ import annotations

import json
import time
from pathlib import Path

from scripts.manage_ws27_72h_wallclock_acceptance_ws27_001 import (
    finish_wallclock_acceptance,
    start_wallclock_acceptance,
    status_wallclock_acceptance,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_start_wallclock_acceptance_creates_running_state(tmp_path: Path) -> None:
    state = tmp_path / "ws27_state.json"
    result = start_wallclock_acceptance(
        repo_root=tmp_path,
        state_file=state,
        target_hours=72.0,
    )
    assert result["status"] == "running"
    assert state.exists()


def test_finish_wallclock_acceptance_fails_when_target_not_reached(tmp_path: Path) -> None:
    state = tmp_path / "ws27_state.json"
    output = tmp_path / "ws27_report.json"
    start_wallclock_acceptance(
        repo_root=tmp_path,
        state_file=state,
        target_hours=72.0,
    )
    result = finish_wallclock_acceptance(
        repo_root=tmp_path,
        state_file=state,
        output_file=output,
        required_reports=[],
    )
    assert result["passed"] is False
    assert result["checks"]["wallclock_target_reached"] is False


def test_finish_wallclock_acceptance_passes_with_elapsed_target_and_reports(tmp_path: Path) -> None:
    state = tmp_path / "ws27_state.json"
    output = tmp_path / "ws27_report.json"
    required_report = tmp_path / "required.json"
    required_report.write_text("{}\n", encoding="utf-8")

    started_epoch = time.time() - (73 * 3600)
    _write_json(
        state,
        {
            "task_id": "NGA-WS27-001",
            "scenario": "ws27_72h_wallclock_acceptance",
            "status": "running",
            "started_at": "2026-02-20T00:00:00+00:00",
            "started_epoch": started_epoch,
            "target_hours": 72.0,
        },
    )

    result = finish_wallclock_acceptance(
        repo_root=tmp_path,
        state_file=state,
        output_file=output,
        required_reports=[required_report],
    )
    assert result["passed"] is True
    assert result["checks"]["wallclock_target_reached"] is True
    assert result["checks"]["required_reports_present"] is True

    status = status_wallclock_acceptance(
        repo_root=tmp_path,
        state_file=state,
    )
    assert status["status"] == "finished"
