from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from scripts.generate_phase3_full_release_report_ws27_006 import (
    main,
    run_generate_phase3_full_release_report_ws27_006,
)


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _bootstrap_reports(repo_root: Path, *, all_passed: bool) -> None:
    _write_json(repo_root / "scratch/reports/release_closure_chain_full_m0_m12_result.json", {"passed": all_passed})
    _write_json(repo_root / "scratch/reports/ws27_m12_doc_consistency_ws27_005.json", {"passed": all_passed})
    _write_json(repo_root / "scratch/reports/ws27_72h_endurance_ws27_001.json", {"passed": all_passed})
    _write_json(repo_root / "scratch/reports/ws27_72h_wallclock_acceptance_ws27_001.json", {"passed": all_passed})
    _write_json(repo_root / "scratch/reports/ws27_subagent_cutover_status_ws27_002.json", {"passed": all_passed})
    _write_json(repo_root / "scratch/reports/ws27_oob_repair_drill_ws27_003.json", {"passed": all_passed})


def test_generate_phase3_release_report_passes_when_all_inputs_pass() -> None:
    case_root = _make_case_root("test_ws27_006_phase3_release_report")
    try:
        repo_root = case_root / "repo"
        _bootstrap_reports(repo_root, all_passed=True)

        report = run_generate_phase3_full_release_report_ws27_006(
            repo_root=repo_root,
            release_candidate="phase3-local-rc1",
            output_json=Path("scratch/reports/ws27_006_release_report.json"),
            output_markdown=Path("scratch/reports/ws27_006_signoff.md"),
        )
        assert report["passed"] is True
        checks = report["checks"]
        assert checks["all_required_reports_present"] is True
        assert checks["full_chain_passed"] is True
        assert checks["doc_consistency_passed"] is True
        assert checks["ws27_endurance_passed"] is True
        assert checks["ws27_wallclock_report_present"] is True
        assert checks["ws27_wallclock_acceptance_passed"] is True
        assert checks["ws27_cutover_status_passed"] is True
        assert checks["ws27_oob_drill_passed"] is True

        output_json = repo_root / "scratch/reports/ws27_006_release_report.json"
        output_markdown = repo_root / "scratch/reports/ws27_006_signoff.md"
        assert output_json.exists() is True
        assert output_markdown.exists() is True
        signoff_text = output_markdown.read_text(encoding="utf-8")
        assert "放行结论: `PASS`" in signoff_text
        assert "phase3-local-rc1" in signoff_text
    finally:
        _cleanup_case_root(case_root)


def test_generate_phase3_release_report_marks_failed_when_input_missing() -> None:
    case_root = _make_case_root("test_ws27_006_phase3_release_report")
    try:
        repo_root = case_root / "repo"
        _bootstrap_reports(repo_root, all_passed=True)
        (repo_root / "scratch/reports/ws27_oob_repair_drill_ws27_003.json").unlink()

        report = run_generate_phase3_full_release_report_ws27_006(
            repo_root=repo_root,
            output_json=Path("scratch/reports/ws27_006_release_report_fail.json"),
            output_markdown=Path("scratch/reports/ws27_006_signoff_fail.md"),
        )
        assert report["passed"] is False
        checks = report["checks"]
        assert checks["all_required_reports_present"] is False
        assert checks["ws27_oob_drill_passed"] is False
        assert len(report["missing_required_reports"]) >= 1
    finally:
        _cleanup_case_root(case_root)


def test_generate_phase3_release_report_requires_wallclock_when_enabled() -> None:
    case_root = _make_case_root("test_ws27_006_phase3_release_report_wallclock")
    try:
        repo_root = case_root / "repo"
        _bootstrap_reports(repo_root, all_passed=True)
        (repo_root / "scratch/reports/ws27_72h_wallclock_acceptance_ws27_001.json").unlink()

        report = run_generate_phase3_full_release_report_ws27_006(
            repo_root=repo_root,
            require_wallclock_acceptance=True,
            output_json=Path("scratch/reports/ws27_006_release_report_wallclock_fail.json"),
            output_markdown=Path("scratch/reports/ws27_006_signoff_wallclock_fail.md"),
        )
        assert report["passed"] is False
        checks = report["checks"]
        assert checks["ws27_wallclock_report_present"] is False
        assert checks["ws27_wallclock_acceptance_passed"] is False
        assert checks["all_required_reports_present"] is False
        assert any("ws27_72h_wallclock_acceptance_ws27_001.json" in item for item in report["missing_required_reports"])
        assert "ws27_wallclock_acceptance_passed" in report["gating_check_ids"]
    finally:
        _cleanup_case_root(case_root)


def test_generate_phase3_release_report_cli_strict_returns_nonzero_on_failure(monkeypatch) -> None:
    case_root = _make_case_root("test_ws27_006_phase3_release_report_cli")
    try:
        repo_root = case_root / "repo"
        _bootstrap_reports(repo_root, all_passed=False)
        monkeypatch.setattr(
            "sys.argv",
            [
                "generate_phase3_full_release_report_ws27_006.py",
                "--repo-root",
                str(repo_root),
                "--strict",
                "--output-json",
                "scratch/reports/ws27_006_cli_report.json",
                "--output-markdown",
                "scratch/reports/ws27_006_cli_signoff.md",
            ],
        )
        exit_code = main()
        assert exit_code == 2
        assert (repo_root / "scratch/reports/ws27_006_cli_report.json").exists() is True
        assert (repo_root / "scratch/reports/ws27_006_cli_signoff.md").exists() is True
    finally:
        _cleanup_case_root(case_root)
