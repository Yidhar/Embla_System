from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from scripts.release_closure_chain_m9_ws24_006 import run_release_closure_chain_m9_ws24_006


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_m9_release_chain_runs_all_steps_when_runner_is_green() -> None:
    case_root = _make_case_root("test_release_closure_chain_m9_ws24_006")
    try:
        seen_commands: list[list[str]] = []

        def _runner(command, cwd, timeout):
            seen_commands.append(list(command))
            return 0, f"ok:{len(seen_commands)}", ""

        report = run_release_closure_chain_m9_ws24_006(
            repo_root=Path("."),
            output_file=case_root / "report.json",
            runner=_runner,
        )
        assert report["passed"] is True
        assert report["failed_steps"] == []
        assert report["step_count_planned"] == 4
        assert report["step_count_executed"] == 4
        assert "pytest" in " ".join(seen_commands[0])
        assert "run_plugin_isolation_chaos_suite_ws24_005.py" in " ".join(seen_commands[1])
        assert "validate_m9_closure_gate_ws24_006.py" in " ".join(seen_commands[2])
        assert "validate_doc_consistency_ws16_006.py" in " ".join(seen_commands[3])
    finally:
        _cleanup_case_root(case_root)


def test_m9_release_chain_stops_on_first_failure_by_default() -> None:
    case_root = _make_case_root("test_release_closure_chain_m9_ws24_006")
    try:
        def _runner(command, cwd, timeout):
            text = " ".join(command)
            if "scripts/run_plugin_isolation_chaos_suite_ws24_005.py" in text:
                return 2, "", "chaos suite failed"
            return 0, "ok", ""

        report = run_release_closure_chain_m9_ws24_006(
            repo_root=Path("."),
            output_file=case_root / "report.json",
            runner=_runner,
            continue_on_failure=False,
        )
        assert report["passed"] is False
        assert report["failed_steps"] == ["T1"]
        assert report["step_count_executed"] == 2
    finally:
        _cleanup_case_root(case_root)
