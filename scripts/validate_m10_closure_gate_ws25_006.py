#!/usr/bin/env python3
"""Validate WS25-006 M10 closure gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from autonomous.ws25_release_gate import evaluate_ws25_m10_closure_gate


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate WS25 M10 closure gate")
    parser.add_argument(
        "--ws25-doc",
        type=Path,
        default=Path("doc/task/23-phase3-full-target-task-list.md"),
        help="WS25 task markdown path",
    )
    parser.add_argument(
        "--runbook",
        type=Path,
        default=Path("doc/task/runbooks/release_m10_event_gc_closure_onepager_ws25_006.md"),
        help="WS25 M10 runbook path",
    )
    parser.add_argument(
        "--event-gc-quality-report",
        type=Path,
        default=Path("scratch/reports/ws25_event_gc_quality_baseline.json"),
        help="WS25-005 quality baseline report path",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("scratch/reports/ws25_m10_closure_gate_result.json"),
        help="Gate result output path",
    )
    args = parser.parse_args()

    result = evaluate_ws25_m10_closure_gate(
        ws25_doc_path=args.ws25_doc,
        runbook_path=args.runbook,
        event_gc_quality_report_path=args.event_gc_quality_report,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if bool(result.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
