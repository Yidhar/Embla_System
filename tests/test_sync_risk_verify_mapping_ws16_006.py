from __future__ import annotations

import csv
import shutil
import uuid
from pathlib import Path

from scripts.sync_risk_verify_mapping_ws16_006 import sync_board_verify_for_risks


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _write_risk_ledger(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# risk ledger",
                "| risk_id | topic | severity | implementation_tasks | verification_tasks | evidence_required | gate | status |",
                "|---|---|---|---|---|---|---|---|",
                "| R1 | x | Critical | A | NGA-VERIFY-1 | e | M1 | todo |",
                "| R2 | y | High | B | NGA-VERIFY-2 | e | M2 | todo |",
            ]
        ),
        encoding="utf-8",
    )


def _write_board(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                '"task_id","status","risk_ids","verify_for_risks","evidence_link"',
                '"NGA-IMP-1","review","R1|R2","","docs/a.md"',
                '"NGA-IMP-2","done","R1","NGA-VERIFY-0","docs/a.md"',
                '"NGA-VERIFY-1","review","","","docs/a.md"',
                '"NGA-VERIFY-2","review","","","docs/a.md"',
                '"NGA-VERIFY-0","review","","","docs/a.md"',
            ]
        ),
        encoding="utf-8",
    )


def test_sync_risk_verify_mapping_fills_and_merges_values() -> None:
    case_root = _make_case_root("test_sync_risk_verify_mapping_ws16_006")
    try:
        board = case_root / "board.csv"
        ledger = case_root / "risk.md"
        _write_board(board)
        _write_risk_ledger(ledger)

        result = sync_board_verify_for_risks(
            board_file=board,
            risk_ledger_file=ledger,
        )
        changed = {item["task_id"]: item for item in result["changed"]}  # type: ignore[index]

        assert "NGA-IMP-1" in changed
        assert changed["NGA-IMP-1"]["after"] == "NGA-VERIFY-1|NGA-VERIFY-2"

        assert "NGA-IMP-2" in changed
        assert changed["NGA-IMP-2"]["after"] == "NGA-VERIFY-0|NGA-VERIFY-1"

        rows = result["rows"]  # type: ignore[assignment]
        row_map = {row["task_id"]: row for row in rows}
        assert row_map["NGA-IMP-1"]["verify_for_risks"] == "NGA-VERIFY-1|NGA-VERIFY-2"
        assert row_map["NGA-IMP-2"]["verify_for_risks"] == "NGA-VERIFY-0|NGA-VERIFY-1"
    finally:
        _cleanup_case_root(case_root)


def test_sync_risk_verify_mapping_preserves_csv_structure() -> None:
    case_root = _make_case_root("test_sync_risk_verify_mapping_ws16_006")
    try:
        board = case_root / "board.csv"
        ledger = case_root / "risk.md"
        _write_board(board)
        _write_risk_ledger(ledger)

        result = sync_board_verify_for_risks(
            board_file=board,
            risk_ledger_file=ledger,
        )
        rows = result["rows"]  # type: ignore[assignment]
        assert rows

        out = case_root / "board_out.csv"
        fieldnames = list(rows[0].keys())
        with out.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            writer.writerows(rows)

        reloaded = list(csv.DictReader(out.open("r", encoding="utf-8", newline="")))
        assert len(reloaded) == 5
        assert reloaded[0]["task_id"] == "NGA-IMP-1"
    finally:
        _cleanup_case_root(case_root)
