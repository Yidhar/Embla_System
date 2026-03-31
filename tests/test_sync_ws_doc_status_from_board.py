from __future__ import annotations

import csv
from pathlib import Path

from scripts.sync_ws_doc_status_from_board import run_sync


def _write_board(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["task_id", "status"])
        writer.writeheader()
        writer.writerow({"task_id": "NGA-WS10-001", "status": "done"})
        writer.writerow({"task_id": "NGA-WS10-002", "status": "review"})


def test_sync_ws_doc_status_updates_markdown_status_lines(tmp_path: Path) -> None:
    board = tmp_path / "09-execution-board.csv"
    ws_doc = tmp_path / "10-ws-sample.md"
    _write_board(board)
    ws_doc.write_text(
        "\n".join(
            [
                "# WS10",
                "",
                "### NGA-WS10-001 Foo",
                "- status: todo",
                "",
                "### NGA-WS10-002 Bar",
                "- status: done",
                "",
            ]
        ),
        encoding="utf-8",
    )

    report = run_sync(
        board_file=board,
        doc_globs=[str(tmp_path / "*.md")],
        apply=True,
    )

    summary = report["summary"]
    assert summary["doc_count"] == 1
    assert summary["changed_files"] == 1
    assert summary["changed_task_status_count"] == 2

    updated = ws_doc.read_text(encoding="utf-8")
    assert "- status: done" in updated
    assert "- status: review" in updated


def test_sync_ws_doc_status_dry_run_does_not_write(tmp_path: Path) -> None:
    board = tmp_path / "09-execution-board.csv"
    ws_doc = tmp_path / "10-ws-sample.md"
    _write_board(board)
    original = "\n".join(
        [
            "### NGA-WS10-001 Foo",
            "- status: todo",
            "",
        ]
    )
    ws_doc.write_text(original, encoding="utf-8")

    report = run_sync(
        board_file=board,
        doc_globs=[str(tmp_path / "*.md")],
        apply=False,
    )

    assert report["summary"]["changed_task_status_count"] == 1
    assert ws_doc.read_text(encoding="utf-8") == original
