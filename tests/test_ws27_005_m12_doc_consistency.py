from __future__ import annotations

import csv
import shutil
import uuid
from pathlib import Path

from scripts.validate_m12_doc_consistency_ws27_005 import (
    CORE_DOC_PATHS,
    DEFAULT_BOARD,
    PHASE3_REQUIRED_MARKERS,
    WS27_IMPLEMENTATION_DOC_PATHS,
    WS27_RUNBOOK_PATHS,
    main,
    run_validate_m12_doc_consistency_ws27_005,
)


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_board_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["task_id", "status", "risk_ids", "verify_for_risks", "evidence_link"],
        )
        writer.writeheader()


def _bootstrap_repo(
    root: Path,
    *,
    include_phase3_markers: bool,
    missing_one_runbook: bool,
) -> None:
    for relative in CORE_DOC_PATHS:
        full_path = root / relative
        _write_text(full_path, f"# {relative.name}\n")

    phase3_path = root / "doc/task/23-phase3-full-target-task-list.md"
    if include_phase3_markers:
        _write_text(phase3_path, "\n".join(PHASE3_REQUIRED_MARKERS) + "\n")
    else:
        _write_text(phase3_path, "NGA-WS27-001` 已落地\n")

    for relative in WS27_IMPLEMENTATION_DOC_PATHS:
        _write_text(root / relative, f"# {relative.name}\n")

    for index, relative in enumerate(WS27_RUNBOOK_PATHS):
        if missing_one_runbook and index == 0:
            continue
        _write_text(root / relative, f"# {relative.name}\n")

    _write_board_csv(root / DEFAULT_BOARD)


def test_validate_m12_doc_consistency_passes_when_all_required_docs_exist() -> None:
    case_root = _make_case_root("test_validate_m12_doc_consistency_ws27_005")
    try:
        repo_root = case_root / "repo"
        _bootstrap_repo(repo_root, include_phase3_markers=True, missing_one_runbook=False)

        report = run_validate_m12_doc_consistency_ws27_005(
            repo_root=repo_root,
            output_file=Path("scratch/reports/ws27_doc_consistency.json"),
        )
        assert report["passed"] is True
        checks = report["checks"]
        assert checks["execution_board_has_no_errors"] is True
        assert checks["core_docs_present"] is True
        assert checks["ws27_implementation_docs_present"] is True
        assert checks["ws27_runbooks_present"] is True
        assert checks["phase3_snapshot_markers_present"] is True
        assert (repo_root / "scratch/reports/ws27_doc_consistency.json").exists() is True
    finally:
        _cleanup_case_root(case_root)


def test_validate_m12_doc_consistency_reports_missing_marker_and_runbook() -> None:
    case_root = _make_case_root("test_validate_m12_doc_consistency_ws27_005")
    try:
        repo_root = case_root / "repo"
        _bootstrap_repo(repo_root, include_phase3_markers=False, missing_one_runbook=True)

        report = run_validate_m12_doc_consistency_ws27_005(
            repo_root=repo_root,
            output_file=Path("scratch/reports/ws27_doc_consistency_fail.json"),
        )
        assert report["passed"] is False
        checks = report["checks"]
        assert checks["ws27_runbooks_present"] is False
        assert checks["phase3_snapshot_markers_present"] is False
        missing_items = report["missing_items"]
        assert len(missing_items["ws27_runbooks"]) >= 1
        assert len(missing_items["phase3_snapshot_markers"]) >= 1
    finally:
        _cleanup_case_root(case_root)


def test_validate_m12_doc_consistency_cli_strict_returns_nonzero_on_failure(monkeypatch) -> None:
    case_root = _make_case_root("test_validate_m12_doc_consistency_ws27_005_cli")
    try:
        repo_root = case_root / "repo"
        _bootstrap_repo(repo_root, include_phase3_markers=False, missing_one_runbook=True)
        monkeypatch.setattr(
            "sys.argv",
            [
                "validate_m12_doc_consistency_ws27_005.py",
                "--repo-root",
                str(repo_root),
                "--strict",
                "--output",
                "scratch/reports/ws27_doc_consistency_cli.json",
            ],
        )
        exit_code = main()
        assert exit_code == 2
        assert (repo_root / "scratch/reports/ws27_doc_consistency_cli.json").exists() is True
    finally:
        _cleanup_case_root(case_root)
