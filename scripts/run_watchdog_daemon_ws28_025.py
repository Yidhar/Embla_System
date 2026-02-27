#!/usr/bin/env python3
"""Run/manage watchdog daemon resident loop for WS28-025."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from system.watchdog_daemon import WatchdogDaemon, WatchdogThresholds


TASK_ID = "NGA-WS28-025"
SCENARIO = "watchdog_daemon_resident_loop"
REPORT_SCHEMA_VERSION = "ws28_025_watchdog_daemon_run.v1"
DEFAULT_STATE_FILE = Path("scratch/runtime/watchdog_daemon_state_ws28_025.json")
DEFAULT_OUTPUT = Path("scratch/reports/watchdog_daemon_ws28_025.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(repo_root: Path, candidate: Path) -> Path:
    return candidate if candidate.is_absolute() else repo_root / candidate


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_watchdog_daemon_ws28_025(
    *,
    repo_root: Path,
    mode: str,
    state_file: Path = DEFAULT_STATE_FILE,
    output_file: Path = DEFAULT_OUTPUT,
    interval_seconds: float = 5.0,
    max_ticks: int = 1,
    warn_only: bool = True,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    normalized_mode = str(mode or "run").strip().lower()
    state_path = _resolve_path(root, state_file)
    output_path = _resolve_path(root, output_file)
    checks: Dict[str, Any] = {}
    daemon_run: Dict[str, Any] = {}

    if normalized_mode == "run":
        daemon = WatchdogDaemon(
            thresholds=WatchdogThresholds(),
            warn_only=bool(warn_only),
        )
        daemon_run = daemon.run_daemon(
            state_file=state_path,
            interval_seconds=max(0.0, float(interval_seconds)),
            max_ticks=max(1, int(max_ticks)),
        )
        state_summary = WatchdogDaemon.read_daemon_state(state_path)
        checks = {
            "state_file_exists": state_path.exists(),
            "ticks_completed_positive": int(daemon_run.get("ticks_completed") or 0) >= 1,
            "state_status_known": str(state_summary.get("status") or "") in {"ok", "warning", "critical"},
            "state_not_stale": str(state_summary.get("reason_code") or "")
            not in {"WATCHDOG_DAEMON_STALE_WARNING", "WATCHDOG_DAEMON_STALE_CRITICAL"},
            "state_payload_tick_positive": int(state_summary.get("tick") or 0) >= 1,
        }
    elif normalized_mode == "status":
        state_summary = WatchdogDaemon.read_daemon_state(state_path)
        checks = {
            "state_file_exists": state_path.exists(),
            "state_status_known": str(state_summary.get("status") or "") in {"ok", "warning", "critical"},
            "state_not_stale": str(state_summary.get("reason_code") or "")
            not in {"WATCHDOG_DAEMON_STALE_WARNING", "WATCHDOG_DAEMON_STALE_CRITICAL"},
        }
    else:
        raise ValueError(f"unsupported mode: {mode}")

    passed = all(bool(value) for value in checks.values())
    report: Dict[str, Any] = {
        "task_id": TASK_ID,
        "scenario": SCENARIO,
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "repo_root": _to_unix(root),
        "mode": normalized_mode,
        "passed": passed,
        "checks": checks,
        "state_file": _to_unix(state_path),
        "state_summary": state_summary,
    }
    if daemon_run:
        report["daemon_run"] = daemon_run

    _write_json(output_path, report)
    report["output_file"] = _to_unix(output_path)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run watchdog daemon resident loop (WS28-025)")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root path")
    parser.add_argument("--mode", choices=("run", "status"), default="run", help="run: execute daemon loop once; status: inspect state file")
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE, help="Watchdog state file path")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output report path")
    parser.add_argument("--interval-seconds", type=float, default=5.0, help="Daemon sampling interval")
    parser.add_argument("--max-ticks", type=int, default=1, help="Daemon loop ticks")
    parser.add_argument("--warn-only", action="store_true", help="Enable warn-only watchdog actions")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_watchdog_daemon_ws28_025(
        repo_root=args.repo_root,
        mode=args.mode,
        state_file=args.state_file,
        output_file=args.output,
        interval_seconds=args.interval_seconds,
        max_ticks=args.max_ticks,
        warn_only=args.warn_only,
    )
    print(
        json.dumps(
            {
                "passed": bool(report.get("passed")),
                "checks": report.get("checks", {}),
                "output": report.get("output_file"),
            },
            ensure_ascii=False,
        )
    )
    if args.strict and not bool(report.get("passed")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
