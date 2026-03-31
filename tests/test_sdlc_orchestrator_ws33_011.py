"""Tests for core.sdlc.orchestrator — SDLCOrchestrator lifecycle and delegation."""
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.sdlc.orchestrator import SDLCOrchestrator, get_default_orchestrator


class TestSDLCOrchestratorDisabled:
    """When enabled=False (the default), start() should be a no-op."""

    def test_disabled_by_default(self):
        orch = SDLCOrchestrator()
        assert orch.enabled is False

    def test_start_is_noop_when_disabled(self):
        orch = SDLCOrchestrator(enabled=False)
        orch.start()
        assert orch._lease_thread is None

    def test_shutdown_is_safe_when_never_started(self):
        orch = SDLCOrchestrator()
        orch.shutdown()  # should not raise
        assert orch._lease_thread is None


class TestSDLCOrchestratorEnabled:
    """When enabled=True, start() should spawn the lease heartbeat thread."""

    def test_start_creates_lease_thread(self):
        orch = SDLCOrchestrator(enabled=True)
        # Patch the heartbeat loop to avoid actual lease I/O
        with patch.object(orch, "_lease_heartbeat_loop", side_effect=lambda: orch._stop_event.wait()):
            orch.start()
            try:
                assert orch._lease_thread is not None
                assert orch._lease_thread.is_alive()
                assert orch._lease_thread.name == "sdlc-lease"
                assert orch._lease_thread.daemon is True
            finally:
                orch.shutdown()

    def test_shutdown_stops_thread(self):
        orch = SDLCOrchestrator(enabled=True)
        with patch.object(orch, "_lease_heartbeat_loop", side_effect=lambda: orch._stop_event.wait()):
            orch.start()
            assert orch._lease_thread is not None
            orch.shutdown()
            assert orch._lease_thread is None

    def test_shutdown_sets_stop_event(self):
        orch = SDLCOrchestrator(enabled=True)
        with patch.object(orch, "_lease_heartbeat_loop", side_effect=lambda: orch._stop_event.wait()):
            orch.start()
            orch.shutdown()
            assert orch._stop_event.is_set()


class TestEvaluateGate:
    """evaluate_gate() should delegate to GateRunner."""

    def test_evaluate_gate_delegates_to_gate_runner(self, tmp_path):
        policy_file = tmp_path / "policy" / "gate_policy.yaml"
        policy_file.parent.mkdir(parents=True, exist_ok=True)
        policy_file.write_text(
            "gates:\n  read_only:\n    auto_allow: true\n",
            encoding="utf-8",
        )
        orch = SDLCOrchestrator(project_root=tmp_path, enabled=False)
        result = orch.evaluate_gate("read_only")
        assert isinstance(result, dict)
        assert result["gate_name"] == "read_only"
        assert result["passed"] is True

    def test_evaluate_gate_missing_gate(self, tmp_path):
        policy_file = tmp_path / "policy" / "gate_policy.yaml"
        policy_file.parent.mkdir(parents=True, exist_ok=True)
        policy_file.write_text("gates:\n  read_only:\n    auto_allow: true\n", encoding="utf-8")
        orch = SDLCOrchestrator(project_root=tmp_path, enabled=False)
        result = orch.evaluate_gate("nonexistent")
        assert isinstance(result, dict)
        assert result["passed"] is False


class TestGetDefaultOrchestrator:
    """get_default_orchestrator() should return a singleton."""

    def test_returns_singleton(self):
        import core.sdlc.orchestrator as mod

        # Reset module-level singleton
        mod._DEFAULT_ORCHESTRATOR = None
        try:
            a = get_default_orchestrator()
            b = get_default_orchestrator()
            assert a is b
            assert isinstance(a, SDLCOrchestrator)
        finally:
            mod._DEFAULT_ORCHESTRATOR = None

    def test_singleton_disabled_by_default(self):
        import core.sdlc.orchestrator as mod

        mod._DEFAULT_ORCHESTRATOR = None
        try:
            orch = get_default_orchestrator()
            assert orch.enabled is False
        finally:
            mod._DEFAULT_ORCHESTRATOR = None
