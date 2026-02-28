#!/usr/bin/env python3
"""WS23-001 brainstem supervisor standalone entry and health probe."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List

from core.supervisor.brainstem_supervisor import BrainstemServiceSpec, BrainstemSupervisor


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


Launcher = Callable[[BrainstemServiceSpec], int]


def _load_specs(spec_file: Path) -> List[BrainstemServiceSpec]:
    if not spec_file.exists():
        raise FileNotFoundError(f"spec file not found: {spec_file}")
    payload = json.loads(spec_file.read_text(encoding="utf-8"))
    rows = payload.get("services")
    if not isinstance(rows, list) or not rows:
        raise ValueError("spec file must contain non-empty services list")

    specs: List[BrainstemServiceSpec] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"service row must be object: index={index}")
        command = row.get("command")
        if not isinstance(command, list):
            raise ValueError(f"service command must be list: index={index}")
        env = row.get("env")
        if env is not None and not isinstance(env, dict):
            raise ValueError(f"service env must be object: index={index}")
        spec = BrainstemServiceSpec(
            service_name=str(row.get("service_name") or "").strip(),
            command=[str(item) for item in command],
            working_dir=str(row.get("working_dir") or "").strip(),
            env={str(k): str(v) for k, v in (env or {}).items()},
            restart_policy=str(row.get("restart_policy") or "on-failure"),
            max_restarts=int(row.get("max_restarts", 5)),
            restart_backoff_seconds=float(row.get("restart_backoff_seconds", 2.0)),
            lightweight_fallback_command=[
                str(item) for item in list(row.get("lightweight_fallback_command") or []) if str(item).strip()
            ]
            or None,
        )
        specs.append(spec)
    return specs


def _build_dry_run_launcher() -> Launcher:
    counter = {"pid": 50000}

    def _launch(_spec: BrainstemServiceSpec) -> int:
        counter["pid"] += 1
        return int(counter["pid"])

    return _launch


def _write_heartbeat_snapshot(
    *,
    heartbeat_file: Path,
    tick: int,
    mode: str,
    state_file: Path,
    spec_file: Path,
    health: Dict[str, Any],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "generated_at": _utc_iso(),
        "pid": int(os.getpid()),
        "tick": int(tick),
        "mode": str(mode or "daemon"),
        "state_file": str(state_file).replace("\\", "/"),
        "spec_file": str(spec_file).replace("\\", "/"),
        "healthy": bool(health.get("healthy", False)),
        "service_count": int(health.get("service_count", 0)),
        "unhealthy_services": list(health.get("unhealthy_services") or []),
    }
    target = heartbeat_file if heartbeat_file.is_absolute() else (Path(".").resolve() / heartbeat_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["heartbeat_file"] = str(target).replace("\\", "/")
    return payload


def run_brainstem_supervisor_entry(
    *,
    state_file: Path,
    spec_file: Path,
    mode: str,
    dry_run: bool = False,
    output_file: Path | None = None,
    launcher: Launcher | None = None,
    heartbeat_file: Path | None = None,
    interval_seconds: float = 2.0,
    max_ticks: int = 1,
) -> Dict[str, Any]:
    specs = _load_specs(spec_file)
    run_launcher = launcher or (_build_dry_run_launcher() if dry_run else None)
    pid_alive_checker = (lambda _pid: True) if dry_run else None
    supervisor = BrainstemSupervisor(state_file=state_file, launcher=run_launcher, pid_alive=pid_alive_checker)
    for spec in specs:
        supervisor.register_service(spec)

    actions: List[Dict[str, Any]] = []
    normalized_mode = str(mode or "ensure").strip().lower()
    if normalized_mode == "ensure":
        for spec in specs:
            action = supervisor.ensure_running(spec.service_name)
            actions.append(action.to_dict())
    elif normalized_mode == "daemon":
        interval = max(0.0, float(interval_seconds))
        ticks = max(1, int(max_ticks))
        daemon_health: List[Dict[str, Any]] = []
        last_heartbeat: Dict[str, Any] = {}
        for tick in range(1, ticks + 1):
            for spec in specs:
                action = supervisor.ensure_running(spec.service_name)
                actions.append(action.to_dict())
            required_names = [spec.service_name for spec in specs]
            current_health = supervisor.build_health_snapshot(required_services=required_names)
            daemon_health.append(current_health)
            if heartbeat_file is not None:
                last_heartbeat = _write_heartbeat_snapshot(
                    heartbeat_file=heartbeat_file,
                    tick=tick,
                    mode="daemon",
                    state_file=state_file,
                    spec_file=spec_file,
                    health=current_health,
                )
            if tick < ticks and interval > 0.0:
                time.sleep(interval)
        final_health = daemon_health[-1]
        report: Dict[str, Any] = {
            "task_id": "NGA-WS23-001",
            "scenario": "brainstem_supervisor_entry",
            "generated_at": _utc_iso(),
            "mode": normalized_mode,
            "dry_run": bool(dry_run),
            "state_file": str(state_file).replace("\\", "/"),
            "spec_file": str(spec_file).replace("\\", "/"),
            "action_count": len(actions),
            "actions": actions,
            "health": final_health,
            "health_history": daemon_health,
            "daemon": {
                "tick_count": ticks,
                "interval_seconds": interval,
                "heartbeat_file": str(heartbeat_file).replace("\\", "/") if heartbeat_file is not None else "",
                "last_heartbeat": last_heartbeat,
            },
            "passed": all(bool(item.get("healthy", False)) for item in daemon_health),
        }
        if output_file is not None:
            target = output_file if output_file.is_absolute() else (Path(".").resolve() / output_file)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            report["output_file"] = str(target).replace("\\", "/")
        return report
    elif normalized_mode != "health":
        raise ValueError(f"unsupported mode: {mode}")

    required_names = [spec.service_name for spec in specs]
    health = supervisor.build_health_snapshot(required_services=required_names)
    report: Dict[str, Any] = {
        "task_id": "NGA-WS23-001",
        "scenario": "brainstem_supervisor_entry",
        "generated_at": _utc_iso(),
        "mode": normalized_mode,
        "dry_run": bool(dry_run),
        "state_file": str(state_file).replace("\\", "/"),
        "spec_file": str(spec_file).replace("\\", "/"),
        "action_count": len(actions),
        "actions": actions,
        "health": health,
        "passed": bool(health.get("healthy", False)),
    }

    if output_file is not None:
        target = output_file if output_file.is_absolute() else (Path(".").resolve() / output_file)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["output_file"] = str(target).replace("\\", "/")

    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS23-001 brainstem supervisor standalone entry")
    parser.add_argument(
        "--mode",
        choices=["ensure", "health", "daemon"],
        default="ensure",
        help="ensure: start required services; health: only evaluate health snapshot; daemon: periodic heartbeat run",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path("logs/autonomous/brainstem_supervisor_state.json"),
        help="Supervisor state persistence file",
    )
    parser.add_argument(
        "--spec-file",
        type=Path,
        default=Path("system/brainstem_services.spec"),
        help="Service spec file (JSON)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Use in-memory PID allocator instead of launching processes")
    parser.add_argument(
        "--heartbeat-file",
        type=Path,
        default=Path("scratch/runtime/brainstem_control_plane_heartbeat_ws23_001.json"),
        help="Heartbeat snapshot path used in daemon mode",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=2.0,
        help="Daemon tick interval in seconds",
    )
    parser.add_argument(
        "--max-ticks",
        type=int,
        default=1,
        help="Daemon max ticks (>=1); use 1 for single-shot heartbeat refresh",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scratch/reports/brainstem_supervisor_entry_ws23_001.json"),
        help="Output JSON report path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_brainstem_supervisor_entry(
        state_file=args.state_file,
        spec_file=args.spec_file,
        mode=args.mode,
        dry_run=bool(args.dry_run),
        output_file=args.output,
        heartbeat_file=args.heartbeat_file,
        interval_seconds=float(args.interval_seconds),
        max_ticks=int(args.max_ticks),
    )
    print(
        json.dumps(
            {
                "passed": report.get("passed"),
                "mode": report.get("mode"),
                "output": report.get("output_file"),
                "unhealthy_services": (report.get("health") or {}).get("unhealthy_services"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if bool(report.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
