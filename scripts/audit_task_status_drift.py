#!/usr/bin/env python3
"""Audit WS task status drift across execution board/backlog/ws docs.

This script provides one place to inspect:
1. `09-execution-board.csv` vs `99-task-backlog.csv` status mismatch.
2. `done` tasks lacking dated verification hints in board notes.
3. WS markdown `- status:` drift compared to execution board status.

Optional remediation:
- Demote undated `done` tasks to `review` in board and backlog (`--apply-demote-undated-done --apply`).
"""

from __future__ import annotations

import argparse
import csv
import glob
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple


DEFAULT_BOARD = Path("doc/task/09-execution-board.csv")
DEFAULT_BACKLOG = Path("doc/task/99-task-backlog.csv")
DEFAULT_WS_DOC_GLOB = "doc/task/[1-2][0-9]-ws-*.md"
DEFAULT_OUTPUT = Path("scratch/reports/task_status_audit_ws10_ws20.json")

_TASK_ID_RE = re.compile(r"^NGA-WS\d{2}-\d{3}$")
_WS_HEADING_RE = re.compile(r"^###\s+(NGA-WS\d{2}-\d{3})\b")
_STATUS_LINE_RE = re.compile(r"^-\s*status:\s*(.+?)\s*$")
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_key(key: str) -> str:
    return str(key or "").lstrip("\ufeff").strip()


def _normalize_status(status: str) -> str:
    return str(status or "").strip().strip("`").lower()


def _load_csv(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    rows: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = [_normalize_key(name) for name in list(reader.fieldnames or [])]
        for raw in reader:
            rows.append({_normalize_key(k): str(v) for k, v in raw.items()})
    return rows, fieldnames


def _write_csv(path: Path, rows: Sequence[Dict[str, str]], fieldnames: Sequence[str]) -> None:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(fieldnames), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({name: str(row.get(name, "")) for name in fieldnames})
    path.write_text(buffer.getvalue(), encoding="utf-8")


def _parse_ws_doc_statuses(paths: Iterable[Path]) -> Dict[str, Dict[str, str]]:
    result: Dict[str, Dict[str, str]] = {}
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        index = 0
        while index < len(lines):
            line = str(lines[index]).strip()
            heading = _WS_HEADING_RE.match(line)
            if not heading:
                index += 1
                continue

            task_id = heading.group(1)
            status_value = ""
            probe = index + 1
            while probe < len(lines):
                probe_line = str(lines[probe]).strip()
                if probe_line.startswith("### "):
                    break
                status_match = _STATUS_LINE_RE.match(probe_line)
                if status_match:
                    status_value = _normalize_status(status_match.group(1))
                    break
                probe += 1

            result[task_id] = {
                "status": status_value,
                "path": str(path).replace("\\", "/"),
            }
            index += 1
    return result


def _is_scoped_task(task_id: str) -> bool:
    normalized = str(task_id or "").strip()
    return bool(_TASK_ID_RE.match(normalized))


def run_audit(
    *,
    board_file: Path,
    backlog_file: Path,
    ws_doc_glob: str,
    demote_undated_done: bool,
    apply: bool,
) -> Dict[str, object]:
    board_rows, board_fields = _load_csv(board_file)
    backlog_rows, backlog_fields = _load_csv(backlog_file)

    board_map: Dict[str, Dict[str, str]] = {
        str(row.get("task_id") or "").strip(): row for row in board_rows if _is_scoped_task(row.get("task_id", ""))
    }
    backlog_map: Dict[str, Dict[str, str]] = {
        str(row.get("task_id") or "").strip(): row for row in backlog_rows if _is_scoped_task(row.get("task_id", ""))
    }

    board_vs_backlog_mismatch: List[Dict[str, str]] = []
    missing_in_backlog: List[str] = []
    done_without_dated_note: List[Dict[str, str]] = []

    for task_id, board_row in sorted(board_map.items()):
        board_status = _normalize_status(board_row.get("status", ""))
        backlog_row = backlog_map.get(task_id)
        if backlog_row is None:
            missing_in_backlog.append(task_id)
        else:
            backlog_status = _normalize_status(backlog_row.get("status", ""))
            if backlog_status != board_status:
                board_vs_backlog_mismatch.append(
                    {
                        "task_id": task_id,
                        "board_status": board_status,
                        "backlog_status": backlog_status,
                    }
                )

        if board_status == "done":
            notes = str(board_row.get("notes") or "")
            if not _DATE_RE.search(notes):
                done_without_dated_note.append(
                    {
                        "task_id": task_id,
                        "status": board_status,
                        "notes": notes,
                    }
                )

    ws_doc_paths = sorted(Path(path) for path in glob.glob(ws_doc_glob))
    ws_doc_status = _parse_ws_doc_statuses(ws_doc_paths)
    ws_doc_drift: List[Dict[str, str]] = []

    for task_id, board_row in sorted(board_map.items()):
        board_status = _normalize_status(board_row.get("status", ""))
        ws_entry = ws_doc_status.get(task_id)
        if not ws_entry:
            continue
        ws_status = _normalize_status(ws_entry.get("status", ""))
        if ws_status and ws_status != board_status:
            ws_doc_drift.append(
                {
                    "task_id": task_id,
                    "board_status": board_status,
                    "ws_doc_status": ws_status,
                    "ws_doc_path": str(ws_entry.get("path") or ""),
                }
            )

    demoted: List[str] = []
    if demote_undated_done:
        demote_ids = {entry["task_id"] for entry in done_without_dated_note}
        for task_id in sorted(demote_ids):
            board_row = board_map.get(task_id)
            if board_row and _normalize_status(board_row.get("status", "")) == "done":
                board_row["status"] = "review"
                demoted.append(task_id)
            backlog_row = backlog_map.get(task_id)
            if backlog_row and _normalize_status(backlog_row.get("status", "")) == "done":
                backlog_row["status"] = "review"

    if apply and demoted:
        _write_csv(board_file, board_rows, board_fields)
        _write_csv(backlog_file, backlog_rows, backlog_fields)

    result: Dict[str, object] = {
        "generated_at": _utc_now(),
        "board_file": str(board_file),
        "backlog_file": str(backlog_file),
        "ws_doc_glob": ws_doc_glob,
        "summary": {
            "board_task_count": len(board_map),
            "backlog_task_count": len(backlog_map),
            "board_vs_backlog_mismatch_count": len(board_vs_backlog_mismatch),
            "missing_in_backlog_count": len(missing_in_backlog),
            "done_without_dated_note_count": len(done_without_dated_note),
            "ws_doc_drift_count": len(ws_doc_drift),
            "demoted_to_review_count": len(demoted),
        },
        "board_vs_backlog_mismatch": board_vs_backlog_mismatch,
        "missing_in_backlog": missing_in_backlog,
        "done_without_dated_note": done_without_dated_note,
        "ws_doc_drift": ws_doc_drift,
        "demoted_to_review": demoted,
        "apply_requested": bool(apply),
        "demote_undated_done_requested": bool(demote_undated_done),
    }
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit WS10-WS20 status drift and optional remediation.")
    parser.add_argument("--board", type=Path, default=DEFAULT_BOARD, help="execution board csv path")
    parser.add_argument("--backlog", type=Path, default=DEFAULT_BACKLOG, help="task backlog csv path")
    parser.add_argument("--ws-doc-glob", default=DEFAULT_WS_DOC_GLOB, help="glob for WS markdown docs")
    parser.add_argument(
        "--apply-demote-undated-done",
        action="store_true",
        help="demote done tasks without YYYY-MM-DD in notes to review",
    )
    parser.add_argument("--apply", action="store_true", help="apply remediation to board/backlog files")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT, help="audit output json path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_audit(
        board_file=args.board,
        backlog_file=args.backlog,
        ws_doc_glob=str(args.ws_doc_glob),
        demote_undated_done=bool(args.apply_demote_undated_done),
        apply=bool(args.apply),
    )
    output = args.output_json
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "summary": report.get("summary", {}),
                "output": str(output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
