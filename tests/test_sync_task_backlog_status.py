from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

import scripts.sync_task_backlog_status as sync_backlog


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_sync_task_backlog_status_reports_changes_and_missing_tasks() -> None:
    case_root = _make_case_root("test_sync_task_backlog_status")
    try:
        board = case_root / "board.csv"
        backlog = case_root / "backlog.csv"
        board.write_text(
            "\n".join(
                [
                    "task_id,status",
                    "NGA-WS10-001,done",
                    "NGA-WS10-002,in_progress",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        backlog.write_text(
            "\n".join(
                [
                    "\ufefftask_id,status,title",
                    "NGA-WS10-001,todo,task-a",
                    "NGA-WS10-002,todo,task-b",
                    "NGA-WS10-003,todo,task-c",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        result = sync_backlog.sync_task_backlog_status(board_file=board, backlog_file=backlog)
        assert int(result["row_count"]) == 3
        assert int(result["changed_count"]) == 2
        assert int(result["missing_task_count"]) == 1
        assert list(result["missing_tasks"]) == ["NGA-WS10-003"]
        changed = {item["task_id"]: item["status_after"] for item in list(result["changed_rows"])}
        assert changed["NGA-WS10-001"] == "done"
        assert changed["NGA-WS10-002"] == "in_progress"
        assert "NGA-WS10-003,todo,task-c" in str(result["updated_text"])
    finally:
        _cleanup_case_root(case_root)


def test_sync_task_backlog_status_apply_updates_file(monkeypatch) -> None:
    case_root = _make_case_root("test_sync_task_backlog_status")
    try:
        board = case_root / "board.csv"
        backlog = case_root / "backlog.csv"
        board.write_text(
            "\n".join(
                [
                    "task_id,status",
                    "NGA-WS20-001,done",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        backlog.write_text(
            "\n".join(
                [
                    "task_id,status,title",
                    "NGA-WS20-001,todo,task-z",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "sync_task_backlog_status.py",
                "--board",
                str(board),
                "--backlog",
                str(backlog),
                "--apply",
            ],
        )
        rc = sync_backlog.main()
        assert rc == 0
        content = backlog.read_text(encoding="utf-8")
        assert "NGA-WS20-001,done,task-z" in content
    finally:
        _cleanup_case_root(case_root)
