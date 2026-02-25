from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from scripts.release_phase3_full_signoff_chain_ws27_006 import run_release_phase3_full_signoff_chain_ws27_006


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_phase3_signoff_chain_runs_all_steps_when_runner_is_green() -> None:
    case_root = _make_case_root("test_release_phase3_full_signoff_chain_ws27_006")
    try:
        seen_commands: list[list[str]] = []

        def _runner(command, cwd, timeout):
            seen_commands.append(list(command))
            return 0, f"ok:{len(seen_commands)}", ""

        report = run_release_phase3_full_signoff_chain_ws27_006(
            repo_root=Path("."),
            output_file=case_root / "report.json",
            runner=_runner,
        )
        assert report["passed"] is True
        assert report["failed_steps"] == []
        assert report["step_count_planned"] == 3
        assert report["step_count_executed"] == 3
        assert "release_closure_chain_full_m0_m12.py" in " ".join(seen_commands[0])
        assert "validate_m12_doc_consistency_ws27_005.py" in " ".join(seen_commands[1])
        assert "generate_phase3_full_release_report_ws27_006.py" in " ".join(seen_commands[2])
    finally:
        _cleanup_case_root(case_root)


def test_phase3_signoff_chain_stops_on_first_failure_by_default() -> None:
    case_root = _make_case_root("test_release_phase3_full_signoff_chain_ws27_006")
    try:
        def _runner(command, cwd, timeout):
            text = " ".join(command)
            if "release_closure_chain_full_m0_m12.py" in text:
                return 2, "", "full chain failed"
            return 0, "ok", ""

        report = run_release_phase3_full_signoff_chain_ws27_006(
            repo_root=Path("."),
            output_file=case_root / "report.json",
            runner=_runner,
            continue_on_failure=False,
        )
        assert report["passed"] is False
        assert report["failed_steps"] == ["T0"]
        assert report["step_count_executed"] == 1
    finally:
        _cleanup_case_root(case_root)


def test_phase3_signoff_chain_forwards_wallclock_gate_flag() -> None:
    case_root = _make_case_root("test_release_phase3_full_signoff_chain_ws27_006")
    try:
        seen_commands: list[list[str]] = []

        def _runner(command, cwd, timeout):
            seen_commands.append(list(command))
            return 0, "ok", ""

        report = run_release_phase3_full_signoff_chain_ws27_006(
            repo_root=Path("."),
            output_file=case_root / "report.json",
            runner=_runner,
            require_wallclock_acceptance=True,
            skip_full_chain=True,
            skip_doc_consistency=True,
        )
        assert report["passed"] is True
        assert report["failed_steps"] == []
        assert report["step_count_executed"] == 1
        assert "--require-wallclock-acceptance" in seen_commands[0]
    finally:
        _cleanup_case_root(case_root)
