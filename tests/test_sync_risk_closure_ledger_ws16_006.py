from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from scripts.sync_risk_closure_ledger_ws16_006 import sync_risk_closure_ledger


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _write_board(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                '"task_id","status","risk_ids","verify_for_risks","evidence_link"',
                '"NGA-IMP-A","review","R1","NGA-VER-A","a.md"',
                '"NGA-VER-A","review","","","a.md"',
                '"NGA-IMP-B","done","R2","NGA-VER-B","a.md"',
                '"NGA-VER-B","done","","","a.md"',
            ]
        ),
        encoding="utf-8",
    )


def _write_ledger(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# ledger",
                "| risk_id | topic | severity | implementation_tasks | verification_tasks | evidence_required | gate | status |",
                "|---|---|---|---|---|---|---|---|",
                "| R1 | t1 | Critical | NGA-IMP-A | NGA-VER-A | e | M1 | todo |",
                "| R2 | t2 | High | NGA-IMP-B | NGA-VER-B | e | M2 | todo |",
                "| R3 | t3 | High | NGA-IMP-C | NGA-VER-C | e | M2 | todo |",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_sync_risk_closure_ledger_computes_review_done_and_todo() -> None:
    case_root = _make_case_root("test_sync_risk_closure_ledger_ws16_006")
    try:
        board = case_root / "board.csv"
        ledger = case_root / "risk.md"
        _write_board(board)
        _write_ledger(ledger)

        result = sync_risk_closure_ledger(board_file=board, risk_ledger_file=ledger)
        assert result["row_count"] == 3

        changed = {row["risk_id"]: row for row in result["changed_rows"]}  # type: ignore[index]
        evaluated = {row["risk_id"]: row for row in result["evaluated_rows"]}  # type: ignore[index]
        assert changed["R1"]["status_after"] == "review"
        assert changed["R2"]["status_after"] == "done"
        assert evaluated["R3"]["status_after"] == "todo"
        assert evaluated["R3"]["missing_tasks"] == ["NGA-IMP-C", "NGA-VER-C"]
    finally:
        _cleanup_case_root(case_root)


def test_sync_risk_closure_ledger_preserves_non_risk_lines() -> None:
    case_root = _make_case_root("test_sync_risk_closure_ledger_ws16_006")
    try:
        board = case_root / "board.csv"
        ledger = case_root / "risk.md"
        _write_board(board)
        _write_ledger(ledger)

        result = sync_risk_closure_ledger(board_file=board, risk_ledger_file=ledger)
        updated_text = str(result["updated_text"])
        assert updated_text.startswith("# ledger")
        assert "| risk_id | topic | severity | implementation_tasks | verification_tasks | evidence_required | gate | status |" in updated_text
    finally:
        _cleanup_case_root(case_root)
