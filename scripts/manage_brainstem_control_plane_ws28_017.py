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
from typing import Any, Dict, List, Set

from core.supervisor.process_guard import ProcessGuardDaemon
from system.watchdog_daemon import WatchdogDaemon


DEFAULT_STATE_FILE = Path("scratch/runtime/brainstem_control_plane_manager_ws28_017_state.json")
DEFAULT_HEARTBEAT_FILE = Path("scratch/runtime/brainstem_control_plane_heartbeat_ws23_001.json")
DEFAULT_SUPERVISOR_SCRIPT = Path("scripts/run_brainstem_supervisor_ws23_001.py")
DEFAULT_SPEC_FILE = Path("system/brainstem_services.spec")
DEFAULT_SUPERVISOR_OUTPUT = Path("scratch/reports/brainstem_supervisor_entry_ws23_001.json")
DEFAULT_MANAGER_LOG = Path("logs/autonomous/brainstem_control_plane_manager_ws28_017.log")
DEFAULT_WATCHDOG_SCRIPT = Path("scripts/run_watchdog_daemon_ws28_025.py")
DEFAULT_WATCHDOG_STATE_FILE = Path("scratch/runtime/watchdog_daemon_state_ws28_025.json")
DEFAULT_WATCHDOG_OUTPUT = Path("scratch/reports/watchdog_daemon_ws28_025.json")
DEFAULT_WATCHDOG_LOG = Path("logs/autonomous/watchdog_daemon_ws28_025.log")
DEFAULT_PROCESS_GUARD_SCRIPT = Path("scripts/run_process_guard_daemon_ws28_028.py")
DEFAULT_PROCESS_GUARD_STATE_FILE = Path("scratch/runtime/process_guard_state_ws28_028.json")
DEFAULT_PROCESS_GUARD_OUTPUT = Path("scratch/reports/process_guard_daemon_ws28_028.json")
DEFAULT_PROCESS_GUARD_LOG = Path("logs/autonomous/process_guard_daemon_ws28_028.log")
DEFAULT_OUTPUT = Path("scratch/reports/brainstem_control_plane_manage_ws28_017.json")
REPORT_SCHEMA_VERSION = "ws28_017_brainstem_control_plane_manage.v1"

_HEARTBEAT_STALE_WARNING_SECONDS = 120.0
_HEARTBEAT_STALE_CRITICAL_SECONDS = 300.0
_WATCHDOG_STATE_STALE_WARNING_SECONDS = 120.0
_WATCHDOG_STATE_STALE_CRITICAL_SECONDS = 300.0
_PROCESS_GUARD_STATE_STALE_WARNING_SECONDS = 120.0
_PROCESS_GUARD_STATE_STALE_CRITICAL_SECONDS = 300.0


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


def _wait_for_heartbeat(
    heartbeat_file: Path,
    *,
    timeout_seconds: float,
    min_generated_ts: float | None = None,
) -> Dict[str, Any]:
    deadline = time.time() + max(0.5, float(timeout_seconds))
    last_snapshot = _build_heartbeat_status(heartbeat_file)
    while time.time() <= deadline:
        snapshot = _build_heartbeat_status(heartbeat_file)
        last_snapshot = snapshot
        if (
            snapshot["checks"]["heartbeat_exists"]
            and snapshot["checks"]["generated_at_valid"]
            and snapshot["checks"]["daemon_pid_alive"]
        ):
            if min_generated_ts is not None:
                generated_ts = _parse_iso_datetime(snapshot.get("generated_at"))
                if generated_ts is None or generated_ts < float(min_generated_ts):
                    time.sleep(0.2)
                    continue
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


def _list_pid_ppid_map() -> Dict[int, int]:
    """Best-effort snapshot of pid->ppid mapping."""
    pid_ppid: Dict[int, int] = {}
    proc_root = Path("/proc")
    if proc_root.exists():
        for entry in proc_root.iterdir():
            if not entry.is_dir() or not entry.name.isdigit():
                continue
            try:
                pid = int(entry.name)
            except ValueError:
                continue
            status_path = entry / "status"
            try:
                content = status_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            ppid = 0
            for line in content.splitlines():
                if line.startswith("PPid:"):
                    try:
                        ppid = int(line.split(":", 1)[1].strip())
                    except (ValueError, IndexError):
                        ppid = 0
                    break
            pid_ppid[pid] = ppid
        return pid_ppid

    output = ""
    ps_candidates = (
        ["ps", "-eo", "pid=", "ppid="],
        ["ps", "-o", "pid=", "-o", "ppid="],
        ["ps", "-A", "-o", "pid=", "-o", "ppid="],
    )
    for command in ps_candidates:
        try:
            output = subprocess.check_output(  # noqa: S603
                command,
                text=True,
                stderr=subprocess.DEVNULL,
            )
            break
        except Exception:
            continue
    if not output:
        return pid_ppid

    for raw in output.splitlines():
        parts = raw.strip().split()
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        pid_ppid[pid] = ppid
    return pid_ppid


def _collect_descendant_pids(seed_pids: List[int]) -> List[int]:
    """Collect descendants for a set of parent PIDs from process snapshot."""
    parents: Set[int] = {int(pid) for pid in seed_pids if int(pid) > 0}
    if not parents:
        return []

    pid_ppid = _list_pid_ppid_map()
    children_map: Dict[int, List[int]] = {}
    for pid, ppid in pid_ppid.items():
        children_map.setdefault(ppid, []).append(pid)

    queue = list(parents)
    descendants: Set[int] = set()
    while queue:
        parent = queue.pop(0)
        for child in children_map.get(parent, []):
            if child in descendants or child in parents:
                continue
            descendants.add(child)
            queue.append(child)
    return sorted(descendants)


def _list_pid_cmdline_map() -> Dict[int, str]:
    """Best-effort snapshot of pid->cmdline."""
    pid_cmdline: Dict[int, str] = {}
    proc_root = Path("/proc")
    if proc_root.exists():
        for entry in proc_root.iterdir():
            if not entry.is_dir() or not entry.name.isdigit():
                continue
            try:
                pid = int(entry.name)
            except ValueError:
                continue
            cmdline_path = entry / "cmdline"
            try:
                raw = cmdline_path.read_bytes()
            except OSError:
                continue
            if not raw:
                continue
            text = raw.replace(b"\x00", b" ").decode("utf-8", errors="ignore").strip()
            if text:
                pid_cmdline[pid] = text
        if pid_cmdline:
            return pid_cmdline

    output = ""
    ps_candidates = (
        ["ps", "-eo", "pid=", "args="],
        ["ps", "-o", "pid=", "-o", "args="],
        ["ps", "-A", "-o", "pid=", "-o", "args="],
    )
    for command in ps_candidates:
        try:
            output = subprocess.check_output(  # noqa: S603
                command,
                text=True,
                stderr=subprocess.DEVNULL,
            )
            break
        except Exception:
            continue
    if not output:
        return pid_cmdline

    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if not parts:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        cmdline = parts[1] if len(parts) > 1 else ""
        pid_cmdline[pid] = cmdline
    return pid_cmdline


def _find_repo_orphan_backend_pids(repo_root: Path) -> List[int]:
    """Fallback cleanup for orphaned backend main process outside tracked state."""
    root_text = _to_unix_path(repo_root.resolve())
    markers = (
        f"{root_text}/.venv/bin/python main.py --headless",
        f"{root_text}/.venv/bin/python main.py --lightweight",
    )
    matched: List[int] = []
    for pid, cmdline in _list_pid_cmdline_map().items():
        normalized_cmd = str(cmdline).replace("\\", "/")
        if any(marker in normalized_cmd for marker in markers):
            matched.append(int(pid))
    return sorted(set(matched))


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


def _build_watchdog_daemon_command(
    *,
    python_executable: str,
    watchdog_script: Path,
    repo_root: Path,
    state_file: Path,
    output_file: Path,
    interval_seconds: float,
    max_ticks: int,
    warn_only: bool = True,
) -> List[str]:
    command = [
        python_executable,
        _to_unix_path(watchdog_script),
        "--repo-root",
        _to_unix_path(repo_root),
        "--mode",
        "run",
        "--state-file",
        _to_unix_path(state_file),
        "--output",
        _to_unix_path(output_file),
        "--interval-seconds",
        str(max(0.0, float(interval_seconds))),
        "--max-ticks",
        str(max(1, int(max_ticks))),
    ]
    if warn_only:
        command.append("--warn-only")
    return command


def _build_process_guard_daemon_command(
    *,
    python_executable: str,
    process_guard_script: Path,
    repo_root: Path,
    state_file: Path,
    output_file: Path,
    interval_seconds: float,
    max_ticks: int,
) -> List[str]:
    return [
        python_executable,
        _to_unix_path(process_guard_script),
        "--repo-root",
        _to_unix_path(repo_root),
        "--mode",
        "run",
        "--state-file",
        _to_unix_path(state_file),
        "--output",
        _to_unix_path(output_file),
        "--interval-seconds",
        str(max(0.0, float(interval_seconds))),
        "--max-ticks",
        str(max(1, int(max_ticks))),
        "--auto-reap",
    ]


def _build_watchdog_status(
    *,
    watchdog_state_file: Path,
    launcher_pid: int = 0,
    stale_warning_seconds: float = _WATCHDOG_STATE_STALE_WARNING_SECONDS,
    stale_critical_seconds: float = _WATCHDOG_STATE_STALE_CRITICAL_SECONDS,
) -> Dict[str, Any]:
    state_summary = WatchdogDaemon.read_daemon_state(
        watchdog_state_file,
        stale_warning_seconds=float(stale_warning_seconds),
        stale_critical_seconds=float(stale_critical_seconds),
    )
    daemon_pid = int(state_summary.get("pid") or 0)
    launcher_pid_int = int(launcher_pid)
    launcher_pid_alive = _pid_alive(launcher_pid_int) if launcher_pid_int > 0 else True
    daemon_pid_alive = _pid_alive(daemon_pid) if daemon_pid > 0 else False
    reason_code = str(state_summary.get("reason_code") or "")
    checks = {
        "state_file_exists": watchdog_state_file.exists(),
        "state_status_known": str(state_summary.get("status") or "") in {"ok", "warning", "critical"},
        "state_not_stale": reason_code not in {"WATCHDOG_DAEMON_STALE_WARNING", "WATCHDOG_DAEMON_STALE_CRITICAL"},
        "launcher_pid_alive": launcher_pid_alive,
        "daemon_pid_alive": daemon_pid_alive,
    }
    reasons: List[str] = []
    if not checks["state_file_exists"]:
        reasons.append("state_file_missing")
    if checks["state_file_exists"] and not checks["state_status_known"]:
        reasons.append("state_status_unknown")
    if checks["state_file_exists"] and not checks["state_not_stale"]:
        reasons.append("state_stale")
    if launcher_pid_int > 0 and not checks["launcher_pid_alive"]:
        reasons.append("launcher_pid_not_alive")
    if checks["state_file_exists"] and not checks["daemon_pid_alive"]:
        reasons.append("daemon_pid_not_alive")
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "reasons": reasons,
        "state_file": _to_unix_path(watchdog_state_file),
        "launcher_pid": launcher_pid_int,
        "daemon_pid": daemon_pid,
        "state_summary": state_summary,
    }


def _build_process_guard_status(
    *,
    process_guard_state_file: Path,
    launcher_pid: int = 0,
    stale_warning_seconds: float = _PROCESS_GUARD_STATE_STALE_WARNING_SECONDS,
    stale_critical_seconds: float = _PROCESS_GUARD_STATE_STALE_CRITICAL_SECONDS,
) -> Dict[str, Any]:
    state_summary = ProcessGuardDaemon.read_daemon_state(
        process_guard_state_file,
        stale_warning_seconds=float(stale_warning_seconds),
        stale_critical_seconds=float(stale_critical_seconds),
    )
    daemon_pid = int(state_summary.get("pid") or 0)
    launcher_pid_int = int(launcher_pid)
    launcher_pid_alive = _pid_alive(launcher_pid_int) if launcher_pid_int > 0 else True
    daemon_pid_alive = _pid_alive(daemon_pid) if daemon_pid > 0 else False
    reason_code = str(state_summary.get("reason_code") or "")
    checks = {
        "state_file_exists": process_guard_state_file.exists(),
        "state_status_known": str(state_summary.get("status") or "") in {"ok", "warning", "critical"},
        "state_not_stale": reason_code not in {"PROCESS_GUARD_STATE_STALE_WARNING", "PROCESS_GUARD_STATE_STALE_CRITICAL"},
        "launcher_pid_alive": launcher_pid_alive,
        "daemon_pid_alive": daemon_pid_alive,
    }
    reasons: List[str] = []
    if not checks["state_file_exists"]:
        reasons.append("state_file_missing")
    if checks["state_file_exists"] and not checks["state_status_known"]:
        reasons.append("state_status_unknown")
    if checks["state_file_exists"] and not checks["state_not_stale"]:
        reasons.append("state_stale")
    if launcher_pid_int > 0 and not checks["launcher_pid_alive"]:
        reasons.append("launcher_pid_not_alive")
    if checks["state_file_exists"] and not checks["daemon_pid_alive"]:
        reasons.append("daemon_pid_not_alive")
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "reasons": reasons,
        "state_file": _to_unix_path(process_guard_state_file),
        "launcher_pid": launcher_pid_int,
        "daemon_pid": daemon_pid,
        "state_summary": state_summary,
    }


def _wait_for_watchdog_state(
    watchdog_state_file: Path,
    *,
    launcher_pid: int,
    timeout_seconds: float,
    stale_warning_seconds: float = _WATCHDOG_STATE_STALE_WARNING_SECONDS,
    stale_critical_seconds: float = _WATCHDOG_STATE_STALE_CRITICAL_SECONDS,
) -> Dict[str, Any]:
    deadline = time.time() + max(0.5, float(timeout_seconds))
    last_snapshot = _build_watchdog_status(
        watchdog_state_file=watchdog_state_file,
        launcher_pid=launcher_pid,
        stale_warning_seconds=stale_warning_seconds,
        stale_critical_seconds=stale_critical_seconds,
    )
    while time.time() <= deadline:
        snapshot = _build_watchdog_status(
            watchdog_state_file=watchdog_state_file,
            launcher_pid=launcher_pid,
            stale_warning_seconds=stale_warning_seconds,
            stale_critical_seconds=stale_critical_seconds,
        )
        last_snapshot = snapshot
        if bool(snapshot.get("passed")):
            return snapshot
        time.sleep(0.2)
    return last_snapshot


def _wait_for_process_guard_state(
    process_guard_state_file: Path,
    *,
    launcher_pid: int,
    timeout_seconds: float,
    stale_warning_seconds: float = _PROCESS_GUARD_STATE_STALE_WARNING_SECONDS,
    stale_critical_seconds: float = _PROCESS_GUARD_STATE_STALE_CRITICAL_SECONDS,
) -> Dict[str, Any]:
    deadline = time.time() + max(0.5, float(timeout_seconds))
    last_snapshot = _build_process_guard_status(
        process_guard_state_file=process_guard_state_file,
        launcher_pid=launcher_pid,
        stale_warning_seconds=stale_warning_seconds,
        stale_critical_seconds=stale_critical_seconds,
    )
    while time.time() <= deadline:
        snapshot = _build_process_guard_status(
            process_guard_state_file=process_guard_state_file,
            launcher_pid=launcher_pid,
            stale_warning_seconds=stale_warning_seconds,
            stale_critical_seconds=stale_critical_seconds,
        )
        last_snapshot = snapshot
        if bool(snapshot.get("passed")):
            return snapshot
        time.sleep(0.2)
    return last_snapshot


def start_brainstem_control_plane(
    *,
    repo_root: Path,
    state_file: Path,
    heartbeat_file: Path,
    supervisor_script: Path,
    spec_file: Path,
    supervisor_output: Path,
    manager_log: Path,
    watchdog_script: Path,
    watchdog_state_file: Path,
    watchdog_output: Path,
    watchdog_log: Path,
    process_guard_script: Path,
    process_guard_state_file: Path,
    process_guard_output: Path,
    process_guard_log: Path,
    interval_seconds: float = 5.0,
    max_ticks: int = 1000000000,
    watchdog_interval_seconds: float = 5.0,
    watchdog_max_ticks: int = 1000000000,
    watchdog_warn_only: bool = True,
    process_guard_interval_seconds: float = 5.0,
    process_guard_max_ticks: int = 1000000000,
    start_timeout_seconds: float = 8.0,
    watchdog_state_stale_warning_seconds: float = _WATCHDOG_STATE_STALE_WARNING_SECONDS,
    watchdog_state_stale_critical_seconds: float = _WATCHDOG_STATE_STALE_CRITICAL_SECONDS,
    process_guard_state_stale_warning_seconds: float = _PROCESS_GUARD_STATE_STALE_WARNING_SECONDS,
    process_guard_state_stale_critical_seconds: float = _PROCESS_GUARD_STATE_STALE_CRITICAL_SECONDS,
    force_restart: bool = False,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    state_path = _resolve_path(root, state_file)
    heartbeat_path = _resolve_path(root, heartbeat_file)
    supervisor_script_path = _resolve_path(root, supervisor_script)
    spec_file_path = _resolve_path(root, spec_file)
    supervisor_output_path = _resolve_path(root, supervisor_output)
    manager_log_path = _resolve_path(root, manager_log)
    watchdog_script_path = _resolve_path(root, watchdog_script)
    watchdog_state_path = _resolve_path(root, watchdog_state_file)
    watchdog_output_path = _resolve_path(root, watchdog_output)
    watchdog_log_path = _resolve_path(root, watchdog_log)
    process_guard_script_path = _resolve_path(root, process_guard_script)
    process_guard_state_path = _resolve_path(root, process_guard_state_file)
    process_guard_output_path = _resolve_path(root, process_guard_output)
    process_guard_log_path = _resolve_path(root, process_guard_log)
    previous_state = _read_json(state_path)
    start_requested_ts = time.time()

    if not force_restart:
        current = _build_heartbeat_status(heartbeat_path)
        watchdog_launcher_pid = int(previous_state.get("watchdog_launcher_pid") or 0)
        process_guard_launcher_pid = int(previous_state.get("process_guard_launcher_pid") or 0)
        current_watchdog = _build_watchdog_status(
            watchdog_state_file=watchdog_state_path,
            launcher_pid=watchdog_launcher_pid,
            stale_warning_seconds=watchdog_state_stale_warning_seconds,
            stale_critical_seconds=watchdog_state_stale_critical_seconds,
        )
        current_process_guard = _build_process_guard_status(
            process_guard_state_file=process_guard_state_path,
            launcher_pid=process_guard_launcher_pid,
            stale_warning_seconds=process_guard_state_stale_warning_seconds,
            stale_critical_seconds=process_guard_state_stale_critical_seconds,
        )
        if bool(current.get("passed")) and bool(current_watchdog.get("passed")) and bool(current_process_guard.get("passed")):
            checks = {
                "already_running": True,
                "spawned": False,
                "heartbeat_detected": True,
                "watchdog_gate": True,
                "watchdog_state_exists": bool(current_watchdog.get("checks", {}).get("state_file_exists")),
                "process_guard_gate": True,
                "process_guard_state_exists": bool(current_process_guard.get("checks", {}).get("state_file_exists")),
            }
            report = {
                "task_id": "NGA-WS28-017",
                "scenario": "brainstem_control_plane_manage",
                "generated_at": _utc_iso_now(),
                "action": "start",
                "passed": True,
                "status": "already_running",
                "repo_root": _to_unix_path(root),
                "checks": checks,
                "heartbeat": current,
                "watchdog": current_watchdog,
                "process_guard": current_process_guard,
                "state_file": _to_unix_path(state_path),
                "heartbeat_file": _to_unix_path(heartbeat_path),
                "watchdog_state_file": _to_unix_path(watchdog_state_path),
                "process_guard_state_file": _to_unix_path(process_guard_state_path),
                "watchdog_output": _to_unix_path(watchdog_output_path),
                "watchdog_log": _to_unix_path(watchdog_log_path),
                "process_guard_output": _to_unix_path(process_guard_output_path),
                "process_guard_log": _to_unix_path(process_guard_log_path),
            }
            persisted_state = dict(previous_state)
            persisted_state.update(
                {
                    "task_id": "NGA-WS28-017",
                    "scenario": "brainstem_control_plane_manage",
                    "generated_at": _utc_iso_now(),
                    "status": "already_running",
                    "action": "start",
                    "repo_root": _to_unix_path(root),
                    "heartbeat_file": _to_unix_path(heartbeat_path),
                    "watchdog_state_file": _to_unix_path(watchdog_state_path),
                    "process_guard_state_file": _to_unix_path(process_guard_state_path),
                    "watchdog_output": _to_unix_path(watchdog_output_path),
                    "watchdog_log": _to_unix_path(watchdog_log_path),
                    "process_guard_output": _to_unix_path(process_guard_output_path),
                    "process_guard_log": _to_unix_path(process_guard_log_path),
                    "checks": checks,
                }
            )
            _write_json(state_path, persisted_state)
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
    watchdog_command = _build_watchdog_daemon_command(
        python_executable=sys.executable,
        watchdog_script=watchdog_script_path,
        repo_root=root,
        state_file=watchdog_state_path,
        output_file=watchdog_output_path,
        interval_seconds=watchdog_interval_seconds,
        max_ticks=watchdog_max_ticks,
        warn_only=watchdog_warn_only,
    )
    watchdog_log_path.parent.mkdir(parents=True, exist_ok=True)
    with watchdog_log_path.open("a", encoding="utf-8") as watchdog_log_handle:
        watchdog_process = subprocess.Popen(  # noqa: S603
            watchdog_command,
            cwd=str(root),
            stdout=watchdog_log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    process_guard_command = _build_process_guard_daemon_command(
        python_executable=sys.executable,
        process_guard_script=process_guard_script_path,
        repo_root=root,
        state_file=process_guard_state_path,
        output_file=process_guard_output_path,
        interval_seconds=process_guard_interval_seconds,
        max_ticks=process_guard_max_ticks,
    )
    process_guard_log_path.parent.mkdir(parents=True, exist_ok=True)
    with process_guard_log_path.open("a", encoding="utf-8") as process_guard_log_handle:
        process_guard_process = subprocess.Popen(  # noqa: S603
            process_guard_command,
            cwd=str(root),
            stdout=process_guard_log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    heartbeat_snapshot = _wait_for_heartbeat(
        heartbeat_path,
        timeout_seconds=start_timeout_seconds,
        min_generated_ts=start_requested_ts,
    )
    watchdog_snapshot = _wait_for_watchdog_state(
        watchdog_state_path,
        launcher_pid=int(watchdog_process.pid),
        timeout_seconds=start_timeout_seconds,
        stale_warning_seconds=watchdog_state_stale_warning_seconds,
        stale_critical_seconds=watchdog_state_stale_critical_seconds,
    )
    process_guard_snapshot = _wait_for_process_guard_state(
        process_guard_state_path,
        launcher_pid=int(process_guard_process.pid),
        timeout_seconds=start_timeout_seconds,
        stale_warning_seconds=process_guard_state_stale_warning_seconds,
        stale_critical_seconds=process_guard_state_stale_critical_seconds,
    )
    checks = {
        "spawned": int(process.pid) > 0,
        "heartbeat_detected": bool(heartbeat_snapshot.get("checks", {}).get("heartbeat_exists")),
        "heartbeat_generated_at_valid": bool(heartbeat_snapshot.get("checks", {}).get("generated_at_valid")),
        "daemon_pid_alive": bool(heartbeat_snapshot.get("checks", {}).get("daemon_pid_alive")),
        "watchdog_spawned": int(watchdog_process.pid) > 0,
        "watchdog_state_detected": bool(watchdog_snapshot.get("checks", {}).get("state_file_exists")),
        "watchdog_state_known": bool(watchdog_snapshot.get("checks", {}).get("state_status_known")),
        "watchdog_daemon_pid_alive": bool(watchdog_snapshot.get("checks", {}).get("daemon_pid_alive")),
        "watchdog_launcher_pid_alive": bool(watchdog_snapshot.get("checks", {}).get("launcher_pid_alive")),
        "watchdog_gate": bool(watchdog_snapshot.get("passed")),
        "process_guard_spawned": int(process_guard_process.pid) > 0,
        "process_guard_state_detected": bool(process_guard_snapshot.get("checks", {}).get("state_file_exists")),
        "process_guard_state_known": bool(process_guard_snapshot.get("checks", {}).get("state_status_known")),
        "process_guard_daemon_pid_alive": bool(process_guard_snapshot.get("checks", {}).get("daemon_pid_alive")),
        "process_guard_launcher_pid_alive": bool(process_guard_snapshot.get("checks", {}).get("launcher_pid_alive")),
        "process_guard_gate": bool(process_guard_snapshot.get("passed")),
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
        "watchdog_launcher_pid": int(watchdog_process.pid),
        "watchdog_daemon_pid": int(watchdog_snapshot.get("daemon_pid") or 0),
        "watchdog_command": watchdog_command,
        "process_guard_launcher_pid": int(process_guard_process.pid),
        "process_guard_daemon_pid": int(process_guard_snapshot.get("daemon_pid") or 0),
        "process_guard_command": process_guard_command,
        "state_file": _to_unix_path(state_path),
        "heartbeat_file": _to_unix_path(heartbeat_path),
        "watchdog_state_file": _to_unix_path(watchdog_state_path),
        "process_guard_state_file": _to_unix_path(process_guard_state_path),
        "supervisor_output": _to_unix_path(supervisor_output_path),
        "watchdog_output": _to_unix_path(watchdog_output_path),
        "process_guard_output": _to_unix_path(process_guard_output_path),
        "manager_log": _to_unix_path(manager_log_path),
        "watchdog_log": _to_unix_path(watchdog_log_path),
        "process_guard_log": _to_unix_path(process_guard_log_path),
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
        "watchdog": watchdog_snapshot,
        "process_guard": process_guard_snapshot,
        "state_file": _to_unix_path(state_path),
        "heartbeat_file": _to_unix_path(heartbeat_path),
        "watchdog_state_file": _to_unix_path(watchdog_state_path),
        "process_guard_state_file": _to_unix_path(process_guard_state_path),
        "manager_log": _to_unix_path(manager_log_path),
        "watchdog_log": _to_unix_path(watchdog_log_path),
        "process_guard_log": _to_unix_path(process_guard_log_path),
        "launcher_pid": int(process.pid),
        "heartbeat_pid": int(heartbeat_snapshot.get("pid") or 0),
        "watchdog_launcher_pid": int(watchdog_process.pid),
        "watchdog_daemon_pid": int(watchdog_snapshot.get("daemon_pid") or 0),
        "process_guard_launcher_pid": int(process_guard_process.pid),
        "process_guard_daemon_pid": int(process_guard_snapshot.get("daemon_pid") or 0),
        "command": command,
        "watchdog_command": watchdog_command,
        "process_guard_command": process_guard_command,
        "watchdog_output": _to_unix_path(watchdog_output_path),
        "process_guard_output": _to_unix_path(process_guard_output_path),
    }


def status_brainstem_control_plane(
    *,
    repo_root: Path,
    state_file: Path,
    heartbeat_file: Path,
    watchdog_state_file: Path,
    process_guard_state_file: Path,
    watchdog_state_stale_warning_seconds: float = _WATCHDOG_STATE_STALE_WARNING_SECONDS,
    watchdog_state_stale_critical_seconds: float = _WATCHDOG_STATE_STALE_CRITICAL_SECONDS,
    process_guard_state_stale_warning_seconds: float = _PROCESS_GUARD_STATE_STALE_WARNING_SECONDS,
    process_guard_state_stale_critical_seconds: float = _PROCESS_GUARD_STATE_STALE_CRITICAL_SECONDS,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    state_path = _resolve_path(root, state_file)
    heartbeat_path = _resolve_path(root, heartbeat_file)
    watchdog_state_path = _resolve_path(root, watchdog_state_file)
    process_guard_state_path = _resolve_path(root, process_guard_state_file)
    manager_state = _read_json(state_path)
    heartbeat = _build_heartbeat_status(heartbeat_path)
    launcher_pid = int(manager_state.get("launcher_pid") or 0)
    launcher_pid_alive = _pid_alive(launcher_pid) if launcher_pid > 0 else True
    watchdog_launcher_pid = int(manager_state.get("watchdog_launcher_pid") or 0)
    watchdog = _build_watchdog_status(
        watchdog_state_file=watchdog_state_path,
        launcher_pid=watchdog_launcher_pid,
        stale_warning_seconds=watchdog_state_stale_warning_seconds,
        stale_critical_seconds=watchdog_state_stale_critical_seconds,
    )
    process_guard_launcher_pid = int(manager_state.get("process_guard_launcher_pid") or 0)
    process_guard = _build_process_guard_status(
        process_guard_state_file=process_guard_state_path,
        launcher_pid=process_guard_launcher_pid,
        stale_warning_seconds=process_guard_state_stale_warning_seconds,
        stale_critical_seconds=process_guard_state_stale_critical_seconds,
    )
    checks = {
        "manager_state_exists": state_path.exists(),
        "heartbeat_gate": bool(heartbeat.get("passed")),
        "launcher_pid_alive": launcher_pid_alive,
        "watchdog_gate": bool(watchdog.get("passed")),
        "watchdog_launcher_pid_alive": bool(watchdog.get("checks", {}).get("launcher_pid_alive")),
        "watchdog_daemon_pid_alive": bool(watchdog.get("checks", {}).get("daemon_pid_alive")),
        "watchdog_state_exists": bool(watchdog.get("checks", {}).get("state_file_exists")),
        "process_guard_gate": bool(process_guard.get("passed")),
        "process_guard_launcher_pid_alive": bool(process_guard.get("checks", {}).get("launcher_pid_alive")),
        "process_guard_daemon_pid_alive": bool(process_guard.get("checks", {}).get("daemon_pid_alive")),
        "process_guard_state_exists": bool(process_guard.get("checks", {}).get("state_file_exists")),
    }
    reasons: List[str] = []
    if not checks["manager_state_exists"]:
        reasons.append("manager_state_missing")
    if not checks["heartbeat_gate"]:
        reasons.extend([f"heartbeat:{item}" for item in list(heartbeat.get("reasons") or [])])
    if launcher_pid > 0 and not checks["launcher_pid_alive"]:
        reasons.append("launcher_pid_not_alive")
    if not checks["watchdog_gate"]:
        reasons.extend([f"watchdog:{item}" for item in list(watchdog.get("reasons") or [])])
    if not checks["process_guard_gate"]:
        reasons.extend([f"process_guard:{item}" for item in list(process_guard.get("reasons") or [])])
    passed = all(checks.values())
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
        "watchdog_state_file": _to_unix_path(watchdog_state_path),
        "process_guard_state_file": _to_unix_path(process_guard_state_path),
        "manager_state": manager_state,
        "heartbeat": heartbeat,
        "watchdog": watchdog,
        "process_guard": process_guard,
    }


def stop_brainstem_control_plane(
    *,
    repo_root: Path,
    state_file: Path,
    heartbeat_file: Path,
    watchdog_state_file: Path,
    process_guard_state_file: Path,
    stop_timeout_seconds: float = 3.0,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    state_path = _resolve_path(root, state_file)
    heartbeat_path = _resolve_path(root, heartbeat_file)
    watchdog_state_path = _resolve_path(root, watchdog_state_file)
    process_guard_state_path = _resolve_path(root, process_guard_state_file)
    state_payload = _read_json(state_path)
    heartbeat_payload = _read_json(heartbeat_path)
    watchdog_payload = _read_json(watchdog_state_path)
    process_guard_payload = _read_json(process_guard_state_path)

    seed_pids = {
        int(state_payload.get("launcher_pid") or 0),
        int(heartbeat_payload.get("pid") or 0),
        int(state_payload.get("watchdog_launcher_pid") or 0),
        int(state_payload.get("watchdog_daemon_pid") or 0),
        int(watchdog_payload.get("pid") or 0),
        int(state_payload.get("process_guard_launcher_pid") or 0),
        int(state_payload.get("process_guard_daemon_pid") or 0),
        int(process_guard_payload.get("pid") or 0),
    } - {0}
    descendant_pids = set(_collect_descendant_pids(list(seed_pids)))
    orphan_backend_pids = set(_find_repo_orphan_backend_pids(root))
    target_pids = sorted(seed_pids | descendant_pids | orphan_backend_pids)
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
        "watchdog_state_file": _to_unix_path(watchdog_state_path),
        "process_guard_state_file": _to_unix_path(process_guard_state_path),
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
        "watchdog_state_file": _to_unix_path(watchdog_state_path),
        "process_guard_state_file": _to_unix_path(process_guard_state_path),
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
    watchdog_script: Path = DEFAULT_WATCHDOG_SCRIPT,
    watchdog_state_file: Path = DEFAULT_WATCHDOG_STATE_FILE,
    watchdog_output: Path = DEFAULT_WATCHDOG_OUTPUT,
    watchdog_log: Path = DEFAULT_WATCHDOG_LOG,
    process_guard_script: Path = DEFAULT_PROCESS_GUARD_SCRIPT,
    process_guard_state_file: Path = DEFAULT_PROCESS_GUARD_STATE_FILE,
    process_guard_output: Path = DEFAULT_PROCESS_GUARD_OUTPUT,
    process_guard_log: Path = DEFAULT_PROCESS_GUARD_LOG,
    output_file: Path = DEFAULT_OUTPUT,
    interval_seconds: float = 5.0,
    max_ticks: int = 1000000000,
    watchdog_interval_seconds: float = 5.0,
    watchdog_max_ticks: int = 1000000000,
    watchdog_warn_only: bool = True,
    process_guard_interval_seconds: float = 5.0,
    process_guard_max_ticks: int = 1000000000,
    start_timeout_seconds: float = 8.0,
    watchdog_state_stale_warning_seconds: float = _WATCHDOG_STATE_STALE_WARNING_SECONDS,
    watchdog_state_stale_critical_seconds: float = _WATCHDOG_STATE_STALE_CRITICAL_SECONDS,
    process_guard_state_stale_warning_seconds: float = _PROCESS_GUARD_STATE_STALE_WARNING_SECONDS,
    process_guard_state_stale_critical_seconds: float = _PROCESS_GUARD_STATE_STALE_CRITICAL_SECONDS,
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
            watchdog_script=watchdog_script,
            watchdog_state_file=watchdog_state_file,
            watchdog_output=watchdog_output,
            watchdog_log=watchdog_log,
            process_guard_script=process_guard_script,
            process_guard_state_file=process_guard_state_file,
            process_guard_output=process_guard_output,
            process_guard_log=process_guard_log,
            interval_seconds=interval_seconds,
            max_ticks=max_ticks,
            watchdog_interval_seconds=watchdog_interval_seconds,
            watchdog_max_ticks=watchdog_max_ticks,
            watchdog_warn_only=watchdog_warn_only,
            process_guard_interval_seconds=process_guard_interval_seconds,
            process_guard_max_ticks=process_guard_max_ticks,
            start_timeout_seconds=start_timeout_seconds,
            watchdog_state_stale_warning_seconds=watchdog_state_stale_warning_seconds,
            watchdog_state_stale_critical_seconds=watchdog_state_stale_critical_seconds,
            process_guard_state_stale_warning_seconds=process_guard_state_stale_warning_seconds,
            process_guard_state_stale_critical_seconds=process_guard_state_stale_critical_seconds,
            force_restart=force_restart,
        )
    elif normalized_action == "status":
        report = status_brainstem_control_plane(
            repo_root=repo_root,
            state_file=state_file,
            heartbeat_file=heartbeat_file,
            watchdog_state_file=watchdog_state_file,
            process_guard_state_file=process_guard_state_file,
            watchdog_state_stale_warning_seconds=watchdog_state_stale_warning_seconds,
            watchdog_state_stale_critical_seconds=watchdog_state_stale_critical_seconds,
            process_guard_state_stale_warning_seconds=process_guard_state_stale_warning_seconds,
            process_guard_state_stale_critical_seconds=process_guard_state_stale_critical_seconds,
        )
    elif normalized_action == "stop":
        report = stop_brainstem_control_plane(
            repo_root=repo_root,
            state_file=state_file,
            heartbeat_file=heartbeat_file,
            watchdog_state_file=watchdog_state_file,
            process_guard_state_file=process_guard_state_file,
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
    parser.add_argument("--watchdog-script", type=Path, default=DEFAULT_WATCHDOG_SCRIPT, help="Watchdog daemon script path")
    parser.add_argument("--watchdog-state-file", type=Path, default=DEFAULT_WATCHDOG_STATE_FILE, help="Watchdog daemon state path")
    parser.add_argument("--watchdog-output", type=Path, default=DEFAULT_WATCHDOG_OUTPUT, help="Watchdog daemon run report path")
    parser.add_argument("--watchdog-log", type=Path, default=DEFAULT_WATCHDOG_LOG, help="Watchdog daemon process log path")
    parser.add_argument("--process-guard-script", type=Path, default=DEFAULT_PROCESS_GUARD_SCRIPT, help="Process guard daemon script path")
    parser.add_argument("--process-guard-state-file", type=Path, default=DEFAULT_PROCESS_GUARD_STATE_FILE, help="Process guard daemon state path")
    parser.add_argument("--process-guard-output", type=Path, default=DEFAULT_PROCESS_GUARD_OUTPUT, help="Process guard daemon run report path")
    parser.add_argument("--process-guard-log", type=Path, default=DEFAULT_PROCESS_GUARD_LOG, help="Process guard daemon process log path")
    parser.add_argument("--manager-log", type=Path, default=DEFAULT_MANAGER_LOG, help="Manager log path")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Result output JSON path")
    parser.add_argument("--interval-seconds", type=float, default=5.0, help="Heartbeat interval seconds")
    parser.add_argument("--max-ticks", type=int, default=1000000000, help="Daemon max ticks")
    parser.add_argument("--watchdog-interval-seconds", type=float, default=5.0, help="Watchdog daemon interval seconds")
    parser.add_argument("--watchdog-max-ticks", type=int, default=1000000000, help="Watchdog daemon max ticks")
    parser.add_argument("--process-guard-interval-seconds", type=float, default=5.0, help="Process guard daemon interval seconds")
    parser.add_argument("--process-guard-max-ticks", type=int, default=1000000000, help="Process guard daemon max ticks")
    parser.add_argument(
        "--watchdog-warn-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run watchdog daemon in warn-only mode",
    )
    parser.add_argument("--start-timeout-seconds", type=float, default=8.0, help="Start action heartbeat timeout")
    parser.add_argument(
        "--watchdog-state-stale-warning-seconds",
        type=float,
        default=_WATCHDOG_STATE_STALE_WARNING_SECONDS,
        help="Watchdog daemon stale warning threshold",
    )
    parser.add_argument(
        "--watchdog-state-stale-critical-seconds",
        type=float,
        default=_WATCHDOG_STATE_STALE_CRITICAL_SECONDS,
        help="Watchdog daemon stale critical threshold",
    )
    parser.add_argument(
        "--process-guard-state-stale-warning-seconds",
        type=float,
        default=_PROCESS_GUARD_STATE_STALE_WARNING_SECONDS,
        help="Process guard daemon stale warning threshold",
    )
    parser.add_argument(
        "--process-guard-state-stale-critical-seconds",
        type=float,
        default=_PROCESS_GUARD_STATE_STALE_CRITICAL_SECONDS,
        help="Process guard daemon stale critical threshold",
    )
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
        watchdog_script=args.watchdog_script,
        watchdog_state_file=args.watchdog_state_file,
        watchdog_output=args.watchdog_output,
        watchdog_log=args.watchdog_log,
        process_guard_script=args.process_guard_script,
        process_guard_state_file=args.process_guard_state_file,
        process_guard_output=args.process_guard_output,
        process_guard_log=args.process_guard_log,
        output_file=args.output,
        interval_seconds=float(args.interval_seconds),
        max_ticks=int(args.max_ticks),
        watchdog_interval_seconds=float(args.watchdog_interval_seconds),
        watchdog_max_ticks=int(args.watchdog_max_ticks),
        watchdog_warn_only=bool(args.watchdog_warn_only),
        process_guard_interval_seconds=float(args.process_guard_interval_seconds),
        process_guard_max_ticks=int(args.process_guard_max_ticks),
        start_timeout_seconds=float(args.start_timeout_seconds),
        watchdog_state_stale_warning_seconds=float(args.watchdog_state_stale_warning_seconds),
        watchdog_state_stale_critical_seconds=float(args.watchdog_state_stale_critical_seconds),
        process_guard_state_stale_warning_seconds=float(args.process_guard_state_stale_warning_seconds),
        process_guard_state_stale_critical_seconds=float(args.process_guard_state_stale_critical_seconds),
        stop_timeout_seconds=float(args.stop_timeout_seconds),
        force_restart=bool(args.force_restart),
    )
    print(json.dumps(report, ensure_ascii=False))
    if args.strict and not bool(report.get("passed")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
