"""Validate doc/task execution board consistency for WS16-006."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from system.doc_consistency import validate_execution_board_consistency


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate execution-board evidence paths.")
    parser.add_argument(
        "--board",
        default="doc/task/09-execution-board.csv",
        help="Execution board csv path",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root path",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero when any error exists",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional report output json path",
    )
    args = parser.parse_args()

    report = validate_execution_board_consistency(
        board_file=Path(args.board),
        repo_root=Path(args.repo_root),
    )
    payload = report.to_dict()
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.output:
        output_file = Path(args.output)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"saved report: {output_file}")

    if args.strict and report.error_count > 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
