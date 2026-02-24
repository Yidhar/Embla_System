import shutil
import uuid
from pathlib import Path

from autonomous.release import CanaryThresholds, ReleaseController


def _write_policy(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
gates:
  deploy:
    canary_window_min: 15
    min_sample_count: 200
    healthy_windows_for_promotion: 3
    bad_windows_for_rollback: 2
""".strip(),
        encoding="utf-8",
    )


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_release_controller_promote():
    case_root = _make_case_root("test_release_controller_promote")
    try:
        policy_path = case_root / "gate_policy.yaml"
        _write_policy(policy_path)
        controller = ReleaseController(
            repo_dir=str(case_root),
            policy_path=policy_path,
            thresholds=CanaryThresholds(max_error_rate=0.02, max_latency_p95_ms=1500.0, min_kpi_ratio=0.95),
        )

        decision = controller.evaluate_canary(
            observations=[
                {"window_minutes": 15, "sample_count": 220, "error_rate": 0.01, "latency_p95_ms": 1000, "kpi_ratio": 0.99},
                {"window_minutes": 15, "sample_count": 210, "error_rate": 0.01, "latency_p95_ms": 1100, "kpi_ratio": 1.0},
                {"window_minutes": 15, "sample_count": 205, "error_rate": 0.015, "latency_p95_ms": 1200, "kpi_ratio": 0.98},
            ]
        )
        assert decision.outcome == "promote"
    finally:
        _cleanup_case_root(case_root)


def test_release_controller_rollback():
    case_root = _make_case_root("test_release_controller_rollback")
    try:
        policy_path = case_root / "gate_policy.yaml"
        _write_policy(policy_path)
        controller = ReleaseController(
            repo_dir=str(case_root),
            policy_path=policy_path,
            thresholds=CanaryThresholds(max_error_rate=0.02, max_latency_p95_ms=1500.0, min_kpi_ratio=0.95),
        )

        decision = controller.evaluate_canary(
            observations=[
                {"window_minutes": 15, "sample_count": 220, "error_rate": 0.12, "latency_p95_ms": 3000, "kpi_ratio": 0.8},
                {"window_minutes": 15, "sample_count": 210, "error_rate": 0.2, "latency_p95_ms": 3500, "kpi_ratio": 0.7},
            ]
        )
        assert decision.outcome == "rollback"
    finally:
        _cleanup_case_root(case_root)


def test_release_controller_rollback_contains_threshold_snapshot():
    case_root = _make_case_root("test_release_controller_threshold_snapshot")
    try:
        policy_path = case_root / "gate_policy.yaml"
        _write_policy(policy_path)
        controller = ReleaseController(
            repo_dir=str(case_root),
            policy_path=policy_path,
            thresholds=CanaryThresholds(max_error_rate=0.02, max_latency_p95_ms=1500.0, min_kpi_ratio=0.95),
        )
        decision = controller.evaluate_canary(
            observations=[
                {"window_minutes": 15, "sample_count": 220, "error_rate": 0.08, "latency_p95_ms": 2600, "kpi_ratio": 0.8},
                {"window_minutes": 15, "sample_count": 210, "error_rate": 0.09, "latency_p95_ms": 2800, "kpi_ratio": 0.82},
            ]
        )

        assert decision.outcome == "rollback"
        assert decision.trigger_window_index == 2
        assert decision.threshold_snapshot["max_error_rate"] == 0.02
        assert decision.threshold_snapshot["max_latency_p95_ms"] == 1500.0
        assert decision.threshold_snapshot["healthy_windows_for_promotion"] == 3.0
        assert decision.threshold_snapshot["bad_windows_for_rollback"] == 2.0
        assert decision.stats["eligible_windows"] == 2
        assert decision.stats["bad_streak"] == 2
    finally:
        _cleanup_case_root(case_root)


def test_evaluate_and_execute_rollback_honors_auto_flag(monkeypatch):
    case_root = _make_case_root("test_release_controller_auto_rollback")
    try:
        policy_path = case_root / "gate_policy.yaml"
        _write_policy(policy_path)
        controller = ReleaseController(
            repo_dir=str(case_root),
            policy_path=policy_path,
            thresholds=CanaryThresholds(max_error_rate=0.02, max_latency_p95_ms=1500.0, min_kpi_ratio=0.95),
        )

        calls = {"count": 0, "command": ""}

        def _fake_execute(command: str | None):
            calls["count"] += 1
            calls["command"] = command or ""
            return True, "rollback-ok"

        monkeypatch.setattr(controller, "execute_rollback", _fake_execute)
        observations = [
            {"window_minutes": 15, "sample_count": 220, "error_rate": 0.12, "latency_p95_ms": 3000, "kpi_ratio": 0.8},
            {"window_minutes": 15, "sample_count": 210, "error_rate": 0.2, "latency_p95_ms": 3500, "kpi_ratio": 0.7},
        ]

        decision_enabled, result_enabled = controller.evaluate_and_execute_rollback(
            observations,
            auto_rollback_enabled=True,
            rollback_command="echo rollback",
        )
        assert decision_enabled.outcome == "rollback"
        assert result_enabled["attempted"] is True
        assert result_enabled["status"] == "succeeded"
        assert calls["count"] == 1
        assert calls["command"] == "echo rollback"

        decision_disabled, result_disabled = controller.evaluate_and_execute_rollback(
            observations,
            auto_rollback_enabled=False,
            rollback_command="echo rollback",
        )
        assert decision_disabled.outcome == "rollback"
        assert result_disabled["attempted"] is False
        assert result_disabled["status"] == "skipped"
        assert "disabled" in result_disabled["details"]
        assert calls["count"] == 1
    finally:
        _cleanup_case_root(case_root)
