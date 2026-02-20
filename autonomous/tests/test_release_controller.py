from pathlib import Path

from autonomous.release import CanaryThresholds, ReleaseController


def _write_policy(path: Path) -> None:
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


def test_release_controller_promote(tmp_path: Path):
    policy_path = tmp_path / "gate_policy.yaml"
    _write_policy(policy_path)
    controller = ReleaseController(
        repo_dir=str(tmp_path),
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


def test_release_controller_rollback(tmp_path: Path):
    policy_path = tmp_path / "gate_policy.yaml"
    _write_policy(policy_path)
    controller = ReleaseController(
        repo_dir=str(tmp_path),
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

