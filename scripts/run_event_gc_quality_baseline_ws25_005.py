#!/usr/bin/env python3
"""Run WS25-005 Event/GC quality baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agents.runtime.ws25_event_gc_quality_baseline import WS25EventGCQualityConfig, run_ws25_event_gc_quality_baseline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS25-005 Event/GC quality baseline")
    parser.add_argument("--scratch-root", type=Path, default=Path("scratch/ws25_event_gc_quality_baseline"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scratch/reports/ws25_event_gc_quality_baseline.json"),
        help="Output JSON report path",
    )
    parser.add_argument("--replay-event-count", type=int, default=3, help="Replay idempotency drill event count")
    parser.add_argument("--gc-iterations", type=int, default=3, help="GC quality evaluation iterations")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_ws25_event_gc_quality_baseline(
        scratch_root=args.scratch_root,
        report_file=args.output,
        config=WS25EventGCQualityConfig(
            replay_event_count=max(1, int(args.replay_event_count)),
            gc_iterations=max(1, int(args.gc_iterations)),
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
