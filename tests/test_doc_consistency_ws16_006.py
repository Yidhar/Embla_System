"""WS16-006 document consistency validator tests."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from system.doc_consistency import validate_execution_board_consistency


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_doc_consistency_validator_accepts_valid_evidence_paths() -> None:
    case_root = _make_case_root("test_doc_consistency_ws16_006")
    try:
        (case_root / "docs").mkdir(parents=True, exist_ok=True)
        (case_root / "docs" / "ok.md").write_text("ok", encoding="utf-8")
        (case_root / "src").mkdir(parents=True, exist_ok=True)
        (case_root / "src" / "main.py").write_text("print('ok')", encoding="utf-8")
        board = case_root / "board.csv"
        board.write_text(
            "\n".join(
                [
                    '"task_id","status","evidence_link"',
                    '"NGA-X-001","review","docs/ok.md; src/main.py::func"',
                ]
            ),
            encoding="utf-8",
        )

        report = validate_execution_board_consistency(board_file=board, repo_root=case_root)
        assert report.checked_rows == 1
        assert report.error_count == 0
    finally:
        _cleanup_case_root(case_root)


def test_doc_consistency_validator_reports_missing_paths() -> None:
    case_root = _make_case_root("test_doc_consistency_ws16_006")
    try:
        board = case_root / "board.csv"
        board.write_text(
            "\n".join(
                [
                    '"task_id","status","evidence_link"',
                    '"NGA-X-002","review","docs/missing.md; src/unknown.py:42"',
                ]
            ),
            encoding="utf-8",
        )

        report = validate_execution_board_consistency(board_file=board, repo_root=case_root)
        assert report.checked_rows == 1
        assert report.error_count == 2
        assert any(issue["normalized_path"] == "docs/missing.md" for issue in report.issues)
        assert any(issue["normalized_path"] == "src/unknown.py" for issue in report.issues)
    finally:
        _cleanup_case_root(case_root)


def test_doc_consistency_validator_requires_evidence_for_review_rows() -> None:
    case_root = _make_case_root("test_doc_consistency_ws16_006")
    try:
        board = case_root / "board.csv"
        board.write_text(
            "\n".join(
                [
                    '"task_id","status","evidence_link"',
                    '"NGA-X-003","review",""',
                    '"NGA-X-004","todo",""',
                ]
            ),
            encoding="utf-8",
        )
        report = validate_execution_board_consistency(board_file=board, repo_root=case_root)
        assert report.checked_rows == 1
        assert report.error_count == 1
        assert report.issues[0]["task_id"] == "NGA-X-003"
    finally:
        _cleanup_case_root(case_root)
