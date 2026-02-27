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


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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

        alive_pids = {55001, 55002}

        class _FakeProcess:
            def __init__(self, pid: int) -> None:
                self.pid = pid

        def _fake_popen(command, cwd, stdout, stderr, start_new_session):  # noqa: ARG001
            joined = " ".join(str(item) for item in command)
            if "run_brainstem_supervisor_ws23_001.py" in joined:
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
                return _FakeProcess(55001)
            if "run_watchdog_daemon_ws28_025.py" in joined:
                state_path = Path(command[command.index("--state-file") + 1])
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text(
                    json.dumps(
                        {
                            "generated_at": datetime.now(timezone.utc).isoformat(),
                            "pid": 55002,
                            "mode": "daemon",
                            "tick": 1,
                            "status": "ok",
                            "reason_code": "WATCHDOG_DAEMON_OK",
                            "reason_text": "watchdog daemon heartbeat is healthy",
                            "snapshot": {},
                            "action": None,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                return _FakeProcess(55002)
            raise AssertionError(f"unexpected popen command: {command}")

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
        assert start_report["checks"]["watchdog_spawned"] is True
        assert start_report["checks"]["watchdog_gate"] is True
        assert start_report["report_schema_version"] == "ws28_017_brainstem_control_plane_manage.v1"
        assert start_report["output_file"].endswith("manager_report.json")
        persisted_start = _read_json(output)
        assert persisted_start["action"] == "start"
        assert persisted_start["output_file"].endswith("manager_report.json")

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
        assert status_report["checks"]["watchdog_gate"] is True
        assert status_report["checks"]["watchdog_daemon_pid_alive"] is True
        persisted_status = _read_json(output)
        assert persisted_status["action"] == "status"
        assert persisted_status["report_schema_version"] == "ws28_017_brainstem_control_plane_manage.v1"

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
        persisted_stop = _read_json(output)
        assert persisted_stop["action"] == "stop"
        assert persisted_stop["report_schema_version"] == "ws28_017_brainstem_control_plane_manage.v1"
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


def test_manage_brainstem_stop_collects_descendants_and_orphan_backend(monkeypatch) -> None:
    case_root = _make_case_root("test_manage_brainstem_control_plane_ws28_017")
    try:
        repo_root = case_root / "repo"
        heartbeat = repo_root / "scratch" / "runtime" / "heartbeat.json"
        state_file = repo_root / "scratch" / "runtime" / "manager_state.json"
        watchdog_state = repo_root / "scratch" / "runtime" / "watchdog.json"
        output = repo_root / "scratch" / "reports" / "manager_report.json"

        _write_json(state_file, {"launcher_pid": 77001, "watchdog_launcher_pid": 77002, "watchdog_daemon_pid": 77003})
        _write_json(heartbeat, {"pid": 77001, "generated_at": datetime.now(timezone.utc).isoformat()})
        _write_json(watchdog_state, {"pid": 77003})

        alive_pids = {77001, 77002, 77003, 77011, 77012}

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

        monkeypatch.setattr(manager.os, "kill", _fake_kill)
        monkeypatch.setattr(manager, "_collect_descendant_pids", lambda seed: [77011])
        monkeypatch.setattr(manager, "_find_repo_orphan_backend_pids", lambda root: [77012])

        report = manager.run_manage_brainstem_control_plane_ws28_017(
            repo_root=repo_root,
            action="stop",
            heartbeat_file=heartbeat.relative_to(repo_root),
            state_file=state_file.relative_to(repo_root),
            watchdog_state_file=watchdog_state.relative_to(repo_root),
            output_file=output.relative_to(repo_root),
            stop_timeout_seconds=0.2,
        )
        assert report["passed"] is True
        assert report["checks"]["target_pid_count"] == 5
        assert set(int(pid) for pid in report["termination_results"].keys()) == {77001, 77002, 77003, 77011, 77012}
    finally:
        _cleanup_case_root(case_root)
