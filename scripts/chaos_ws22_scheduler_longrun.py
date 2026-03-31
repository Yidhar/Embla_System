"""WS22-004 scheduler long-run equivalent drill."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agents.runtime.ws22_longrun_baseline import WS22LongRunConfig, run_ws22_longrun_baseline


def main() -> int:
    parser = argparse.ArgumentParser(description="Run WS22-004 scheduler long-run equivalent baseline drill")
    parser.add_argument("--rounds", type=int, default=120)
    parser.add_argument("--virtual-round-seconds", type=float, default=5.0)
    parser.add_argument("--fail-open-every", type=int, default=15)
    parser.add_argument("--lease-renew-every", type=int, default=20)
    parser.add_argument("--scratch-root", type=Path, default=Path("scratch/ws22_longrun_baseline"))
    parser.add_argument(
        "--report-file",
        type=Path,
        default=Path("scratch/reports/ws22_scheduler_longrun_baseline.json"),
    )
    args = parser.parse_args()

    report = run_ws22_longrun_baseline(
        scratch_root=args.scratch_root,
        report_file=args.report_file,
        config=WS22LongRunConfig(
            rounds=max(1, int(args.rounds)),
            virtual_round_seconds=max(0.1, float(args.virtual_round_seconds)),
            fail_open_every=max(1, int(args.fail_open_every)),
            lease_renew_every=max(1, int(args.lease_renew_every)),
        ),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if bool(report.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
