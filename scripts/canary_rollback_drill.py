#!/usr/bin/env python3
"""NGA-WS17-007: canary + auto-rollback drill runner."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from agents.release import CanaryThresholds, ReleaseController


def _scenario_observations(name: str) -> List[Dict[str, Any]]:
    normalized = (name or "rollback").strip().lower()
    if normalized == "promote":
        return [
            {"window_minutes": 15, "sample_count": 240, "error_rate": 0.01, "latency_p95_ms": 900, "kpi_ratio": 0.99},
            {"window_minutes": 15, "sample_count": 260, "error_rate": 0.011, "latency_p95_ms": 950, "kpi_ratio": 1.0},
            {"window_minutes": 15, "sample_count": 220, "error_rate": 0.009, "latency_p95_ms": 980, "kpi_ratio": 0.98},
        ]
    if normalized == "observing":
        return [{"window_minutes": 5, "sample_count": 10, "error_rate": 0.2, "latency_p95_ms": 4000, "kpi_ratio": 0.5}]
    return [
        {"window_minutes": 15, "sample_count": 220, "error_rate": 0.18, "latency_p95_ms": 3200, "kpi_ratio": 0.82},
        {"window_minutes": 15, "sample_count": 210, "error_rate": 0.21, "latency_p95_ms": 3600, "kpi_ratio": 0.76},
    ]


def _load_observations(path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"observations file must be a JSON array: {path}")
    rows: List[Dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict):
            rows.append(dict(item))
    return rows


def run_drill(
    *,
    repo_dir: Path,
    policy_path: Path,
    thresholds: CanaryThresholds,
    observations: List[Dict[str, Any]],
    auto_rollback_enabled: bool,
    rollback_command: str,
    scenario: str,
) -> Dict[str, Any]:
    controller = ReleaseController(
        repo_dir=str(repo_dir),
        policy_path=policy_path,
        thresholds=thresholds,
    )
    decision, rollback_result = controller.evaluate_and_execute_rollback(
        observations,
        auto_rollback_enabled=auto_rollback_enabled,
        rollback_command=rollback_command,
    )
    return {
        "report_version": "ws17-007-v1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "scenario": scenario,
        "decision": {
            "outcome": decision.outcome,
            "reason": decision.reason,
            "trigger_window_index": decision.trigger_window_index,
            "stats": decision.stats,
            "threshold_snapshot": decision.threshold_snapshot,
            "policy_snapshot": decision.policy_snapshot,
            "evaluated_windows": decision.evaluated_windows,
        },
        "rollback_result": rollback_result,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run canary rollback drill and export JSON report")
    parser.add_argument("--repo-dir", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--policy-path", type=Path, default=Path("policy/gate_policy.yaml"), help="Gate policy path")
    parser.add_argument(
        "--scenario",
        choices=["rollback", "promote", "observing"],
        default="rollback",
        help="Built-in observations scenario when --observations-file is not provided",
    )
    parser.add_argument("--observations-file", type=Path, default=None, help="Custom observations JSON array")
    parser.add_argument("--max-error-rate", type=float, default=0.02, help="Canary max error rate")
    parser.add_argument("--max-latency-p95-ms", type=float, default=1500.0, help="Canary max p95 latency (ms)")
    parser.add_argument("--min-kpi-ratio", type=float, default=0.95, help="Canary min KPI ratio")
    parser.add_argument(
        "--auto-rollback-enabled",
        action="store_true",
        help="Execute rollback command automatically when decision is rollback",
    )
    parser.add_argument("--rollback-command", type=str, default="", help="Rollback command to execute when enabled")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compatibility flag. Parsed for legacy release chains; execution remains non-destructive by default.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("logs/runtime/canary_rollback_drill_report.json"),
        help="Report output JSON path",
    )
    parser.add_argument("--stdout-only", action="store_true", help="Print JSON report only without writing file")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_dir = args.repo_dir.resolve()
    policy_path = args.policy_path
    if not policy_path.is_absolute():
        policy_path = repo_dir / policy_path

    if args.observations_file is not None:
        observations_path = args.observations_file.resolve()
        observations = _load_observations(observations_path)
        scenario = "custom"
    else:
        observations = _scenario_observations(args.scenario)
        scenario = args.scenario

    thresholds = CanaryThresholds(
        max_error_rate=max(0.0, float(args.max_error_rate)),
        max_latency_p95_ms=max(1.0, float(args.max_latency_p95_ms)),
        min_kpi_ratio=max(0.0, min(1.0, float(args.min_kpi_ratio))),
    )
    report = run_drill(
        repo_dir=repo_dir,
        policy_path=policy_path,
        thresholds=thresholds,
        observations=observations,
        auto_rollback_enabled=bool(args.auto_rollback_enabled),
        rollback_command=str(args.rollback_command or ""),
        scenario=scenario,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if not args.stdout_only:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
        print(f"[report] wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
