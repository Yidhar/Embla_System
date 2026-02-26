"""WS18-008 brainstem supervisor packaging and self-recovery tests."""

from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

import system.brainstem_supervisor as brainstem_supervisor_module
from system.brainstem_supervisor import BrainstemServiceSpec, BrainstemSupervisor


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_brainstem_supervisor_auto_restart_and_state_persistence() -> None:
    case_root = _make_case_root("test_brainstem_supervisor_ws18_008")
    try:
        state_file = case_root / "brainstem_supervisor_state.json"
        launched_pids = [9001]

        def fake_launcher(_spec: BrainstemServiceSpec) -> int:
            launched_pids[0] += 1
            return launched_pids[0]

        supervisor = BrainstemSupervisor(state_file=state_file, launcher=fake_launcher, pid_alive=lambda _pid: True)
        supervisor.register_service(
            BrainstemServiceSpec(
                service_name="brainstem-core",
                command=["python", "main.py", "--headless"],
                restart_policy="on-failure",
                max_restarts=3,
                restart_backoff_seconds=1.5,
            )
        )

        start_action = supervisor.ensure_running("brainstem-core")
        assert start_action.action == "started"
        first_pid = start_action.pid

        restart_action = supervisor.mark_exit("brainstem-core", exit_code=1)
        assert restart_action.action == "restarted"
        assert restart_action.pid > first_pid
        assert restart_action.restart_count == 1

        reloaded = BrainstemSupervisor(state_file=state_file, launcher=fake_launcher, pid_alive=lambda _pid: True)
        reloaded.register_service(
            BrainstemServiceSpec(
                service_name="brainstem-core",
                command=["python", "main.py", "--headless"],
                restart_policy="on-failure",
                max_restarts=3,
            )
        )
        state = reloaded.get_state("brainstem-core")
        assert state.running is True
        assert state.restart_count == 1
        assert state.pid == restart_action.pid
    finally:
        _cleanup_case_root(case_root)


def test_brainstem_supervisor_falls_back_to_lightweight_mode_when_budget_exhausted() -> None:
    case_root = _make_case_root("test_brainstem_supervisor_ws18_008")
    try:
        state_file = case_root / "brainstem_supervisor_state.json"
        launched_pids = [100]

        def fake_launcher(_spec: BrainstemServiceSpec) -> int:
            launched_pids[0] += 1
            return launched_pids[0]

        supervisor = BrainstemSupervisor(state_file=state_file, launcher=fake_launcher, pid_alive=lambda _pid: True)
        supervisor.register_service(
            BrainstemServiceSpec(
                service_name="brainstem-daemon",
                command=["python", "main.py", "--headless"],
                restart_policy="always",
                max_restarts=1,
                lightweight_fallback_command=["python", "main.py", "--lightweight"],
            )
        )
        supervisor.ensure_running("brainstem-daemon")
        first_restart = supervisor.mark_exit("brainstem-daemon", exit_code=2)
        assert first_restart.action == "restarted"
        fallback = supervisor.mark_exit("brainstem-daemon", exit_code=2)
        assert fallback.action == "fallback"
        assert fallback.mode == "lightweight"

        state = supervisor.get_state("brainstem-daemon")
        assert state.mode == "lightweight"
        assert state.restart_count == 1
        assert state.running is False
    finally:
        _cleanup_case_root(case_root)


def test_brainstem_supervisor_renders_deployment_templates() -> None:
    case_root = _make_case_root("test_brainstem_supervisor_ws18_008")
    try:
        supervisor = BrainstemSupervisor(
            state_file=case_root / "state.json",
            launcher=lambda _spec: 1234,
            pid_alive=lambda _pid: True,
        )
        supervisor.register_service(
            BrainstemServiceSpec(
                service_name="brainstem-watchdog",
                command=["python", "main.py", "--headless"],
                working_dir="E:/Programs/NagaAgent",
                restart_policy="on-failure",
                max_restarts=5,
                restart_backoff_seconds=3,
                lightweight_fallback_command=["python", "main.py", "--lightweight"],
            )
        )

        systemd_unit = supervisor.render_systemd_unit("brainstem-watchdog")
        assert "Description=Naga Brainstem Service (brainstem-watchdog)" in systemd_unit
        assert "Restart=on-failure" in systemd_unit
        assert "Environment=NAGA_BRAINSTEM_STATE_FILE=" in systemd_unit

        windows_plan = supervisor.render_windows_recovery_template("brainstem-watchdog")
        assert windows_plan["service_name"] == "brainstem-watchdog"
        assert windows_plan["restart_policy"] == "on-failure"
        assert windows_plan["recover_actions"][2]["action"] == "run_lightweight_mode"

        manifest = supervisor.build_supervisor_manifest()
        assert manifest["service_count"] == 1
        assert manifest["services"][0]["service_name"] == "brainstem-watchdog"
    finally:
        _cleanup_case_root(case_root)


def test_brainstem_supervisor_health_snapshot_marks_missing_and_stopped_services() -> None:
    case_root = _make_case_root("test_brainstem_supervisor_ws18_008")
    try:
        supervisor = BrainstemSupervisor(
            state_file=case_root / "state.json",
            launcher=lambda _spec: 1200,
            pid_alive=lambda _pid: True,
        )
        supervisor.register_service(
            BrainstemServiceSpec(
                service_name="brainstem-runtime",
                command=["python", "main.py", "--headless"],
                restart_policy="never",
            )
        )
        supervisor.ensure_running("brainstem-runtime")
        supervisor.mark_exit("brainstem-runtime", exit_code=0)

        health = supervisor.build_health_snapshot(required_services=["brainstem-runtime", "brainstem-watchdog"])
        assert health["healthy"] is False
        assert sorted(health["unhealthy_services"]) == ["brainstem-runtime", "brainstem-watchdog"]
        rows = {row["service_name"]: row for row in health["services"]}
        assert rows["brainstem-runtime"]["status"] == "stopped"
        assert rows["brainstem-watchdog"]["status"] == "missing"
    finally:
        _cleanup_case_root(case_root)


def test_brainstem_supervisor_default_launcher_resolves_python_from_current_runtime(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _DummyProcess:
        pid = 88991

    def _fake_which(name: str) -> str | None:
        if name in {"python", "python3"}:
            return None
        return f"/usr/bin/{name}"

    def _fake_popen(command, cwd, env, stdout, stderr):  # noqa: ANN001, ARG001
        captured["command"] = list(command)
        return _DummyProcess()

    monkeypatch.setattr(brainstem_supervisor_module.shutil, "which", _fake_which)
    monkeypatch.setattr(brainstem_supervisor_module.subprocess, "Popen", _fake_popen)

    pid = BrainstemSupervisor._default_launcher(
        BrainstemServiceSpec(
            service_name="brainstem-core",
            command=["python", "main.py", "--headless"],
        )
    )
    assert pid == 88991
    assert captured["command"] == [sys.executable, "main.py", "--headless"]


def test_brainstem_supervisor_restarts_when_running_pid_disappears() -> None:
    case_root = _make_case_root("test_brainstem_supervisor_ws18_008")
    try:
        state_file = case_root / "brainstem_supervisor_state.json"
        next_pid = [12000]
        alive_pids: set[int] = set()

        def fake_launcher(_spec: BrainstemServiceSpec) -> int:
            next_pid[0] += 1
            pid = next_pid[0]
            alive_pids.add(pid)
            return pid

        supervisor = BrainstemSupervisor(
            state_file=state_file,
            launcher=fake_launcher,
            pid_alive=lambda pid: int(pid) in alive_pids,
        )
        supervisor.register_service(
            BrainstemServiceSpec(
                service_name="brainstem-core",
                command=["python", "main.py", "--headless"],
                restart_policy="on-failure",
                max_restarts=3,
            )
        )

        first = supervisor.ensure_running("brainstem-core")
        assert first.action == "started"
        alive_pids.discard(first.pid)

        restarted = supervisor.ensure_running("brainstem-core")
        assert restarted.action == "restarted"
        assert restarted.reason == "stale_pid_auto_restart"
        assert restarted.restart_count == 1
        assert restarted.pid != first.pid

        health = supervisor.build_health_snapshot(required_services=["brainstem-core"])
        row = health["services"][0]
        assert row["service_name"] == "brainstem-core"
        assert row["status"] == "running"
        assert row["healthy"] is True
    finally:
        _cleanup_case_root(case_root)


def test_brainstem_supervisor_health_snapshot_marks_dead_pid_as_unhealthy() -> None:
    case_root = _make_case_root("test_brainstem_supervisor_ws18_008")
    try:
        supervisor = BrainstemSupervisor(
            state_file=case_root / "state.json",
            launcher=lambda _spec: 55661,
            pid_alive=lambda _pid: False,
        )
        supervisor.register_service(
            BrainstemServiceSpec(
                service_name="brainstem-runtime",
                command=["python", "main.py", "--headless"],
                restart_policy="never",
            )
        )

        action = supervisor.ensure_running("brainstem-runtime")
        assert action.action == "started"

        health = supervisor.build_health_snapshot(required_services=["brainstem-runtime"])
        row = health["services"][0]
        assert row["status"] == "stopped"
        assert row["reason"] == "service_pid_not_alive"
        assert row["healthy"] is False
    finally:
        _cleanup_case_root(case_root)
