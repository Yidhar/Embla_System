#!/usr/bin/env python3
"""Sync 99-task-backlog status from 09-execution-board status."""

from __future__ import annotations

import argparse
import csv
import json
import io
from pathlib import Path
from typing import Dict, List


def _normalize_key(key: str) -> str:
    return str(key or "").lstrip("\ufeff").strip()


def _load_board_status_map(board_file: Path) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    with Path(board_file).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            normalized = {_normalize_key(k): str(v) for k, v in row.items()}
            task_id = str(normalized.get("task_id") or "").strip()
            if not task_id:
                continue
            mapping[task_id] = str(normalized.get("status") or "").strip()
    return mapping


def sync_task_backlog_status(
    *,
    board_file: Path,
    backlog_file: Path,
) -> Dict[str, object]:
    board_map = _load_board_status_map(board_file)
    rows: List[Dict[str, str]] = []
    changed_rows: List[Dict[str, str]] = []
    missing_tasks: List[str] = []

    with Path(backlog_file).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = [_normalize_key(name) for name in list(reader.fieldnames or [])]
        for raw_row in reader:
            row = {_normalize_key(k): str(v) for k, v in raw_row.items()}
            task_id = str(row.get("task_id") or "").strip()
            status_before = str(row.get("status") or "").strip()
            status_after = status_before
            if task_id:
                mapped_status = board_map.get(task_id)
                if mapped_status:
                    status_after = mapped_status
                else:
                    missing_tasks.append(task_id)
            row["status"] = status_after
            rows.append(row)
            if status_before != status_after:
                changed_rows.append(
                    {
                        "task_id": task_id,
                        "status_before": status_before,
                        "status_after": status_after,
                    }
                )

    if "status" not in fieldnames:
        raise ValueError("backlog csv missing required field: status")

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({name: str(row.get(name, "")) for name in fieldnames})
    updated_text = buffer.getvalue()

    return {
        "board_path": str(Path(board_file)),
        "backlog_path": str(Path(backlog_file)),
        "row_count": len(rows),
        "changed_count": len(changed_rows),
        "changed_rows": changed_rows,
        "missing_task_count": len(missing_tasks),
        "missing_tasks": sorted(set(missing_tasks)),
        "updated_text": updated_text,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync task backlog status from execution board")
    parser.add_argument("--board", default="doc/task/09-execution-board.csv", help="execution board csv path")
    parser.add_argument("--backlog", default="doc/task/99-task-backlog.csv", help="task backlog csv path")
    parser.add_argument("--apply", action="store_true", help="write synced status back to backlog csv")
    parser.add_argument("--output-json", default="", help="optional output report path")
    args = parser.parse_args()

    result = sync_task_backlog_status(
        board_file=Path(args.board),
        backlog_file=Path(args.backlog),
    )
    payload = {
        "board": args.board,
        "backlog": args.backlog,
        "row_count": result["row_count"],
        "changed_count": result["changed_count"],
        "changed_rows": result["changed_rows"],
        "missing_task_count": result["missing_task_count"],
        "missing_tasks": result["missing_tasks"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.output_json:
        output = Path(args.output_json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.apply:
        Path(args.backlog).write_text(str(result["updated_text"]), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
