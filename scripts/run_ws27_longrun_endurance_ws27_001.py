#!/usr/bin/env python3
"""Run WS27-001 72h endurance and disk quota pressure baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from autonomous.ws27_longrun_endurance import WS27LongRunConfig, run_ws27_72h_endurance_baseline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS27-001 72h endurance and disk quota pressure baseline")
    parser.add_argument("--scratch-root", type=Path, default=Path("scratch/ws27_72h_endurance"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scratch/reports/ws27_72h_endurance_ws27_001.json"),
        help="Output JSON report path",
    )
    parser.add_argument("--target-hours", type=float, default=72.0, help="Virtual endurance target in hours")
    parser.add_argument("--virtual-round-seconds", type=float, default=300.0, help="Virtual seconds per round")
    parser.add_argument("--artifact-payload-kb", type=int, default=128, help="Artifact payload size per round (KB)")
    parser.add_argument("--max-total-size-mb", type=int, default=24, help="Artifact store total size quota (MB)")
    parser.add_argument("--max-single-artifact-mb", type=int, default=2, help="Single artifact quota (MB)")
    parser.add_argument("--max-artifact-count", type=int, default=4096, help="Artifact count quota")
    parser.add_argument("--high-watermark-ratio", type=float, default=0.85, help="High watermark ratio")
    parser.add_argument("--low-watermark-ratio", type=float, default=0.65, help="Low watermark ratio")
    parser.add_argument("--critical-reserve-ratio", type=float, default=0.10, help="Critical reserve ratio")
    parser.add_argument("--normal-priority-every", type=int, default=12, help="Use normal priority every N rounds")
    parser.add_argument("--high-priority-every", type=int, default=48, help="Use high priority every N rounds")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_ws27_72h_endurance_baseline(
        scratch_root=args.scratch_root,
        report_file=args.output,
        config=WS27LongRunConfig(
            target_hours=max(1.0 / 60.0, float(args.target_hours)),
            virtual_round_seconds=max(1.0, float(args.virtual_round_seconds)),
            artifact_payload_kb=max(1, int(args.artifact_payload_kb)),
            max_total_size_mb=max(1, int(args.max_total_size_mb)),
            max_single_artifact_mb=max(1, int(args.max_single_artifact_mb)),
            max_artifact_count=max(16, int(args.max_artifact_count)),
            high_watermark_ratio=float(args.high_watermark_ratio),
            low_watermark_ratio=float(args.low_watermark_ratio),
            critical_reserve_ratio=float(args.critical_reserve_ratio),
            normal_priority_every=max(1, int(args.normal_priority_every)),
            high_priority_every=max(1, int(args.high_priority_every)),
        ),
    )
    print(
        json.dumps(
            {
                "passed": bool(report.get("passed")),
                "checks": report.get("checks", {}),
                "output": str(args.output).replace("\\", "/"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if bool(report.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
