from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.audit_task_status_drift import run_audit


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)


def test_audit_detects_drift_and_demotes_undated_done(tmp_path: Path) -> None:
    board = tmp_path / "board.csv"
    backlog = tmp_path / "backlog.csv"
    ws_doc = tmp_path / "10-ws-sample.md"

    _write_csv(
        board,
        [
            "task_id",
            "status",
            "notes",
            "evidence_link",
            "risk_ids",
            "verify_for_risks",
        ],
        [
            ["NGA-WS10-001", "done", "no date note", "a.py", "", ""],
            ["NGA-WS10-002", "done", "revalidated on 2026-02-24", "b.py", "", ""],
        ],
    )
    _write_csv(
        backlog,
        ["task_id", "status"],
        [
            ["NGA-WS10-001", "done"],
            ["NGA-WS10-002", "done"],
        ],
    )
    ws_doc.write_text(
        "\n".join(
            [
                "### NGA-WS10-001 Foo",
                "- status: todo",
                "",
                "### NGA-WS10-002 Bar",
                "- status: done",
            ]
        ),
        encoding="utf-8",
    )

    report = run_audit(
        board_file=board,
        backlog_file=backlog,
        ws_doc_glob=str(tmp_path / "*.md"),
        demote_undated_done=True,
        apply=True,
    )

    summary = report["summary"]
    assert summary["done_without_dated_note_count"] == 1
    assert summary["ws_doc_drift_count"] == 1
    assert summary["demoted_to_review_count"] == 1
    assert report["demoted_to_review"] == ["NGA-WS10-001"]

    board_rows = list(csv.DictReader(board.open("r", encoding="utf-8")))
    backlog_rows = list(csv.DictReader(backlog.open("r", encoding="utf-8")))
    board_map = {row["task_id"]: row for row in board_rows}
    backlog_map = {row["task_id"]: row for row in backlog_rows}
    assert board_map["NGA-WS10-001"]["status"] == "review"
    assert backlog_map["NGA-WS10-001"]["status"] == "review"
    assert board_map["NGA-WS10-002"]["status"] == "done"

    # Ensure report remains serializable for CLI output parity.
    json.dumps(report, ensure_ascii=False)
