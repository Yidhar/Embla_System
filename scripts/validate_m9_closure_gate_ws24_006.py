#!/usr/bin/env python3
"""Validate WS24-006 M9 closure gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agents.release_gates.ws24_release_gate import evaluate_ws24_m9_closure_gate


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate WS24 M9 closure gate")
    parser.add_argument(
        "--ws24-doc",
        type=Path,
        default=Path("doc/task/23-phase3-full-target-task-list.md"),
        help="WS24 task markdown path",
    )
    parser.add_argument(
        "--runbook",
        type=Path,
        default=Path("doc/task/runbooks/release_m9_plugin_isolation_closure_onepager_ws24_006.md"),
        help="WS24 M9 runbook path",
    )
    parser.add_argument(
        "--plugin-chaos-report",
        type=Path,
        default=Path("scratch/reports/plugin_isolation_chaos_ws24_005.json"),
        help="WS24-005 report path",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("scratch/reports/ws24_m9_closure_gate_result.json"),
        help="Gate result output path",
    )
    args = parser.parse_args()

    result = evaluate_ws24_m9_closure_gate(
        ws24_doc_path=args.ws24_doc,
        runbook_path=args.runbook,
        plugin_chaos_report_path=args.plugin_chaos_report,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if bool(result.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
