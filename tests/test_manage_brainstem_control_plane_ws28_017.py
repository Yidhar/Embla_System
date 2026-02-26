from __future__ import annotations

import json
import shutil
import signal
import uuid
from datetime import datetime, timezone
from pathlib import Path

import scripts.manage_brainstem_control_plane_ws28_017 as manager


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_manage_brainstem_control_plane_start_status_stop_flow(monkeypatch) -> None:
    case_root = _make_case_root("test_manage_brainstem_control_plane_ws28_017")
    try:
        repo_root = case_root / "repo"
        heartbeat = repo_root / "scratch" / "runtime" / "heartbeat.json"
        state_file = repo_root / "scratch" / "runtime" / "manager_state.json"
        output = repo_root / "scratch" / "reports" / "manager_report.json"
        manager_log = repo_root / "logs" / "autonomous" / "manager.log"
        supervisor_output = repo_root / "scratch" / "reports" / "supervisor.json"
        spec_file = repo_root / "system" / "brainstem_services.spec"
        _write_json(spec_file, {"services": []})

        alive_pids = {55001}

        class _FakeProcess:
            pid = 55001

        def _fake_popen(command, cwd, stdout, stderr, start_new_session):  # noqa: ARG001
            heartbeat_path = Path(command[command.index("--heartbeat-file") + 1])
            heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            heartbeat_path.write_text(
                json.dumps(
                    {
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "pid": 55001,
                        "tick": 1,
                        "mode": "daemon",
                        "healthy": True,
                        "service_count": 1,
                        "unhealthy_services": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return _FakeProcess()

        def _fake_kill(pid, sig):
            target = int(pid)
            if sig == 0:
                if target in alive_pids:
                    return None
                raise ProcessLookupError
            if sig in {signal.SIGTERM, signal.SIGKILL}:
                alive_pids.discard(target)
                return None
            return None

        monkeypatch.setattr(manager.subprocess, "Popen", _fake_popen)
        monkeypatch.setattr(manager.os, "kill", _fake_kill)

        start_report = manager.run_manage_brainstem_control_plane_ws28_017(
            repo_root=repo_root,
            action="start",
            heartbeat_file=heartbeat.relative_to(repo_root),
            state_file=state_file.relative_to(repo_root),
            output_file=output.relative_to(repo_root),
            manager_log=manager_log.relative_to(repo_root),
            supervisor_output=supervisor_output.relative_to(repo_root),
            spec_file=spec_file.relative_to(repo_root),
            interval_seconds=0.0,
            max_ticks=10,
            start_timeout_seconds=0.5,
            force_restart=True,
        )
        assert start_report["passed"] is True
        assert start_report["checks"]["spawned"] is True
        assert start_report["checks"]["heartbeat_detected"] is True

        status_report = manager.run_manage_brainstem_control_plane_ws28_017(
            repo_root=repo_root,
            action="status",
            heartbeat_file=heartbeat.relative_to(repo_root),
            state_file=state_file.relative_to(repo_root),
            output_file=output.relative_to(repo_root),
        )
        assert status_report["passed"] is True
        assert status_report["checks"]["heartbeat_gate"] is True
        assert status_report["checks"]["launcher_pid_alive"] is True

        stop_report = manager.run_manage_brainstem_control_plane_ws28_017(
            repo_root=repo_root,
            action="stop",
            heartbeat_file=heartbeat.relative_to(repo_root),
            state_file=state_file.relative_to(repo_root),
            output_file=output.relative_to(repo_root),
            stop_timeout_seconds=0.2,
        )
        assert stop_report["passed"] is True
        assert stop_report["checks"]["all_pids_stopped"] is True
        assert stop_report["remaining_pids"] == []
    finally:
        _cleanup_case_root(case_root)


def test_manage_brainstem_control_plane_status_fails_on_stale_heartbeat(monkeypatch) -> None:
    case_root = _make_case_root("test_manage_brainstem_control_plane_ws28_017")
    try:
        repo_root = case_root / "repo"
        heartbeat = repo_root / "scratch" / "runtime" / "heartbeat.json"
        state_file = repo_root / "scratch" / "runtime" / "manager_state.json"
        output = repo_root / "scratch" / "reports" / "manager_report.json"
        _write_json(
            heartbeat,
            {
                "generated_at": "2026-02-25T08:00:00+00:00",
                "pid": 66001,
                "tick": 2,
                "mode": "daemon",
                "healthy": True,
                "service_count": 1,
                "unhealthy_services": [],
            },
        )
        _write_json(state_file, {"launcher_pid": 66001})

        def _fake_kill(pid, sig):
            if sig == 0 and int(pid) == 66001:
                return None
            raise ProcessLookupError

        monkeypatch.setattr(manager.os, "kill", _fake_kill)
        monkeypatch.setattr(manager.time, "time", lambda: datetime(2026, 2, 26, 12, 0, tzinfo=timezone.utc).timestamp())

        report = manager.run_manage_brainstem_control_plane_ws28_017(
            repo_root=repo_root,
            action="status",
            heartbeat_file=heartbeat.relative_to(repo_root),
            state_file=state_file.relative_to(repo_root),
            output_file=output.relative_to(repo_root),
        )
        assert report["passed"] is False
        reasons = list(report["reasons"])
        assert any(item == "heartbeat:heartbeat_stale_critical" for item in reasons)
    finally:
        _cleanup_case_root(case_root)
