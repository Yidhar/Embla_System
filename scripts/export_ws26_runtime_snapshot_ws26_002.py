#!/usr/bin/env python3
"""Export WS26-002 unified runtime metrics snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from scripts.export_slo_snapshot import build_snapshot


def _build_ws26_report(*, snapshot: Dict[str, Any], output_file: Path) -> Dict[str, Any]:
    metrics = snapshot.get("metrics") if isinstance(snapshot.get("metrics"), dict) else {}
    runtime_rollout = metrics.get("runtime_rollout") if isinstance(metrics.get("runtime_rollout"), dict) else {}
    runtime_fail_open = metrics.get("runtime_fail_open") if isinstance(metrics.get("runtime_fail_open"), dict) else {}
    runtime_lease = metrics.get("runtime_lease") if isinstance(metrics.get("runtime_lease"), dict) else {}

    checks = {
        "has_runtime_rollout": bool(runtime_rollout),
        "has_runtime_fail_open": bool(runtime_fail_open),
        "has_runtime_lease": bool(runtime_lease),
    }
    passed = all(checks.values())
    return {
        "task_id": "NGA-WS26-002",
        "scenario": "runtime_rollout_fail_open_lease_unified_snapshot",
        "generated_at": snapshot.get("generated_at"),
        "project_root": snapshot.get("project_root"),
        "output_file": str(output_file).replace("\\", "/"),
        "passed": passed,
        "checks": checks,
        "summary": {
            "rollout_hit_ratio": runtime_rollout.get("value"),
            "fail_open_ratio": runtime_fail_open.get("value"),
            "fail_open_budget_exhausted": runtime_fail_open.get("budget_exhausted"),
            "lease_status": runtime_lease.get("status"),
        },
        "metrics": {
            "runtime_rollout": runtime_rollout,
            "runtime_fail_open": runtime_fail_open,
            "runtime_lease": runtime_lease,
        },
        "sources": snapshot.get("sources", {}),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export WS26-002 unified runtime metrics snapshot")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scratch/reports/ws26_runtime_snapshot_ws26_002.json"),
        help="Output JSON report path",
    )
    parser.add_argument("--events-limit", type=int, default=20000, help="Maximum event rows scanned")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    output_file = args.output if args.output.is_absolute() else repo_root / args.output

    snapshot = build_snapshot(
        repo_root=repo_root,
        events_limit=max(1, int(args.events_limit)),
    )
    report = _build_ws26_report(snapshot=snapshot, output_file=output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report.get("passed"), "output": str(output_file).replace("\\", "/")}, ensure_ascii=False))
    return 0 if bool(report.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
