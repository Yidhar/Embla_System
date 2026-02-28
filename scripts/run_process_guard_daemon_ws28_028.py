#!/usr/bin/env python3
"""Run/manage process guard daemon for zombie/orphan containment."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from core.supervisor.process_guard import ProcessGuardDaemon, ProcessGuardThresholds


TASK_ID = "NGA-WS28-028"
SCENARIO = "process_guard_daemon"
REPORT_SCHEMA_VERSION = "ws28_028_process_guard_daemon.v1"
DEFAULT_STATE_FILE = Path("scratch/runtime/process_guard_state_ws28_028.json")
DEFAULT_OUTPUT = Path("scratch/reports/process_guard_daemon_ws28_028.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_process_guard_daemon_ws28_028(
    *,
    repo_root: Path,
    mode: str,
    state_file: Path = DEFAULT_STATE_FILE,
    output_file: Path = DEFAULT_OUTPUT,
    interval_seconds: float = 5.0,
    max_ticks: int = 1,
    stale_job_seconds: float = 180.0,
    auto_reap: bool = True,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    state_path = _resolve(root, state_file)
    output_path = _resolve(root, output_file)
    normalized_mode = str(mode or "run").strip().lower()

    daemon = ProcessGuardDaemon(
        thresholds=ProcessGuardThresholds(stale_job_seconds=max(1.0, float(stale_job_seconds))),
    )
    checks: Dict[str, Any] = {}
    state_summary: Dict[str, Any]
    daemon_run: Dict[str, Any] = {}

    if normalized_mode == "run":
        daemon_run = daemon.run_daemon(
            state_file=state_path,
            interval_seconds=max(0.0, float(interval_seconds)),
            max_ticks=max(1, int(max_ticks)),
            auto_reap=bool(auto_reap),
        )
        state_summary = ProcessGuardDaemon.read_daemon_state(state_path)
        checks = {
            "state_file_exists": state_path.exists(),
            "ticks_completed_positive": int(daemon_run.get("ticks_completed") or 0) >= 1,
            "state_status_known": str(state_summary.get("status") or "") in {"ok", "warning", "critical"},
        }
    elif normalized_mode == "status":
        state_summary = ProcessGuardDaemon.read_daemon_state(state_path)
        checks = {
            "state_file_exists": state_path.exists(),
            "state_status_known": str(state_summary.get("status") or "") in {"ok", "warning", "critical"},
        }
    else:
        raise ValueError(f"unsupported mode: {mode}")

    report: Dict[str, Any] = {
        "task_id": TASK_ID,
        "scenario": SCENARIO,
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "repo_root": _to_unix(root),
        "mode": normalized_mode,
        "checks": checks,
        "passed": all(bool(value) for value in checks.values()),
        "state_file": _to_unix(state_path),
        "state_summary": state_summary,
    }
    if daemon_run:
        report["daemon_run"] = daemon_run

    _write_json(output_path, report)
    report["output_file"] = _to_unix(output_path)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run process guard daemon (WS28-028)")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root path")
    parser.add_argument("--mode", choices=("run", "status"), default="run", help="run/status")
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE, help="Process guard state file path")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output report path")
    parser.add_argument("--interval-seconds", type=float, default=5.0, help="Daemon interval seconds")
    parser.add_argument("--max-ticks", type=int, default=1, help="Daemon max ticks")
    parser.add_argument("--stale-job-seconds", type=float, default=180.0, help="Stale running-job threshold in seconds")
    parser.add_argument("--auto-reap", action="store_true", help="Enable orphan-job auto reap")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_process_guard_daemon_ws28_028(
        repo_root=args.repo_root,
        mode=args.mode,
        state_file=args.state_file,
        output_file=args.output,
        interval_seconds=args.interval_seconds,
        max_ticks=args.max_ticks,
        stale_job_seconds=args.stale_job_seconds,
        auto_reap=bool(args.auto_reap),
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
