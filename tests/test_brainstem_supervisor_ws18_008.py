"""WS18-008 brainstem supervisor packaging and self-recovery tests."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

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

        supervisor = BrainstemSupervisor(state_file=state_file, launcher=fake_launcher)
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

        reloaded = BrainstemSupervisor(state_file=state_file, launcher=fake_launcher)
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

        supervisor = BrainstemSupervisor(state_file=state_file, launcher=fake_launcher)
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
        supervisor = BrainstemSupervisor(state_file=case_root / "state.json", launcher=lambda _spec: 1234)
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
