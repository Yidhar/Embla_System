#!/usr/bin/env python3
"""Manage brainstem control-plane daemon lifecycle for WS28-017."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


DEFAULT_STATE_FILE = Path("scratch/runtime/brainstem_control_plane_manager_ws28_017_state.json")
DEFAULT_HEARTBEAT_FILE = Path("scratch/runtime/brainstem_control_plane_heartbeat_ws23_001.json")
DEFAULT_SUPERVISOR_SCRIPT = Path("scripts/run_brainstem_supervisor_ws23_001.py")
DEFAULT_SPEC_FILE = Path("system/brainstem_services.spec")
DEFAULT_SUPERVISOR_OUTPUT = Path("scratch/reports/brainstem_supervisor_entry_ws23_001.json")
DEFAULT_MANAGER_LOG = Path("logs/autonomous/brainstem_control_plane_manager_ws28_017.log")
DEFAULT_OUTPUT = Path("scratch/reports/brainstem_control_plane_manage_ws28_017.json")
REPORT_SCHEMA_VERSION = "ws28_017_brainstem_control_plane_manage.v1"

_HEARTBEAT_STALE_WARNING_SECONDS = 120.0
_HEARTBEAT_STALE_CRITICAL_SECONDS = 300.0


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(repo_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _finalize_report(*, repo_root: Path, output_file: Path, report: Dict[str, Any]) -> Dict[str, Any]:
    output_path = _resolve_path(repo_root.resolve(), output_file)
    finalized = dict(report)
    finalized["report_schema_version"] = REPORT_SCHEMA_VERSION
    finalized["output_file"] = _to_unix_path(output_path)
    _write_json(output_path, finalized)
    return finalized


def _parse_iso_datetime(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _pid_alive(pid: int) -> bool:
    if int(pid) <= 0:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _build_heartbeat_status(heartbeat_file: Path) -> Dict[str, Any]:
    payload = _read_json(heartbeat_file)
    generated_at = str(payload.get("generated_at") or "")
    generated_ts = _parse_iso_datetime(generated_at)
    heartbeat_age_seconds: float | None = None
    if generated_ts is not None:
        heartbeat_age_seconds = max(0.0, round(time.time() - generated_ts, 3))
    unhealthy_services = payload.get("unhealthy_services")
    unhealthy = (
        [str(item) for item in unhealthy_services if str(item).strip()]
        if isinstance(unhealthy_services, list)
        else []
    )
    daemon_pid = int(payload.get("pid") or 0)
    daemon_alive = _pid_alive(daemon_pid)
    healthy_flag = payload.get("healthy") is True

    checks = {
        "heartbeat_exists": heartbeat_file.exists(),
        "generated_at_valid": generated_ts is not None,
        "heartbeat_not_stale_critical": bool(
            heartbeat_age_seconds is not None and heartbeat_age_seconds <= float(_HEARTBEAT_STALE_CRITICAL_SECONDS)
        ),
        "healthy_flag_true": healthy_flag,
        "daemon_pid_alive": daemon_alive,
        "unhealthy_services_empty": len(unhealthy) == 0,
    }
    reasons: List[str] = []
    if not checks["heartbeat_exists"]:
        reasons.append("heartbeat_missing")
    if checks["heartbeat_exists"] and not checks["generated_at_valid"]:
        reasons.append("heartbeat_generated_at_invalid")
    if checks["generated_at_valid"] and not checks["heartbeat_not_stale_critical"]:
        reasons.append("heartbeat_stale_critical")
    if checks["heartbeat_exists"] and not checks["healthy_flag_true"]:
        reasons.append("healthy_flag_false_or_missing")
    if checks["heartbeat_exists"] and not checks["daemon_pid_alive"]:
        reasons.append("daemon_pid_not_alive")
    if checks["heartbeat_exists"] and not checks["unhealthy_services_empty"]:
        reasons.append("unhealthy_services_present")

    passed = all(checks.values())
    return {
        "passed": passed,
        "checks": checks,
        "reasons": reasons,
        "path": _to_unix_path(heartbeat_file),
        "generated_at": generated_at,
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "stale_warning_seconds": float(_HEARTBEAT_STALE_WARNING_SECONDS),
        "stale_critical_seconds": float(_HEARTBEAT_STALE_CRITICAL_SECONDS),
        "pid": daemon_pid,
        "healthy": payload.get("healthy"),
        "service_count": int(payload.get("service_count") or 0),
        "tick": int(payload.get("tick") or 0),
        "unhealthy_services": unhealthy,
    }


def _wait_for_heartbeat(heartbeat_file: Path, *, timeout_seconds: float) -> Dict[str, Any]:
    deadline = time.time() + max(0.5, float(timeout_seconds))
    last_snapshot = _build_heartbeat_status(heartbeat_file)
    while time.time() <= deadline:
        snapshot = _build_heartbeat_status(heartbeat_file)
        last_snapshot = snapshot
        if snapshot["checks"]["heartbeat_exists"] and snapshot["checks"]["generated_at_valid"]:
            return snapshot
        time.sleep(0.2)
    return last_snapshot


def _terminate_pid(pid: int, *, timeout_seconds: float) -> bool:
    target_pid = int(pid)
    if target_pid <= 0:
        return True
    if not _pid_alive(target_pid):
        return True
    try:
        os.kill(target_pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return not _pid_alive(target_pid)

    deadline = time.time() + max(0.2, float(timeout_seconds))
    while time.time() <= deadline:
        if not _pid_alive(target_pid):
            return True
        time.sleep(0.1)

    try:
        os.kill(target_pid, signal.SIGKILL)
    except (AttributeError, ProcessLookupError, PermissionError):
        return not _pid_alive(target_pid)
    return not _pid_alive(target_pid)


def _build_daemon_command(
    *,
    python_executable: str,
    supervisor_script: Path,
    state_file: Path,
    spec_file: Path,
    heartbeat_file: Path,
    interval_seconds: float,
    max_ticks: int,
    supervisor_output: Path,
) -> List[str]:
    return [
        python_executable,
        _to_unix_path(supervisor_script),
        "--mode",
        "daemon",
        "--state-file",
        _to_unix_path(state_file),
        "--spec-file",
        _to_unix_path(spec_file),
        "--heartbeat-file",
        _to_unix_path(heartbeat_file),
        "--interval-seconds",
        str(max(0.0, float(interval_seconds))),
        "--max-ticks",
        str(max(1, int(max_ticks))),
        "--output",
        _to_unix_path(supervisor_output),
    ]


def start_brainstem_control_plane(
    *,
    repo_root: Path,
    state_file: Path,
    heartbeat_file: Path,
    supervisor_script: Path,
    spec_file: Path,
    supervisor_output: Path,
    manager_log: Path,
    interval_seconds: float = 5.0,
    max_ticks: int = 1000000000,
    start_timeout_seconds: float = 8.0,
    force_restart: bool = False,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    state_path = _resolve_path(root, state_file)
    heartbeat_path = _resolve_path(root, heartbeat_file)
    supervisor_script_path = _resolve_path(root, supervisor_script)
    spec_file_path = _resolve_path(root, spec_file)
    supervisor_output_path = _resolve_path(root, supervisor_output)
    manager_log_path = _resolve_path(root, manager_log)

    if not force_restart:
        current = _build_heartbeat_status(heartbeat_path)
        if bool(current.get("passed")):
            report = {
                "task_id": "NGA-WS28-017",
                "scenario": "brainstem_control_plane_manage",
                "generated_at": _utc_iso_now(),
                "action": "start",
                "passed": True,
                "status": "already_running",
                "repo_root": _to_unix_path(root),
                "checks": {
                    "already_running": True,
                    "spawned": False,
                    "heartbeat_detected": True,
                },
                "heartbeat": current,
                "state_file": _to_unix_path(state_path),
                "heartbeat_file": _to_unix_path(heartbeat_path),
            }
            _write_json(state_path, report)
            return report

    command = _build_daemon_command(
        python_executable=sys.executable,
        supervisor_script=supervisor_script_path,
        state_file=state_path,
        spec_file=spec_file_path,
        heartbeat_file=heartbeat_path,
        interval_seconds=interval_seconds,
        max_ticks=max_ticks,
        supervisor_output=supervisor_output_path,
    )
    manager_log_path.parent.mkdir(parents=True, exist_ok=True)
    with manager_log_path.open("a", encoding="utf-8") as log_handle:
        process = subprocess.Popen(  # noqa: S603
            command,
            cwd=str(root),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    heartbeat_snapshot = _wait_for_heartbeat(heartbeat_path, timeout_seconds=start_timeout_seconds)
    checks = {
        "spawned": int(process.pid) > 0,
        "heartbeat_detected": bool(heartbeat_snapshot.get("checks", {}).get("heartbeat_exists")),
        "heartbeat_generated_at_valid": bool(heartbeat_snapshot.get("checks", {}).get("generated_at_valid")),
        "daemon_pid_alive": bool(heartbeat_snapshot.get("checks", {}).get("daemon_pid_alive")),
    }
    passed = all(checks.values())

    state_payload = {
        "task_id": "NGA-WS28-017",
        "scenario": "brainstem_control_plane_manage",
        "generated_at": _utc_iso_now(),
        "status": "running" if passed else "degraded",
        "action": "start",
        "repo_root": _to_unix_path(root),
        "launcher_pid": int(process.pid),
        "heartbeat_pid": int(heartbeat_snapshot.get("pid") or 0),
        "command": command,
        "state_file": _to_unix_path(state_path),
        "heartbeat_file": _to_unix_path(heartbeat_path),
        "supervisor_output": _to_unix_path(supervisor_output_path),
        "manager_log": _to_unix_path(manager_log_path),
        "checks": checks,
    }
    _write_json(state_path, state_payload)
    return {
        "task_id": "NGA-WS28-017",
        "scenario": "brainstem_control_plane_manage",
        "generated_at": _utc_iso_now(),
        "action": "start",
        "passed": passed,
        "repo_root": _to_unix_path(root),
        "checks": checks,
        "heartbeat": heartbeat_snapshot,
        "state_file": _to_unix_path(state_path),
        "heartbeat_file": _to_unix_path(heartbeat_path),
        "manager_log": _to_unix_path(manager_log_path),
        "launcher_pid": int(process.pid),
        "heartbeat_pid": int(heartbeat_snapshot.get("pid") or 0),
        "command": command,
    }


def status_brainstem_control_plane(
    *,
    repo_root: Path,
    state_file: Path,
    heartbeat_file: Path,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    state_path = _resolve_path(root, state_file)
    heartbeat_path = _resolve_path(root, heartbeat_file)
    manager_state = _read_json(state_path)
    heartbeat = _build_heartbeat_status(heartbeat_path)
    launcher_pid = int(manager_state.get("launcher_pid") or 0)
    launcher_pid_alive = _pid_alive(launcher_pid) if launcher_pid > 0 else True
    checks = {
        "manager_state_exists": state_path.exists(),
        "heartbeat_gate": bool(heartbeat.get("passed")),
        "launcher_pid_alive": launcher_pid_alive,
    }
    reasons: List[str] = []
    if not checks["manager_state_exists"]:
        reasons.append("manager_state_missing")
    if not checks["heartbeat_gate"]:
        reasons.extend([f"heartbeat:{item}" for item in list(heartbeat.get("reasons") or [])])
    if launcher_pid > 0 and not checks["launcher_pid_alive"]:
        reasons.append("launcher_pid_not_alive")
    passed = checks["heartbeat_gate"] and checks["launcher_pid_alive"]
    return {
        "task_id": "NGA-WS28-017",
        "scenario": "brainstem_control_plane_manage",
        "generated_at": _utc_iso_now(),
        "action": "status",
        "passed": passed,
        "repo_root": _to_unix_path(root),
        "checks": checks,
        "reasons": reasons,
        "state_file": _to_unix_path(state_path),
        "heartbeat_file": _to_unix_path(heartbeat_path),
        "manager_state": manager_state,
        "heartbeat": heartbeat,
    }


def stop_brainstem_control_plane(
    *,
    repo_root: Path,
    state_file: Path,
    heartbeat_file: Path,
    stop_timeout_seconds: float = 3.0,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    state_path = _resolve_path(root, state_file)
    heartbeat_path = _resolve_path(root, heartbeat_file)
    state_payload = _read_json(state_path)
    heartbeat_payload = _read_json(heartbeat_path)

    target_pids = sorted(
        {
            int(state_payload.get("launcher_pid") or 0),
            int(heartbeat_payload.get("pid") or 0),
        }
        - {0}
    )
    termination_results: Dict[str, bool] = {}
    for pid in target_pids:
        termination_results[str(pid)] = _terminate_pid(pid, timeout_seconds=stop_timeout_seconds)

    remaining_pids = [pid for pid in target_pids if _pid_alive(pid)]
    passed = len(remaining_pids) == 0

    updated_state = {
        "task_id": "NGA-WS28-017",
        "scenario": "brainstem_control_plane_manage",
        "generated_at": _utc_iso_now(),
        "status": "stopped" if passed else "stop_failed",
        "action": "stop",
        "state_file": _to_unix_path(state_path),
        "heartbeat_file": _to_unix_path(heartbeat_path),
        "target_pids": target_pids,
        "termination_results": termination_results,
        "remaining_pids": remaining_pids,
    }
    _write_json(state_path, updated_state)
    return {
        "task_id": "NGA-WS28-017",
        "scenario": "brainstem_control_plane_manage",
        "generated_at": _utc_iso_now(),
        "action": "stop",
        "passed": passed,
        "repo_root": _to_unix_path(root),
        "checks": {
            "target_pid_count": len(target_pids),
            "all_pids_stopped": passed,
        },
        "termination_results": termination_results,
        "remaining_pids": remaining_pids,
        "state_file": _to_unix_path(state_path),
        "heartbeat_file": _to_unix_path(heartbeat_path),
    }


def run_manage_brainstem_control_plane_ws28_017(
    *,
    repo_root: Path,
    action: str,
    state_file: Path = DEFAULT_STATE_FILE,
    heartbeat_file: Path = DEFAULT_HEARTBEAT_FILE,
    supervisor_script: Path = DEFAULT_SUPERVISOR_SCRIPT,
    spec_file: Path = DEFAULT_SPEC_FILE,
    supervisor_output: Path = DEFAULT_SUPERVISOR_OUTPUT,
    manager_log: Path = DEFAULT_MANAGER_LOG,
    output_file: Path = DEFAULT_OUTPUT,
    interval_seconds: float = 5.0,
    max_ticks: int = 1000000000,
    start_timeout_seconds: float = 8.0,
    stop_timeout_seconds: float = 3.0,
    force_restart: bool = False,
) -> Dict[str, Any]:
    normalized_action = str(action or "").strip().lower()
    if normalized_action == "start":
        report = start_brainstem_control_plane(
            repo_root=repo_root,
            state_file=state_file,
            heartbeat_file=heartbeat_file,
            supervisor_script=supervisor_script,
            spec_file=spec_file,
            supervisor_output=supervisor_output,
            manager_log=manager_log,
            interval_seconds=interval_seconds,
            max_ticks=max_ticks,
            start_timeout_seconds=start_timeout_seconds,
            force_restart=force_restart,
        )
    elif normalized_action == "status":
        report = status_brainstem_control_plane(
            repo_root=repo_root,
            state_file=state_file,
            heartbeat_file=heartbeat_file,
        )
    elif normalized_action == "stop":
        report = stop_brainstem_control_plane(
            repo_root=repo_root,
            state_file=state_file,
            heartbeat_file=heartbeat_file,
            stop_timeout_seconds=stop_timeout_seconds,
        )
    else:
        raise ValueError(f"unsupported action: {action}")
    return _finalize_report(repo_root=repo_root, output_file=output_file, report=report)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage WS28-017 brainstem control-plane daemon")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--action", choices=("start", "status", "stop"), required=True, help="Action to run")
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE, help="Manager state JSON path")
    parser.add_argument("--heartbeat-file", type=Path, default=DEFAULT_HEARTBEAT_FILE, help="Heartbeat JSON path")
    parser.add_argument(
        "--supervisor-script",
        type=Path,
        default=DEFAULT_SUPERVISOR_SCRIPT,
        help="Supervisor entry script path",
    )
    parser.add_argument("--spec-file", type=Path, default=DEFAULT_SPEC_FILE, help="Brainstem services spec path")
    parser.add_argument(
        "--supervisor-output",
        type=Path,
        default=DEFAULT_SUPERVISOR_OUTPUT,
        help="Supervisor report output path",
    )
    parser.add_argument("--manager-log", type=Path, default=DEFAULT_MANAGER_LOG, help="Manager log path")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Result output JSON path")
    parser.add_argument("--interval-seconds", type=float, default=5.0, help="Heartbeat interval seconds")
    parser.add_argument("--max-ticks", type=int, default=1000000000, help="Daemon max ticks")
    parser.add_argument("--start-timeout-seconds", type=float, default=8.0, help="Start action heartbeat timeout")
    parser.add_argument("--stop-timeout-seconds", type=float, default=3.0, help="Stop action wait timeout")
    parser.add_argument("--force-restart", action="store_true", help="Allow start action to restart regardless of current health")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_manage_brainstem_control_plane_ws28_017(
        repo_root=args.repo_root,
        action=args.action,
        state_file=args.state_file,
        heartbeat_file=args.heartbeat_file,
        supervisor_script=args.supervisor_script,
        spec_file=args.spec_file,
        supervisor_output=args.supervisor_output,
        manager_log=args.manager_log,
        output_file=args.output,
        interval_seconds=float(args.interval_seconds),
        max_ticks=int(args.max_ticks),
        start_timeout_seconds=float(args.start_timeout_seconds),
        stop_timeout_seconds=float(args.stop_timeout_seconds),
        force_restart=bool(args.force_restart),
    )
    print(json.dumps(report, ensure_ascii=False))
    if args.strict and not bool(report.get("passed")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
