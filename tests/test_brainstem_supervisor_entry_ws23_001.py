from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from scripts.run_brainstem_supervisor_ws23_001 import run_brainstem_supervisor_entry
from core.supervisor import BrainstemServiceSpec, BrainstemSupervisor


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _write_spec(case_root: Path, *, restart_policy: str = "on-failure") -> Path:
    spec_file = case_root / "brainstem_services.json"
    payload = {
        "schema_version": "ws23-001-v1",
        "services": [
            {
                "service_name": "brainstem-core",
                "command": ["python", "main.py", "--headless"],
                "working_dir": ".",
                "restart_policy": restart_policy,
                "max_restarts": 2,
                "restart_backoff_seconds": 1.0,
            }
        ],
    }
    spec_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return spec_file


def test_brainstem_supervisor_entry_ensure_mode_with_dry_run_reports_healthy() -> None:
    case_root = _make_case_root("test_brainstem_supervisor_entry_ws23_001")
    try:
        spec_file = _write_spec(case_root)
        report = run_brainstem_supervisor_entry(
            state_file=case_root / "state.json",
            spec_file=spec_file,
            mode="ensure",
            dry_run=True,
            output_file=case_root / "report.json",
        )
        assert report["passed"] is True
        assert report["action_count"] == 1
        assert report["actions"][0]["action"] == "started"
        assert report["health"]["healthy"] is True
        assert report["health"]["services"][0]["status"] == "running"
        assert (case_root / "report.json").exists()
    finally:
        _cleanup_case_root(case_root)


def test_brainstem_supervisor_entry_health_mode_detects_stopped_service() -> None:
    case_root = _make_case_root("test_brainstem_supervisor_entry_ws23_001")
    try:
        spec_file = _write_spec(case_root, restart_policy="never")
        state_file = case_root / "state.json"
        supervisor = BrainstemSupervisor(state_file=state_file, launcher=lambda _spec: 43210, pid_alive=lambda _pid: True)
        supervisor.register_service(
            BrainstemServiceSpec(
                service_name="brainstem-core",
                command=["python", "main.py", "--headless"],
                restart_policy="never",
            )
        )
        supervisor.ensure_running("brainstem-core")
        supervisor.mark_exit("brainstem-core", exit_code=0)

        report = run_brainstem_supervisor_entry(
            state_file=state_file,
            spec_file=spec_file,
            mode="health",
            dry_run=False,
            output_file=case_root / "health.json",
        )
        assert report["passed"] is False
        assert report["action_count"] == 0
        assert report["health"]["healthy"] is False
        assert "brainstem-core" in report["health"]["unhealthy_services"]
        assert report["health"]["services"][0]["status"] == "stopped"
    finally:
        _cleanup_case_root(case_root)


def test_brainstem_supervisor_entry_daemon_mode_writes_heartbeat_snapshot() -> None:
    case_root = _make_case_root("test_brainstem_supervisor_entry_ws23_001")
    try:
        spec_file = _write_spec(case_root)
        heartbeat_file = case_root / "heartbeat.json"
        report = run_brainstem_supervisor_entry(
            state_file=case_root / "state.json",
            spec_file=spec_file,
            mode="daemon",
            dry_run=True,
            heartbeat_file=heartbeat_file,
            interval_seconds=0.0,
            max_ticks=2,
            output_file=case_root / "daemon.json",
        )
        assert report["passed"] is True
        assert report["mode"] == "daemon"
        assert report["daemon"]["tick_count"] == 2
        assert report["health"]["healthy"] is True
        assert heartbeat_file.exists()
        heartbeat = json.loads(heartbeat_file.read_text(encoding="utf-8"))
        assert heartbeat["mode"] == "daemon"
        assert heartbeat["tick"] == 2
        assert heartbeat["healthy"] is True
        assert int(heartbeat["pid"]) > 0
    finally:
        _cleanup_case_root(case_root)
