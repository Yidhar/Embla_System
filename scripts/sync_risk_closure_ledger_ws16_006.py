"""Sync risk closure ledger status from execution-board task status."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Dict, List


def _split_tokens(raw: str) -> List[str]:
    value = str(raw or "").strip()
    if not value:
        return []
    parts = re.split(r"[|,;]", value)
    return [part.strip() for part in parts if part.strip()]


def _load_board_map(board_file: Path) -> Dict[str, Dict[str, str]]:
    mapping: Dict[str, Dict[str, str]] = {}
    with Path(board_file).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            normalized = {str(k): str(v) for k, v in row.items()}
            task_id = str(normalized.get("task_id") or "").strip()
            if task_id:
                mapping[task_id] = normalized
    return mapping


def _compute_risk_status(*, impl_statuses: List[str], verify_statuses: List[str], missing_tasks: List[str]) -> str:
    if missing_tasks:
        return "todo"
    all_statuses = [status.lower() for status in [*impl_statuses, *verify_statuses] if status]
    if not all_statuses:
        return "todo"

    if all(status == "done" for status in all_statuses):
        return "done"
    if any(status in {"todo", "blocked", "deferred"} for status in all_statuses):
        return "todo"
    if any(status == "in_progress" for status in all_statuses):
        return "in_progress"
    if all(status in {"review", "done"} for status in all_statuses):
        return "review"
    return "todo"


def _format_row(columns: List[str]) -> str:
    return "| " + " | ".join(columns) + " |"


def sync_risk_closure_ledger(
    *,
    board_file: Path,
    risk_ledger_file: Path,
) -> Dict[str, object]:
    board_map = _load_board_map(board_file)
    ledger_path = Path(risk_ledger_file)
    lines = ledger_path.read_text(encoding="utf-8").splitlines()

    updated_lines: List[str] = []
    changed_rows: List[Dict[str, object]] = []
    evaluated_rows: List[Dict[str, object]] = []
    row_count = 0

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("| R"):
            updated_lines.append(line)
            continue

        columns = [part.strip() for part in stripped.strip("|").split("|")]
        if len(columns) < 8:
            updated_lines.append(line)
            continue

        row_count += 1
        risk_id = columns[0]
        implementation_tasks = _split_tokens(columns[3])
        verification_tasks = _split_tokens(columns[4])
        status_before = columns[7]

        missing_tasks: List[str] = []
        impl_statuses: List[str] = []
        verify_statuses: List[str] = []

        for task_id in implementation_tasks:
            row = board_map.get(task_id)
            if row is None:
                missing_tasks.append(task_id)
                continue
            impl_statuses.append(str(row.get("status") or "").strip())

        for task_id in verification_tasks:
            row = board_map.get(task_id)
            if row is None:
                missing_tasks.append(task_id)
                continue
            verify_statuses.append(str(row.get("status") or "").strip())

        status_after = _compute_risk_status(
            impl_statuses=impl_statuses,
            verify_statuses=verify_statuses,
            missing_tasks=missing_tasks,
        )
        columns[7] = status_after
        updated_lines.append(_format_row(columns))

        evaluated_rows.append(
            {
                "risk_id": risk_id,
                "status_before": status_before,
                "status_after": status_after,
                "implementation_tasks": implementation_tasks,
                "verification_tasks": verification_tasks,
                "missing_tasks": missing_tasks,
                "implementation_statuses": impl_statuses,
                "verification_statuses": verify_statuses,
            }
        )

        if status_before != status_after:
            changed_rows.append(
                {
                    "risk_id": risk_id,
                    "status_before": status_before,
                    "status_after": status_after,
                    "implementation_tasks": implementation_tasks,
                    "verification_tasks": verification_tasks,
                    "missing_tasks": missing_tasks,
                    "implementation_statuses": impl_statuses,
                    "verification_statuses": verify_statuses,
                }
            )

    return {
        "ledger_path": str(ledger_path),
        "row_count": row_count,
        "changed_count": len(changed_rows),
        "changed_rows": changed_rows,
        "evaluated_rows": evaluated_rows,
        "updated_text": "\n".join(updated_lines) + "\n",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync 08-risk-closure-ledger status from 09-execution-board.")
    parser.add_argument("--board", default="doc/task/09-execution-board.csv", help="execution board CSV path")
    parser.add_argument("--risk-ledger", default="doc/task/08-risk-closure-ledger.md", help="risk ledger markdown path")
    parser.add_argument("--output-json", default="", help="optional JSON report output path")
    parser.add_argument("--apply", action="store_true", help="write status updates back to risk ledger")
    args = parser.parse_args()

    result = sync_risk_closure_ledger(
        board_file=Path(args.board),
        risk_ledger_file=Path(args.risk_ledger),
    )
    payload = {
        "board": args.board,
        "risk_ledger": args.risk_ledger,
        "row_count": result["row_count"],
        "changed_count": result["changed_count"],
        "changed_rows": result["changed_rows"],
        "evaluated_rows": result["evaluated_rows"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.output_json:
        output = Path(args.output_json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.apply:
        Path(args.risk_ledger).write_text(str(result["updated_text"]), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
