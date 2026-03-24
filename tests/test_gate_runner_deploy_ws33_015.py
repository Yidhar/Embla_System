"""WS33-015: Deploy gate check runners — integration_test, perf_smoke, canary_plan."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import yaml

from core.release.gate_runner import GateCheckResult, GateRunner


# ── Helpers ────────────────────────────────────────────────────


def _write_policy(tmp_path: Path, policy: Dict[str, Any]) -> Path:
    policy_file = tmp_path / "gate_policy.yaml"
    policy_file.write_text(yaml.dump(policy, default_flow_style=False), encoding="utf-8")
    return policy_file


_DEPLOY_POLICY: Dict[str, Any] = {
    "gates": {
        "deploy": {
            "required_checks": ["integration_test", "perf_smoke", "canary_plan"],
            "canary_window_min": 15,
            "min_sample_count": 200,
            "burn_rate_windows": ["5m", "30m"],
            "healthy_windows_for_promotion": 3,
            "bad_windows_for_rollback": 2,
        },
    }
}


# ── integration_test runner ───────────────────────────────────


class TestIntegrationTestRunner:

    def test_passes_when_subprocess_exits_zero(self, tmp_path: Path) -> None:
        policy_file = _write_policy(tmp_path, _DEPLOY_POLICY)
        runner = GateRunner(policy_path=policy_file, project_root=tmp_path)

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="SELF_CHECK_SMOKE_OK\n", stderr=""
        )
        with patch("core.release.gate_runner.subprocess.run", return_value=mock_result) as mock_run:
            result = runner._check_integration_test()

        assert result.passed is True
        assert result.check_name == "integration_test"
        assert "SELF_CHECK_SMOKE_OK" in result.output
        mock_run.assert_called_once()

    def test_fails_when_subprocess_exits_nonzero(self, tmp_path: Path) -> None:
        policy_file = _write_policy(tmp_path, _DEPLOY_POLICY)
        runner = GateRunner(policy_path=policy_file, project_root=tmp_path)

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="ImportError: no module\n"
        )
        with patch("core.release.gate_runner.subprocess.run", return_value=mock_result):
            result = runner._check_integration_test()

        assert result.passed is False
        assert result.check_name == "integration_test"
        assert "ImportError" in result.error

    def test_handles_exception(self, tmp_path: Path) -> None:
        policy_file = _write_policy(tmp_path, _DEPLOY_POLICY)
        runner = GateRunner(policy_path=policy_file, project_root=tmp_path)

        with patch("core.release.gate_runner.subprocess.run", side_effect=OSError("boom")):
            result = runner._check_integration_test()

        assert result.passed is False
        assert "boom" in result.error


# ── perf_smoke runner ─────────────────────────────────────────


class TestPerfSmokeRunner:

    def test_perf_smoke_passes(self, tmp_path: Path) -> None:
        """Run perf_smoke with mocked EventStore and aggregation — should pass."""
        policy_file = _write_policy(tmp_path, _DEPLOY_POLICY)
        runner = GateRunner(policy_path=policy_file, project_root=tmp_path)

        mock_store = MagicMock()
        mock_store.topic_db_path = tmp_path / "events.db"

        with patch("core.event_bus.event_store.EventStore", return_value=mock_store), \
             patch("core.event_bus.runtime_views.build_runtime_posture_summary", return_value={}):
            result = runner._check_perf_smoke()

        assert result.check_name == "perf_smoke"
        assert result.passed is True
        assert "emit_50_events=" in result.output
        assert "aggregation=" in result.output

    def test_perf_smoke_fails_on_exception(self, tmp_path: Path) -> None:
        policy_file = _write_policy(tmp_path, _DEPLOY_POLICY)
        runner = GateRunner(policy_path=policy_file, project_root=tmp_path)

        with patch("core.event_bus.event_store.EventStore", side_effect=RuntimeError("db locked")):
            result = runner._check_perf_smoke()

        assert result.passed is False
        assert "db locked" in result.error


# ── canary_plan runner ────────────────────────────────────────


class TestCanaryPlanRunner:

    def test_canary_plan_promote(self, tmp_path: Path) -> None:
        policy_file = _write_policy(tmp_path, _DEPLOY_POLICY)
        runner = GateRunner(policy_path=policy_file, project_root=tmp_path)

        mock_decision = MagicMock()
        mock_decision.outcome = "promote"
        mock_decision.stats = {"healthy_streak": 3}

        mock_controller = MagicMock()
        mock_controller.evaluate_canary.return_value = mock_decision

        with patch("agents.release.controller.ReleaseController", return_value=mock_controller):
            result = runner._check_canary_plan()

        assert result.passed is True
        assert result.check_name == "canary_plan"
        assert "promote" in result.output

    def test_canary_plan_observing(self, tmp_path: Path) -> None:
        policy_file = _write_policy(tmp_path, _DEPLOY_POLICY)
        runner = GateRunner(policy_path=policy_file, project_root=tmp_path)

        mock_decision = MagicMock()
        mock_decision.outcome = "observing"
        mock_decision.stats = {"healthy_streak": 1}

        mock_controller = MagicMock()
        mock_controller.evaluate_canary.return_value = mock_decision

        with patch("agents.release.controller.ReleaseController", return_value=mock_controller):
            result = runner._check_canary_plan()

        assert result.passed is True

    def test_canary_plan_rollback_fails(self, tmp_path: Path) -> None:
        policy_file = _write_policy(tmp_path, _DEPLOY_POLICY)
        runner = GateRunner(policy_path=policy_file, project_root=tmp_path)

        mock_decision = MagicMock()
        mock_decision.outcome = "rollback"
        mock_decision.stats = {"healthy_streak": 0}

        mock_controller = MagicMock()
        mock_controller.evaluate_canary.return_value = mock_decision

        with patch("agents.release.controller.ReleaseController", return_value=mock_controller):
            result = runner._check_canary_plan()

        assert result.passed is False

    def test_canary_plan_handles_exception(self, tmp_path: Path) -> None:
        policy_file = _write_policy(tmp_path, _DEPLOY_POLICY)
        runner = GateRunner(policy_path=policy_file, project_root=tmp_path)

        with patch("agents.release.controller.ReleaseController", side_effect=ValueError("bad config")):
            result = runner._check_canary_plan()

        assert result.passed is False
        assert "bad config" in result.error


# ── Deploy gate full evaluation ───────────────────────────────


class TestDeployGateEvaluation:

    def test_evaluate_deploy_runs_all_three_checks(self, tmp_path: Path) -> None:
        """evaluate_gate('deploy') should run integration_test, perf_smoke, canary_plan."""
        policy_file = _write_policy(tmp_path, _DEPLOY_POLICY)
        runner = GateRunner(policy_path=policy_file, project_root=tmp_path)

        # Patch the instance methods to return controlled results
        runner._check_runners["integration_test"] = lambda: GateCheckResult(
            check_name="integration_test", passed=True, output="OK"
        )
        runner._check_runners["perf_smoke"] = lambda: GateCheckResult(
            check_name="perf_smoke", passed=True, output="fast"
        )
        runner._check_runners["canary_plan"] = lambda: GateCheckResult(
            check_name="canary_plan", passed=True, output="promote"
        )

        evaluation = runner.evaluate_gate("deploy")

        assert evaluation.gate_name == "deploy"
        assert evaluation.passed is True
        check_names = {c.check_name for c in evaluation.checks}
        assert check_names == {"integration_test", "perf_smoke", "canary_plan"}
        assert all(c.passed for c in evaluation.checks)

    def test_evaluate_deploy_fails_when_one_check_fails(self, tmp_path: Path) -> None:
        policy_file = _write_policy(tmp_path, _DEPLOY_POLICY)
        runner = GateRunner(policy_path=policy_file, project_root=tmp_path)

        runner._check_runners["integration_test"] = lambda: GateCheckResult(
            check_name="integration_test", passed=False, error="smoke failed"
        )
        runner._check_runners["perf_smoke"] = lambda: GateCheckResult(
            check_name="perf_smoke", passed=True, output="fast"
        )
        runner._check_runners["canary_plan"] = lambda: GateCheckResult(
            check_name="canary_plan", passed=True, output="promote"
        )

        evaluation = runner.evaluate_gate("deploy")

        assert evaluation.passed is False
        assert "integration_test" in evaluation.reason

    def test_runners_registered_in_check_runners(self, tmp_path: Path) -> None:
        """The 3 deploy runners should be auto-registered when no custom runners provided."""
        policy_file = _write_policy(tmp_path, _DEPLOY_POLICY)
        runner = GateRunner(policy_path=policy_file, project_root=tmp_path)

        assert "integration_test" in runner._check_runners
        assert "perf_smoke" in runner._check_runners
        assert "canary_plan" in runner._check_runners
        # Original runners should also be present
        assert "unit_test" in runner._check_runners
        assert "lint" in runner._check_runners
