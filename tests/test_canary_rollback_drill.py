from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

from agents.release import CanaryThresholds
from scripts.canary_rollback_drill import parse_args, run_drill


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


def _rollback_observations() -> list[dict[str, float | int]]:
    return [
        {"window_minutes": 15, "sample_count": 220, "error_rate": 0.18, "latency_p95_ms": 3200, "kpi_ratio": 0.82},
        {"window_minutes": 15, "sample_count": 210, "error_rate": 0.21, "latency_p95_ms": 3600, "kpi_ratio": 0.76},
    ]


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_run_drill_rolls_back_in_decision_without_auto_execution() -> None:
    case_root = _make_case_root("test_canary_rollback_drill_disabled")
    try:
        policy = case_root / "policy" / "gate_policy.yaml"
        _write_policy(policy)

        report = run_drill(
            repo_dir=case_root,
            policy_path=policy,
            thresholds=CanaryThresholds(max_error_rate=0.02, max_latency_p95_ms=1500.0, min_kpi_ratio=0.95),
            observations=_rollback_observations(),
            auto_rollback_enabled=False,
            rollback_command="",
            scenario="rollback",
        )

        assert report["decision"]["outcome"] == "rollback"
        assert report["rollback_result"]["enabled"] is False
        assert report["rollback_result"]["attempted"] is False
        assert report["rollback_result"]["status"] == "skipped"
    finally:
        _cleanup_case_root(case_root)


def test_run_drill_executes_logical_rollback_when_auto_enabled() -> None:
    case_root = _make_case_root("test_canary_rollback_drill_enabled")
    try:
        policy = case_root / "policy" / "gate_policy.yaml"
        _write_policy(policy)

        report = run_drill(
            repo_dir=case_root,
            policy_path=policy,
            thresholds=CanaryThresholds(max_error_rate=0.02, max_latency_p95_ms=1500.0, min_kpi_ratio=0.95),
            observations=_rollback_observations(),
            auto_rollback_enabled=True,
            rollback_command="",
            scenario="rollback",
        )

        assert report["decision"]["outcome"] == "rollback"
        assert report["rollback_result"]["enabled"] is True
        assert report["rollback_result"]["attempted"] is True
        assert report["rollback_result"]["status"] == "succeeded"
    finally:
        _cleanup_case_root(case_root)


def test_parse_args_accepts_legacy_dry_run_flag(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["canary_rollback_drill.py", "--dry-run"])
    args = parse_args()
    assert args.dry_run is True
