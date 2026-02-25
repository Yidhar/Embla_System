#!/usr/bin/env python3
"""Manage wall-clock acceptance evidence for WS27-001."""

from __future__ import annotations

import argparse
import json
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


DEFAULT_STATE = Path("scratch/reports/ws27_72h_wallclock_acceptance_ws27_001_state.json")
DEFAULT_OUTPUT = Path("scratch/reports/ws27_72h_wallclock_acceptance_ws27_001.json")
DEFAULT_REQUIRED_REPORTS = (
    Path("scratch/reports/ws27_72h_endurance_ws27_001.json"),
    Path("scratch/reports/release_closure_chain_full_m0_m12_result.json"),
)


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(repo_root: Path, candidate: Path) -> Path:
    return candidate if candidate.is_absolute() else repo_root / candidate


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def start_wallclock_acceptance(
    *,
    repo_root: Path,
    state_file: Path,
    target_hours: float,
    force_restart: bool = False,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    state_path = _resolve_path(root, state_file)

    if state_path.exists() and not force_restart:
        existing = _read_json(state_path)
        if str(existing.get("status")) == "running":
            raise RuntimeError(
                f"wall-clock acceptance already running: state={_to_unix_path(state_path)}; use --force-restart to reset"
            )

    started_epoch = time.time()
    target_hours_normalized = max(1.0, float(target_hours))
    payload = {
        "task_id": "NGA-WS27-001",
        "scenario": "ws27_72h_wallclock_acceptance",
        "status": "running",
        "repo_root": _to_unix_path(root),
        "hostname": socket.gethostname(),
        "started_at": _utc_iso_now(),
        "started_epoch": started_epoch,
        "target_hours": target_hours_normalized,
        "target_seconds": round(target_hours_normalized * 3600.0, 3),
        "last_updated_at": _utc_iso_now(),
    }
    _write_json(state_path, payload)
    payload["state_file"] = _to_unix_path(state_path)
    return payload


def status_wallclock_acceptance(*, repo_root: Path, state_file: Path) -> Dict[str, Any]:
    root = repo_root.resolve()
    state_path = _resolve_path(root, state_file)
    if not state_path.exists():
        raise FileNotFoundError(f"state file not found: {_to_unix_path(state_path)}")

    state = _read_json(state_path)
    started_epoch = float(state.get("started_epoch") or 0.0)
    target_hours = max(1.0, float(state.get("target_hours") or 72.0))
    elapsed_seconds = max(0.0, time.time() - started_epoch)
    target_seconds = target_hours * 3600.0
    target_reached = elapsed_seconds >= target_seconds
    result = {
        "task_id": "NGA-WS27-001",
        "scenario": "ws27_72h_wallclock_acceptance",
        "status": str(state.get("status") or "unknown"),
        "state_file": _to_unix_path(state_path),
        "started_at": state.get("started_at"),
        "target_hours": target_hours,
        "elapsed_hours": round(elapsed_seconds / 3600.0, 6),
        "remaining_hours": round(max(0.0, target_hours - elapsed_seconds / 3600.0), 6),
        "target_reached": bool(target_reached),
        "last_updated_at": _utc_iso_now(),
    }
    return result


def finish_wallclock_acceptance(
    *,
    repo_root: Path,
    state_file: Path,
    output_file: Path,
    required_reports: List[Path],
) -> Dict[str, Any]:
    root = repo_root.resolve()
    state_path = _resolve_path(root, state_file)
    output_path = _resolve_path(root, output_file)
    if not state_path.exists():
        raise FileNotFoundError(f"state file not found: {_to_unix_path(state_path)}")

    state = _read_json(state_path)
    started_epoch = float(state.get("started_epoch") or 0.0)
    target_hours = max(1.0, float(state.get("target_hours") or 72.0))
    elapsed_seconds = max(0.0, time.time() - started_epoch)
    target_seconds = target_hours * 3600.0
    target_reached = elapsed_seconds >= target_seconds

    missing_required_reports: List[str] = []
    for report in required_reports:
        resolved = _resolve_path(root, report)
        if not resolved.exists():
            missing_required_reports.append(_to_unix_path(report))

    checks = {
        "wallclock_target_reached": bool(target_reached),
        "required_reports_present": len(missing_required_reports) == 0,
    }
    passed = all(checks.values())

    report = {
        "task_id": "NGA-WS27-001",
        "scenario": "ws27_72h_wallclock_acceptance",
        "generated_at": _utc_iso_now(),
        "repo_root": _to_unix_path(root),
        "passed": passed,
        "checks": checks,
        "target_hours": target_hours,
        "elapsed_hours": round(elapsed_seconds / 3600.0, 6),
        "started_at": state.get("started_at"),
        "finished_at": _utc_iso_now(),
        "state_file": _to_unix_path(state_path),
        "missing_required_reports": missing_required_reports,
    }
    _write_json(output_path, report)

    state["status"] = "finished"
    state["finished_at"] = report["finished_at"]
    state["last_updated_at"] = report["finished_at"]
    state["final_report"] = _to_unix_path(output_path)
    _write_json(state_path, state)

    report["output_file"] = _to_unix_path(output_path)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage WS27-001 wall-clock acceptance evidence")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument(
        "--action",
        choices=("start", "status", "finish"),
        required=True,
        help="Action to run",
    )
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE, help="State JSON path")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Final acceptance report JSON path")
    parser.add_argument("--target-hours", type=float, default=72.0, help="Wall-clock target hours (start only)")
    parser.add_argument(
        "--required-report",
        action="append",
        default=[],
        help="Required report path for finish action; repeatable",
    )
    parser.add_argument("--force-restart", action="store_true", help="Allow start action to overwrite running state")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when finish checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    required_reports = [Path(item) for item in args.required_report] if args.required_report else list(DEFAULT_REQUIRED_REPORTS)

    if args.action == "start":
        result = start_wallclock_acceptance(
            repo_root=args.repo_root,
            state_file=args.state,
            target_hours=float(args.target_hours),
            force_restart=bool(args.force_restart),
        )
    elif args.action == "status":
        result = status_wallclock_acceptance(
            repo_root=args.repo_root,
            state_file=args.state,
        )
    else:
        result = finish_wallclock_acceptance(
            repo_root=args.repo_root,
            state_file=args.state,
            output_file=args.output,
            required_reports=required_reports,
        )

    print(json.dumps(result, ensure_ascii=False))
    if args.action == "finish" and args.strict and not bool(result.get("passed")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
