from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from scripts.run_ws26_m11_runtime_chaos_suite_ws26_006 import run_ws26_m11_runtime_chaos_suite_ws26_006


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_ws26_m11_runtime_chaos_suite_runs_all_cases_when_green() -> None:
    case_root = _make_case_root("test_run_ws26_m11_runtime_chaos_suite_ws26_006")
    try:
        seen_commands: list[list[str]] = []

        def _runner(command, cwd, timeout):
            seen_commands.append(list(command))
            return 0, "ok", ""

        report = run_ws26_m11_runtime_chaos_suite_ws26_006(
            repo_root=Path("."),
            output_file=case_root / "report.json",
            runner=_runner,
        )
        assert report["passed"] is True
        assert report["failed_cases"] == []
        assert report["case_count_planned"] == 3
        assert report["case_count_executed"] == 3
        assert all("pytest" in " ".join(command) for command in seen_commands)
        assert "test_chaos_lock_failover.py" in " ".join(seen_commands[0])
        assert "test_chaos_sleep_watch.py" in " ".join(seen_commands[1])
        assert "test_process_lineage.py::test_process_lineage_kill_job_signature_runs_even_when_root_kill_succeeds" in " ".join(
            seen_commands[2]
        )
    finally:
        _cleanup_case_root(case_root)


def test_ws26_m11_runtime_chaos_suite_stops_after_case_failure() -> None:
    case_root = _make_case_root("test_run_ws26_m11_runtime_chaos_suite_ws26_006")
    try:
        def _runner(command, cwd, timeout):
            text = " ".join(command)
            if "tests/test_chaos_sleep_watch.py" in text:
                return 2, "", "sleep_watch regression"
            return 0, "ok", ""

        report = run_ws26_m11_runtime_chaos_suite_ws26_006(
            repo_root=Path("."),
            output_file=case_root / "report.json",
            runner=_runner,
            continue_on_failure=False,
        )
        assert report["passed"] is False
        assert report["failed_cases"] == ["C2"]
        assert report["case_count_executed"] == 2
    finally:
        _cleanup_case_root(case_root)
