#!/usr/bin/env python3
"""Validate WS26-006 M11 closure gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from autonomous.ws26_release_gate import evaluate_ws26_m11_closure_gate


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate WS26 M11 closure gate")
    parser.add_argument(
        "--ws26-doc",
        type=Path,
        default=Path("doc/task/23-phase3-full-target-task-list.md"),
        help="WS26 task markdown path",
    )
    parser.add_argument(
        "--runbook",
        type=Path,
        default=Path("doc/task/runbooks/release_m11_lock_fencing_closure_onepager_ws26_006.md"),
        help="WS26 M11 runbook path",
    )
    parser.add_argument(
        "--runtime-snapshot-report",
        type=Path,
        default=Path("scratch/reports/ws26_runtime_snapshot_ws26_002.json"),
        help="WS26-002 runtime snapshot report path",
    )
    parser.add_argument(
        "--m11-chaos-report",
        type=Path,
        default=Path("scratch/reports/ws26_m11_runtime_chaos_ws26_006.json"),
        help="WS26-006 M11 chaos report path",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("scratch/reports/ws26_m11_closure_gate_result.json"),
        help="Gate result output path",
    )
    args = parser.parse_args()

    result = evaluate_ws26_m11_closure_gate(
        ws26_doc_path=args.ws26_doc,
        runbook_path=args.runbook,
        runtime_snapshot_report_path=args.runtime_snapshot_report,
        m11_chaos_report_path=args.m11_chaos_report,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if bool(result.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
