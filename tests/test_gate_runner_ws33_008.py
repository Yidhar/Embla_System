"""WS33-008: GateRunner release gate evaluation tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import yaml

from core.release.gate_runner import GateCheckResult, GateEvaluation, GateRunner


# ── Helpers ────────────────────────────────────────────────────


def _write_policy(tmp_path: Path, policy: Dict[str, Any]) -> Path:
    policy_file = tmp_path / "gate_policy.yaml"
    policy_file.write_text(yaml.dump(policy, default_flow_style=False), encoding="utf-8")
    return policy_file


def _always_pass(name: str = "stub") -> GateCheckResult:
    return GateCheckResult(check_name=name, passed=True, output="ok")


def _always_fail(name: str = "stub") -> GateCheckResult:
    return GateCheckResult(check_name=name, passed=False, error="forced failure")


class _EventCapture:
    """Minimal event emitter that captures events for assertion."""

    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    def emit(self, event_type: str, payload: Dict[str, Any], **kwargs: Any) -> None:
        self.events.append({"event_type": event_type, "payload": payload, **kwargs})


# ── read_only gate ─────────────────────────────────────────────


class TestReadOnlyGate:

    def test_auto_allow_passes_immediately(self, tmp_path: Path) -> None:
        policy_file = _write_policy(tmp_path, {
            "gates": {
                "read_only": {"auto_allow": True},
            }
        })
        runner = GateRunner(policy_path=policy_file)
        result = runner.evaluate_gate("read_only")
        assert result.passed is True
        assert result.reason == "auto_allow"
        assert result.checks == []

    def test_auto_allow_with_real_policy(self) -> None:
        """Use the actual policy/gate_policy.yaml to verify read_only is auto_allow."""
        real_policy = Path("policy/gate_policy.yaml")
        if not real_policy.exists():
            return  # skip if running outside project root
        runner = GateRunner(policy_path=real_policy)
        result = runner.evaluate_gate("read_only")
        assert result.passed is True
        assert result.reason == "auto_allow"


# ── write_repo gate ────────────────────────────────────────────


class TestWriteRepoGate:

    def test_runs_all_required_checks(self, tmp_path: Path) -> None:
        policy_file = _write_policy(tmp_path, {
            "gates": {
                "write_repo": {
                    "required_checks": ["unit_test", "lint", "static_scan"],
                },
            }
        })
        runners = {
            "unit_test": lambda: _always_pass("unit_test"),
            "lint": lambda: _always_pass("lint"),
            "static_scan": lambda: _always_pass("static_scan"),
        }
        runner = GateRunner(policy_path=policy_file, check_runners=runners)
        result = runner.evaluate_gate("write_repo")

        assert result.passed is True
        assert len(result.checks) == 3
        check_names = {c.check_name for c in result.checks}
        assert check_names == {"unit_test", "lint", "static_scan"}

    def test_fails_when_one_check_fails(self, tmp_path: Path) -> None:
        policy_file = _write_policy(tmp_path, {
            "gates": {
                "write_repo": {
                    "required_checks": ["unit_test", "lint", "static_scan"],
                },
            }
        })
        runners = {
            "unit_test": lambda: _always_pass("unit_test"),
            "lint": lambda: _always_fail("lint"),
            "static_scan": lambda: _always_pass("static_scan"),
        }
        runner = GateRunner(policy_path=policy_file, check_runners=runners)
        result = runner.evaluate_gate("write_repo")

        assert result.passed is False
        assert "lint" in result.reason
        failed = [c for c in result.checks if not c.passed]
        assert len(failed) == 1
        assert failed[0].check_name == "lint"

    def test_missing_runner_fails_check(self, tmp_path: Path) -> None:
        policy_file = _write_policy(tmp_path, {
            "gates": {
                "write_repo": {
                    "required_checks": ["unit_test", "nonexistent_check"],
                },
            }
        })
        runners = {
            "unit_test": lambda: _always_pass("unit_test"),
        }
        runner = GateRunner(policy_path=policy_file, check_runners=runners)
        result = runner.evaluate_gate("write_repo")

        assert result.passed is False
        failed = [c for c in result.checks if not c.passed]
        assert any("nonexistent_check" in c.check_name for c in failed)


# ── secrets gate ───────────────────────────────────────────────


class TestSecretsGate:

    def test_secrets_gate_adds_implicit_checks(self, tmp_path: Path) -> None:
        policy_file = _write_policy(tmp_path, {
            "gates": {
                "secrets": {
                    "require_short_lived_token": True,
                    "require_audit_log": True,
                },
            }
        })
        runners = {
            "short_lived_token": lambda: _always_pass("short_lived_token"),
            "audit_log": lambda: _always_pass("audit_log"),
        }
        runner = GateRunner(policy_path=policy_file, check_runners=runners)
        result = runner.evaluate_gate("secrets")

        assert result.passed is True
        check_names = {c.check_name for c in result.checks}
        assert "short_lived_token" in check_names
        assert "audit_log" in check_names


# ── Event emission ─────────────────────────────────────────────


class TestEventEmission:

    def test_emits_passed_event(self, tmp_path: Path) -> None:
        policy_file = _write_policy(tmp_path, {
            "gates": {
                "read_only": {"auto_allow": True},
            }
        })
        emitter = _EventCapture()
        runner = GateRunner(policy_path=policy_file, event_emitter=emitter)
        runner.evaluate_gate("read_only")

        assert len(emitter.events) == 1
        assert emitter.events[0]["event_type"] == "GateEvaluationPassed"
        assert emitter.events[0]["payload"]["gate_name"] == "read_only"
        assert emitter.events[0]["payload"]["passed"] is True

    def test_emits_failed_event(self, tmp_path: Path) -> None:
        policy_file = _write_policy(tmp_path, {
            "gates": {
                "write_repo": {
                    "required_checks": ["lint"],
                },
            }
        })
        emitter = _EventCapture()
        runners = {"lint": lambda: _always_fail("lint")}
        runner = GateRunner(policy_path=policy_file, event_emitter=emitter, check_runners=runners)
        runner.evaluate_gate("write_repo")

        assert len(emitter.events) == 1
        assert emitter.events[0]["event_type"] == "GateEvaluationFailed"
        assert emitter.events[0]["payload"]["passed"] is False

    def test_emits_event_for_unknown_gate(self, tmp_path: Path) -> None:
        policy_file = _write_policy(tmp_path, {"gates": {}})
        emitter = _EventCapture()
        runner = GateRunner(policy_path=policy_file, event_emitter=emitter)
        result = runner.evaluate_gate("nonexistent")

        assert result.passed is False
        assert len(emitter.events) == 1
        assert emitter.events[0]["event_type"] == "GateEvaluationFailed"


# ── GateRunner utility ─────────────────────────────────────────


class TestGateRunnerUtility:

    def test_list_gates(self, tmp_path: Path) -> None:
        policy_file = _write_policy(tmp_path, {
            "gates": {
                "read_only": {"auto_allow": True},
                "write_repo": {"required_checks": ["lint"]},
                "deploy": {"required_checks": ["integration_test"]},
            }
        })
        runner = GateRunner(policy_path=policy_file)
        gates = runner.list_gates()
        assert gates == ["deploy", "read_only", "write_repo"]

    def test_missing_policy_file(self, tmp_path: Path) -> None:
        policy_file = tmp_path / "nonexistent.yaml"
        runner = GateRunner(policy_path=policy_file)
        assert runner.list_gates() == []

    def test_evaluate_gate_not_found(self, tmp_path: Path) -> None:
        policy_file = _write_policy(tmp_path, {"gates": {"read_only": {"auto_allow": True}}})
        runner = GateRunner(policy_path=policy_file)
        result = runner.evaluate_gate("unknown_gate")
        assert result.passed is False
        assert "not found" in result.reason

    def test_dataclass_to_dict(self) -> None:
        check = GateCheckResult(check_name="lint", passed=True, output="clean")
        d = check.to_dict()
        assert d == {"check_name": "lint", "passed": True, "output": "clean", "error": ""}

        evaluation = GateEvaluation(gate_name="test", passed=True, checks=[check], reason="ok")
        d2 = evaluation.to_dict()
        assert d2["gate_name"] == "test"
        assert len(d2["checks"]) == 1
