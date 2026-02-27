from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from scripts.release_closure_chain_m0_m5 import run_release_closure_chain_m0_m5


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_release_closure_chain_runs_all_steps_with_green_runner() -> None:
    case_root = _make_case_root("test_release_closure_chain_m0_m5")
    try:
        seen_commands: list[list[str]] = []

        def _runner(command, cwd, timeout):
            seen_commands.append(list(command))
            return 0, f"ok:{len(seen_commands)}", ""

        report = run_release_closure_chain_m0_m5(
            repo_root=Path("."),
            output_file=case_root / "report.json",
            runner=_runner,
        )
        assert report["passed"] is True
        assert report["failed_steps"] == []
        assert report["warning_steps"] == []
        assert report["step_count_planned"] == 9
        assert report["step_count_executed"] == 9
        assert "validate_immutable_dna_gate_ws23_003.py" in " ".join(seen_commands[0])
        assert "validate_doc_consistency_ws16_006.py" in " ".join(seen_commands[1])
        assert "test_native_executor_guards.py" in " ".join(seen_commands[2])
        assert "test_tool_contract.py" in " ".join(seen_commands[3])
        assert "test_mcp_status_snapshot.py" in " ".join(seen_commands[4])
        assert "test_event_store_ws18_001.py" in " ".join(seen_commands[5])
        assert "export_slo_snapshot.py" in " ".join(seen_commands[6])
        assert "embla_core_release_compat_gate.py" in " ".join(seen_commands[7])
        assert "canary_rollback_drill.py" in " ".join(seen_commands[8])
    finally:
        _cleanup_case_root(case_root)


def test_release_closure_chain_stops_on_first_failure_by_default() -> None:
    case_root = _make_case_root("test_release_closure_chain_m0_m5")
    try:
        def _runner(command, cwd, timeout):
            text = " ".join(command)
            if "test_tool_contract.py" in text:
                return 2, "", "t2 failed"
            return 0, "ok", ""

        report = run_release_closure_chain_m0_m5(
            repo_root=Path("."),
            output_file=case_root / "report.json",
            runner=_runner,
            continue_on_failure=False,
        )
        assert report["passed"] is False
        assert report["failed_steps"] == ["T2"]
        assert report["step_count_executed"] == 4
    finally:
        _cleanup_case_root(case_root)


def test_release_closure_chain_canary_step_is_blocking() -> None:
    case_root = _make_case_root("test_release_closure_chain_m0_m5")
    try:
        def _runner(command, cwd, timeout):
            text = " ".join(command)
            if "canary_rollback_drill.py" in text:
                return 1, "", "canary drill failed"
            return 0, "ok", ""

        report = run_release_closure_chain_m0_m5(
            repo_root=Path("."),
            output_file=case_root / "report.json",
            runner=_runner,
        )
        assert report["passed"] is False
        assert report["failed_steps"] == ["T5C"]
        assert report["warning_steps"] == []
    finally:
        _cleanup_case_root(case_root)
