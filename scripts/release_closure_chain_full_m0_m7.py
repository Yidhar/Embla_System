#!/usr/bin/env python3
"""Unified release closure chain runner for M0-M7 gates."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from scripts.release_closure_chain_m0_m5 import run_release_closure_chain_m0_m5
from scripts.release_phase3_closure_chain_ws22_004 import run_phase3_release_closure_chain


def _to_jsonable(value):
    if isinstance(value, Path):
        return str(value).replace("\\", "/")
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    return value


def run_release_closure_chain_full_m0_m7(
    *,
    repo_root: Path,
    output_file: Path,
    m0_m5_output_file: Path,
    m6_m7_output_file: Path,
    skip_m0_m5: bool = False,
    skip_m6_m7: bool = False,
    quick_mode: bool = False,
    continue_on_failure: bool = False,
    timeout_seconds: int = 2400,
) -> Dict[str, object]:
    root = repo_root.resolve()
    started_at = time.time()
    failed_groups: List[str] = []
    group_results: Dict[str, object] = {}

    if not skip_m0_m5:
        m0_report = run_release_closure_chain_m0_m5(
            repo_root=root,
            output_file=m0_m5_output_file,
            skip_t0=False,
            skip_t1=bool(quick_mode),
            skip_t2=bool(quick_mode),
            skip_t3=bool(quick_mode),
            skip_t4=bool(quick_mode),
            skip_t5=bool(quick_mode),
            continue_on_failure=bool(continue_on_failure),
            timeout_seconds=max(30, int(timeout_seconds)),
        )
        group_results["m0_m5"] = m0_report
        if not bool(m0_report.get("passed")):
            failed_groups.append("m0_m5")
            if not continue_on_failure:
                report = {
                    "scenario": "release_closure_chain_full_m0_m7",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "repo_root": str(root).replace("\\", "/"),
                    "elapsed_seconds": round(time.time() - started_at, 4),
                    "passed": False,
                    "failed_groups": failed_groups,
                    "group_results": group_results,
                }
                output = output_file if output_file.is_absolute() else root / output_file
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps(_to_jsonable(report), ensure_ascii=False, indent=2), encoding="utf-8")
                return report

    if not skip_m6_m7:
        phase3_report = run_phase3_release_closure_chain(
            repo_root=root,
            output_file=m6_m7_output_file,
            skip_tests=bool(quick_mode),
            skip_longrun=bool(quick_mode),
            skip_gate=False,
            skip_doc_consistency=False,
            continue_on_failure=bool(continue_on_failure),
            timeout_seconds=max(30, int(timeout_seconds)),
        )
        group_results["m6_m7"] = phase3_report
        if not bool(phase3_report.get("passed")):
            failed_groups.append("m6_m7")

    passed = len(failed_groups) == 0
    report = {
        "scenario": "release_closure_chain_full_m0_m7",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(root).replace("\\", "/"),
        "elapsed_seconds": round(time.time() - started_at, 4),
        "passed": passed,
        "failed_groups": failed_groups,
        "group_results": group_results,
    }

    output = output_file if output_file.is_absolute() else root / output_file
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(_to_jsonable(report), ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run unified release closure chain for M0-M7")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scratch/reports/release_closure_chain_full_m0_m7_result.json"),
        help="Unified output JSON report path",
    )
    parser.add_argument(
        "--m0-m5-output",
        type=Path,
        default=Path("scratch/reports/release_closure_chain_m0_m5_result.json"),
        help="M0-M5 output JSON report path",
    )
    parser.add_argument(
        "--m6-m7-output",
        type=Path,
        default=Path("scratch/reports/ws22_phase3_release_chain_result.json"),
        help="M6-M7 output JSON report path",
    )
    parser.add_argument("--skip-m0-m5", action="store_true", help="Skip M0-M5 closure chain group")
    parser.add_argument("--skip-m6-m7", action="store_true", help="Skip M6-M7 closure chain group")
    parser.add_argument(
        "--quick-mode",
        action="store_true",
        help="Run lightweight mode (skip heavy regressions and long-run drill)",
    )
    parser.add_argument("--continue-on-failure", action="store_true", help="Continue after group failure")
    parser.add_argument("--timeout-seconds", type=int, default=2400, help="Per-step timeout")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_release_closure_chain_full_m0_m7(
        repo_root=args.repo_root,
        output_file=args.output,
        m0_m5_output_file=args.m0_m5_output,
        m6_m7_output_file=args.m6_m7_output,
        skip_m0_m5=bool(args.skip_m0_m5),
        skip_m6_m7=bool(args.skip_m6_m7),
        quick_mode=bool(args.quick_mode),
        continue_on_failure=bool(args.continue_on_failure),
        timeout_seconds=max(30, int(args.timeout_seconds)),
    )
    print(
        json.dumps(
            {
                "passed": report.get("passed"),
                "failed_groups": report.get("failed_groups"),
                "output": str((args.output if args.output.is_absolute() else (args.repo_root / args.output).resolve())),
            },
            ensure_ascii=False,
        )
    )
    return 0 if bool(report.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
