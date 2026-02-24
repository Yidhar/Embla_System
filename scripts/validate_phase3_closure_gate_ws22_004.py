"""Validate WS22 phase3 closure gate using long-run report + task doc state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from autonomous.ws22_release_gate import evaluate_ws22_phase3_closure_gate


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate WS22 phase3 closure gate")
    parser.add_argument(
        "--report-file",
        type=Path,
        default=Path("scratch/reports/ws22_scheduler_longrun_baseline.json"),
        help="WS22 long-run baseline report JSON path",
    )
    parser.add_argument(
        "--ws22-doc",
        type=Path,
        default=Path("doc/task/22-ws-phase3-scheduler-bridge-and-rollout.md"),
        help="WS22 task markdown path",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("scratch/reports/ws22_phase3_closure_gate_result.json"),
        help="Optional output JSON path",
    )
    args = parser.parse_args()

    result = evaluate_ws22_phase3_closure_gate(
        report_path=args.report_file,
        ws22_doc_path=args.ws22_doc,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if bool(result.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
