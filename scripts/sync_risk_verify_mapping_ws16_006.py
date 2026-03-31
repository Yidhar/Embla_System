"""Sync execution-board verify_for_risks from risk closure ledger mappings."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, List, Tuple

from system.doc_consistency import load_risk_verification_map


def _split_tokens(raw: str) -> List[str]:
    value = str(raw or "").strip()
    if not value:
        return []
    tokens: List[str] = []
    for part in value.replace(";", "|").replace(",", "|").split("|"):
        token = part.strip()
        if token:
            tokens.append(token)
    return tokens


def _merge_preserving_order(existing: List[str], expected: List[str]) -> List[str]:
    merged = list(existing)
    for token in expected:
        if token not in merged:
            merged.append(token)
    return merged


def sync_board_verify_for_risks(
    *,
    board_file: Path,
    risk_ledger_file: Path,
    statuses: Tuple[str, ...] = ("review", "done"),
) -> Dict[str, object]:
    rows: List[Dict[str, str]] = []
    with Path(board_file).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append({str(k): str(v) for k, v in row.items()})

    risk_map = load_risk_verification_map(risk_ledger_file=Path(risk_ledger_file))
    status_set = {s.lower() for s in statuses}
    board_task_ids = {
        str(row.get("task_id") or "").strip()
        for row in rows
        if str(row.get("task_id") or "").strip()
    }
    changed: List[Dict[str, str]] = []

    for row in rows:
        status = str(row.get("status") or "").strip().lower()
        if status not in status_set:
            continue

        original_verify = str(row.get("verify_for_risks") or "")
        current_valid = [
            token
            for token in _split_tokens(original_verify)
            if token in board_task_ids
        ]

        risk_ids = _split_tokens(row.get("risk_ids") or "")
        merged: List[str] = list(current_valid)
        if risk_ids:
            expected: List[str] = []
            for risk_id in risk_ids:
                expected.extend(risk_map.get(risk_id, []))
            if expected:
                merged = _merge_preserving_order(current_valid, expected)

        merged_value = "|".join(merged)
        if merged_value != original_verify:
            changed.append(
                {
                    "task_id": str(row.get("task_id") or "").strip(),
                    "before": original_verify,
                    "after": merged_value,
                }
            )
            row["verify_for_risks"] = merged_value

    return {
        "rows": rows,
        "changed": changed,
    }


def _write_board(*, board_file: Path, rows: List[Dict[str, str]]) -> None:
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with Path(board_file).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync verify_for_risks in execution board.")
    parser.add_argument("--board", default="doc/task/09-execution-board.csv", help="execution board CSV path")
    parser.add_argument("--risk-ledger", default="doc/task/08-risk-closure-ledger.md", help="risk ledger markdown path")
    parser.add_argument("--dry-run", action="store_true", help="print changes without writing board")
    args = parser.parse_args()

    result = sync_board_verify_for_risks(
        board_file=Path(args.board),
        risk_ledger_file=Path(args.risk_ledger),
    )
    changed = result["changed"]
    payload = {
        "board": args.board,
        "risk_ledger": args.risk_ledger,
        "changed_count": len(changed),
        "changed": changed,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if not args.dry_run:
        _write_board(board_file=Path(args.board), rows=result["rows"])  # type: ignore[arg-type]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
