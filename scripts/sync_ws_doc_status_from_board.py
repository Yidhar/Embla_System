#!/usr/bin/env python3
"""Sync WS markdown task statuses from execution board status.

Scope:
- Default targets `doc/task/10-ws-*.md` ... `doc/task/20-ws-*.md`.
- Status source is `doc/task/09-execution-board.csv`.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence


DEFAULT_BOARD = Path("doc/task/09-execution-board.csv")
DEFAULT_DOC_GLOBS: Sequence[str] = ("doc/task/1[0-9]-ws-*.md", "doc/task/20-ws-*.md")
DEFAULT_OUTPUT = Path("scratch/reports/ws_doc_status_sync_ws10_ws20.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_status(status: str) -> str:
    return str(status or "").strip().strip("`").lower()


def _load_board_status_map(board_file: Path) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    with board_file.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            task_id = str(row.get("task_id") or "").strip()
            if not task_id:
                continue
            status = _normalize_status(str(row.get("status") or ""))
            if status:
                mapping[task_id] = status
    return mapping


def _resolve_doc_paths(globs: Sequence[str]) -> List[Path]:
    paths: List[Path] = []
    for pattern in globs:
        paths.extend(Path(item) for item in glob.glob(pattern))
    unique = sorted({str(path.resolve()): path for path in paths}.values(), key=lambda p: str(p))
    return unique


def _sync_one_doc(path: Path, board_map: Dict[str, str]) -> Dict[str, object]:
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    updated = list(lines)
    index = 0
    changed: List[Dict[str, str]] = []
    missing_status_line: List[str] = []
    missing_in_board: List[str] = []

    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped.startswith("### NGA-WS"):
            index += 1
            continue

        heading_tokens = stripped.split()
        task_id = ""
        if len(heading_tokens) >= 2:
            task_id = str(heading_tokens[1]).strip()
        if not task_id:
            index += 1
            continue

        board_status = board_map.get(task_id)
        if not board_status:
            missing_in_board.append(task_id)
            index += 1
            continue

        probe = index + 1
        status_line_index = -1
        current_status = ""
        while probe < len(lines):
            current = lines[probe]
            current_stripped = current.strip()
            if current_stripped.startswith("### "):
                break
            if current_stripped.startswith("- status:"):
                status_line_index = probe
                status_value = current_stripped.split(":", 1)[1].strip()
                current_status = _normalize_status(status_value)
                break
            probe += 1

        if status_line_index < 0:
            missing_status_line.append(task_id)
            index += 1
            continue

        if current_status != board_status:
            line_ending = "\n"
            raw_line = lines[status_line_index]
            if raw_line.endswith("\r\n"):
                line_ending = "\r\n"
            updated[status_line_index] = f"- status: {board_status}{line_ending}"
            changed.append(
                {
                    "task_id": task_id,
                    "status_before": current_status,
                    "status_after": board_status,
                }
            )
        index += 1

    changed_count = len(changed)
    updated_text = "".join(updated)
    return {
        "path": str(path).replace("\\", "/"),
        "changed_count": changed_count,
        "changed_items": changed,
        "missing_status_line": sorted(set(missing_status_line)),
        "missing_in_board": sorted(set(missing_in_board)),
        "updated_text": updated_text,
        "text_changed": updated_text != original,
    }


def run_sync(
    *,
    board_file: Path,
    doc_globs: Sequence[str],
    apply: bool,
) -> Dict[str, object]:
    board_map = _load_board_status_map(board_file)
    doc_paths = _resolve_doc_paths(doc_globs)
    per_file: List[Dict[str, object]] = []
    total_changed = 0
    changed_files = 0

    for path in doc_paths:
        report = _sync_one_doc(path, board_map)
        per_file.append(
            {
                "path": report["path"],
                "changed_count": report["changed_count"],
                "changed_items": report["changed_items"],
                "missing_status_line": report["missing_status_line"],
                "missing_in_board": report["missing_in_board"],
            }
        )
        total_changed += int(report["changed_count"])
        if bool(report["text_changed"]):
            changed_files += 1
            if apply:
                path.write_text(str(report["updated_text"]), encoding="utf-8")

    return {
        "generated_at": _utc_now(),
        "board_file": str(board_file),
        "doc_globs": list(doc_globs),
        "summary": {
            "board_task_count": len(board_map),
            "doc_count": len(doc_paths),
            "changed_files": changed_files,
            "changed_task_status_count": total_changed,
        },
        "files": per_file,
        "apply_requested": bool(apply),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync WS markdown statuses from 09 execution board")
    parser.add_argument("--board", type=Path, default=DEFAULT_BOARD, help="execution board csv path")
    parser.add_argument(
        "--doc-glob",
        dest="doc_globs",
        action="append",
        default=[],
        help="markdown glob to include (repeatable); defaults to WS10-WS20 patterns",
    )
    parser.add_argument("--apply", action="store_true", help="write updates to markdown files")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT, help="output report json path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    doc_globs = list(args.doc_globs) if args.doc_globs else list(DEFAULT_DOC_GLOBS)
    report = run_sync(
        board_file=args.board,
        doc_globs=doc_globs,
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
