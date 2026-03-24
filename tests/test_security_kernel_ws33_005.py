"""Security kernel tests: KillSwitch engage/is_engaged, NativeToolExecutor killswitch guard, ApprovalGate high-risk scope blocking."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.security.killswitch import KillSwitchController


# ── KillSwitch engage / is_engaged ──────────────────────────────


class TestKillSwitchEngage:

    def test_engage_sets_active_true(self, tmp_path: Path) -> None:
        state_file = tmp_path / "ks.json"
        ctrl = KillSwitchController(state_file=state_file)

        result = ctrl.engage(reason="test meltdown", source="unit_test")

        assert result["active"] is True
        assert result["execution_state"] == "engaged"
        assert result["engaged_reason"] == "test meltdown"
        assert result["engaged_source"] == "unit_test"

    def test_engage_persists_to_disk(self, tmp_path: Path) -> None:
        state_file = tmp_path / "ks.json"
        ctrl = KillSwitchController(state_file=state_file)
        ctrl.engage(reason="persist test")

        raw = json.loads(state_file.read_text(encoding="utf-8"))
        assert raw["active"] is True
        assert raw["execution_state"] == "engaged"

    def test_is_engaged_returns_true_after_engage(self, tmp_path: Path) -> None:
        state_file = tmp_path / "ks.json"
        ctrl = KillSwitchController(state_file=state_file)

        assert ctrl.is_engaged() is False
        ctrl.engage(reason="arm it")
        assert ctrl.is_engaged() is True

    def test_is_engaged_returns_false_after_release(self, tmp_path: Path) -> None:
        state_file = tmp_path / "ks.json"
        ctrl = KillSwitchController(state_file=state_file)

        ctrl.engage(reason="arm then release")
        assert ctrl.is_engaged() is True

        ctrl.release(requested_by="unit_test")
        assert ctrl.is_engaged() is False

    def test_engage_default_source(self, tmp_path: Path) -> None:
        state_file = tmp_path / "ks.json"
        ctrl = KillSwitchController(state_file=state_file)

        result = ctrl.engage()
        assert result["engaged_source"] == "system"
        assert result["engaged_reason"] == ""


# ── NativeToolExecutor killswitch guard ─────────────────────────


class TestNativeToolExecutorKillswitchGuard:

    def test_execute_returns_error_when_killswitch_engaged(self, tmp_path: Path) -> None:
        """When killswitch is engaged, execute() must short-circuit with error."""
        state_file = tmp_path / "ks.json"
        ks_ctrl = KillSwitchController(state_file=state_file)
        ks_ctrl.engage(reason="test block")

        # Patch heavy dependencies to isolate the guard check
        with (
            patch("apiserver.native_tools.NativeExecutor") as MockExecutor,
            patch("apiserver.native_tools.get_policy_firewall") as mock_firewall_fn,
            patch("apiserver.native_tools.ExecutionBackendRegistry"),
            patch("apiserver.native_tools.get_artifact_store"),
        ):
            mock_executor_instance = MagicMock()
            mock_executor_instance.base_dir = tmp_path
            MockExecutor.return_value = mock_executor_instance

            mock_firewall = MagicMock()
            mock_decision = MagicMock()
            mock_decision.allowed = True
            mock_decision.audit_id = ""
            mock_firewall.validate_native_call.return_value = mock_decision
            mock_firewall_fn.return_value = mock_firewall

            from apiserver.native_tools import NativeToolExecutor

            executor = NativeToolExecutor()
            executor.killswitch_controller = ks_ctrl

            # Mock _build_effective_call to return a simple tuple
            mock_backend = MagicMock()
            mock_backend.name = "native"
            mock_context = MagicMock()
            mock_context.workspace_host_root = None
            executor._build_effective_call = MagicMock(
                return_value=({"tool_name": "read_file", "path": "/tmp/test.txt"}, mock_context, mock_backend)
            )

            result = asyncio.run(
                executor.execute({"tool_name": "read_file", "path": "/tmp/test.txt"}, "sess-1")
            )

        assert result["status"] == "error"
        assert "系统已熔断" in result["result"]


# ── ApprovalGate blocks unapproved high-risk scope ──────────────


class TestApprovalGateHighRisk:

    def test_blocks_prompt_dna_scope_without_ticket(self) -> None:
        from core.security.approval_gate import ApprovalDecision, ApprovalGate, ApprovalRequest

        gate = ApprovalGate()
        decision = gate.evaluate(
            ApprovalRequest(
                scope="prompt_dna",
                risk_level="high",
                requested_by="agent",
            )
        )
        assert decision.approved is False
        assert decision.requires_human_approval is True

    def test_allows_prompt_dna_scope_with_ticket(self) -> None:
        from core.security.approval_gate import ApprovalGate, ApprovalRequest

        gate = ApprovalGate()
        decision = gate.evaluate(
            ApprovalRequest(
                scope="prompt_dna",
                risk_level="high",
                requested_by="agent",
                approval_ticket="TICKET-001",
            )
        )
        assert decision.approved is True

    def test_blocks_core_scope_without_ticket(self) -> None:
        from core.security.approval_gate import ApprovalGate, ApprovalRequest

        gate = ApprovalGate()
        decision = gate.evaluate(
            ApprovalRequest(
                scope="core",
                risk_level="high",
                requested_by="agent",
            )
        )
        assert decision.approved is False
        assert "core" in decision.reason_text

    def test_allows_general_scope_without_ticket(self) -> None:
        from core.security.approval_gate import ApprovalGate, ApprovalRequest

        gate = ApprovalGate()
        decision = gate.evaluate(
            ApprovalRequest(
                scope="general",
                risk_level="low",
                requested_by="agent",
            )
        )
        assert decision.approved is True


# ── Scope inference ─────────────────────────────────────────────


class TestInferToolScope:

    def test_prompt_dna_path(self) -> None:
        from apiserver.native_tools import _infer_tool_scope

        scope = _infer_tool_scope("write_file", {"path": "system/prompts/dna/shell.md"})
        assert scope == "prompt_dna"

    def test_policy_path(self) -> None:
        from apiserver.native_tools import _infer_tool_scope

        scope = _infer_tool_scope("write_file", {"path": "policy/gate_policy.yaml"})
        assert scope == "policy"

    def test_tools_registry_path(self) -> None:
        from apiserver.native_tools import _infer_tool_scope

        scope = _infer_tool_scope("write_file", {"path": "workspace/tools_registry/my_tool.json"})
        assert scope == "tools_registry"

    def test_core_path(self) -> None:
        from apiserver.native_tools import _infer_tool_scope

        scope = _infer_tool_scope("write_file", {"path": "core/security/killswitch.py"})
        assert scope == "core"

    def test_general_path(self) -> None:
        from apiserver.native_tools import _infer_tool_scope

        scope = _infer_tool_scope("read_file", {"path": "README.md"})
        assert scope == "general"

    def test_killswitch_plan_tool(self) -> None:
        from apiserver.native_tools import _infer_tool_scope

        scope = _infer_tool_scope("killswitch_plan", {})
        assert scope == "security"
