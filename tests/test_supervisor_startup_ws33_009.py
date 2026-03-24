"""WS33-009: BrainstemSupervisor + ProcessGuardDaemon startup integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from core.supervisor.brainstem_supervisor import BrainstemServiceSpec, BrainstemSupervisor
from core.supervisor.process_guard import ProcessGuardDaemon, ProcessGuardThresholds


# ── BrainstemSupervisor Tests ──────────────────────────────────


class TestBrainstemSupervisorInstantiation:

    def test_instantiate_with_state_file(self, tmp_path: Path) -> None:
        state_file = tmp_path / "brainstem_state.json"
        supervisor = BrainstemSupervisor(state_file=state_file)
        assert supervisor.state_file == state_file
        assert state_file.parent.exists()

    def test_register_service(self, tmp_path: Path) -> None:
        state_file = tmp_path / "brainstem_state.json"
        supervisor = BrainstemSupervisor(state_file=state_file)
        spec = BrainstemServiceSpec(
            service_name="api_server",
            command=["python", "-m", "uvicorn", "apiserver.api_server:app"],
            working_dir=str(tmp_path),
            restart_policy="on-failure",
            max_restarts=3,
        )
        supervisor.register_service(spec)

        state = supervisor.get_state("api_server")
        assert state.service_name == "api_server"
        assert state_file.exists()

        persisted = json.loads(state_file.read_text(encoding="utf-8"))
        service_names = [s["service_name"] for s in persisted.get("services", [])]
        assert "api_server" in service_names

    def test_register_multiple_services(self, tmp_path: Path) -> None:
        state_file = tmp_path / "brainstem_state.json"
        supervisor = BrainstemSupervisor(state_file=state_file)
        for name in ("svc_a", "svc_b"):
            supervisor.register_service(
                BrainstemServiceSpec(service_name=name, command=["echo", name])
            )
        snapshot = supervisor.build_health_snapshot()
        assert snapshot["service_count"] == 2

    def test_get_state_unknown_service(self, tmp_path: Path) -> None:
        supervisor = BrainstemSupervisor(state_file=tmp_path / "s.json")
        state = supervisor.get_state("nonexistent")
        assert state.service_name == "nonexistent"
        assert state.running is False


# ── ProcessGuardDaemon Tests ──────────────────────────────────


class _FakeLineageRegistry:
    """Minimal stand-in for ProcessLineageRegistry."""

    def __init__(self, records=None):
        self._records = list(records or [])

    def list_running(self):
        return list(self._records)

    def reap_orphaned_running_jobs(self, *, reason="", max_epoch=None):
        return 0


class TestProcessGuardRunOnce:

    def test_run_once_no_jobs(self) -> None:
        registry = _FakeLineageRegistry()
        guard = ProcessGuardDaemon(registry=registry)
        result = guard.run_once()
        assert result["status"] == "ok"
        assert result["running_jobs"] == 0
        assert result["orphan_jobs"] == 0
        assert result["stale_jobs"] == 0

    def test_run_once_with_stale_job(self) -> None:
        import time

        stale_record = SimpleNamespace(
            job_root_id="job-stale-001",
            root_pid=999999,
            started_at=time.time() - 500,
            status="running",
        )
        registry = _FakeLineageRegistry(records=[stale_record])

        guard = ProcessGuardDaemon(
            registry=registry,
            thresholds=ProcessGuardThresholds(stale_job_seconds=60.0),
        )
        import core.supervisor.process_guard as pg_mod

        original_fn = pg_mod._pid_alive

        def _always_alive(pid):
            return True

        pg_mod._pid_alive = _always_alive
        try:
            result = guard.run_once()
            assert result["stale_jobs"] >= 1
        finally:
            pg_mod._pid_alive = original_fn

    def test_run_daemon_single_tick(self, tmp_path: Path) -> None:
        registry = _FakeLineageRegistry()
        guard = ProcessGuardDaemon(registry=registry)
        state_file = tmp_path / "pg_state.json"
        result = guard.run_daemon(
            state_file=state_file,
            interval_seconds=0.0,
            max_ticks=1,
        )
        assert result["ticks_completed"] == 1
        assert state_file.exists()
        persisted = json.loads(state_file.read_text(encoding="utf-8"))
        assert persisted["status"] == "ok"


# ── main.py integration surface check ─────────────────────────


class TestMainSupervisorWiring:

    def test_embla_runtime_has_supervisor_attributes(self) -> None:
        """Verify the EmblaRuntime class exposes supervisor instance slots."""
        from main import EmblaRuntime, StartupOptions

        runtime = EmblaRuntime(StartupOptions())
        assert hasattr(runtime, "_brainstem_supervisor")
        assert hasattr(runtime, "_process_guard")
        assert hasattr(runtime, "_process_guard_thread")
        assert runtime._brainstem_supervisor is None
        assert runtime._process_guard is None
        assert runtime._process_guard_thread is None
