#!/usr/bin/env python3
"""Validate WS23-006 M8 closure gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agents.release_gates.ws23_release_gate import evaluate_ws23_m8_closure_gate


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate WS23 M8 closure gate")
    parser.add_argument(
        "--ws23-doc",
        type=Path,
        default=Path("doc/task/23-phase3-full-target-task-list.md"),
        help="WS23 task markdown path",
    )
    parser.add_argument(
        "--runbook",
        type=Path,
        default=Path("doc/task/runbooks/release_m8_phase3_closure_onepager_ws23_006.md"),
        help="WS23 M8 runbook path",
    )
    parser.add_argument(
        "--brainstem-report",
        type=Path,
        default=Path("scratch/reports/brainstem_supervisor_entry_ws23_001.json"),
        help="WS23-001 report path",
    )
    parser.add_argument(
        "--dna-report",
        type=Path,
        default=Path("scratch/reports/immutable_dna_gate_ws23_003_result.json"),
        help="WS23-003 report path",
    )
    parser.add_argument(
        "--killswitch-report",
        type=Path,
        default=Path("scratch/reports/killswitch_oob_bundle_ws23_004.json"),
        help="WS23-004 report path",
    )
    parser.add_argument(
        "--outbox-bridge-report",
        type=Path,
        default=Path("scratch/reports/outbox_brainstem_bridge_ws23_005.json"),
        help="WS23-005 report path",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("scratch/reports/ws23_m8_closure_gate_result.json"),
        help="Gate result output path",
    )
    args = parser.parse_args()

    result = evaluate_ws23_m8_closure_gate(
        ws23_doc_path=args.ws23_doc,
        runbook_path=args.runbook,
        brainstem_report_path=args.brainstem_report,
        dna_gate_report_path=args.dna_report,
        killswitch_bundle_report_path=args.killswitch_report,
        outbox_bridge_report_path=args.outbox_bridge_report,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if bool(result.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
