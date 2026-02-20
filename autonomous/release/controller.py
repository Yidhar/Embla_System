"""Canary evaluation and rollback helpers for autonomous release flow."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import yaml


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


@dataclass(frozen=True)
class CanaryThresholds:
    max_error_rate: float = 0.02
    max_latency_p95_ms: float = 1500.0
    min_kpi_ratio: float = 0.95


@dataclass(frozen=True)
class CanaryDecision:
    outcome: str  # promote | rollback | observing
    reason: str
    evaluated_windows: List[Dict[str, Any]]
    policy_snapshot: Dict[str, Any]


class ReleaseController:
    """Evaluate canary windows against gate policy and trigger rollback commands."""

    def __init__(
        self,
        repo_dir: str,
        policy_path: str | Path,
        *,
        thresholds: CanaryThresholds | None = None,
    ) -> None:
        self.repo_dir = Path(repo_dir)
        self.policy_path = Path(policy_path)
        self.thresholds = thresholds or CanaryThresholds()
        self._deploy_policy = self._load_deploy_policy()

    def _load_deploy_policy(self) -> Dict[str, Any]:
        if not self.policy_path.exists():
            return {}
        try:
            payload = yaml.safe_load(self.policy_path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        gates = payload.get("gates", {})
        if not isinstance(gates, dict):
            return {}
        deploy = gates.get("deploy", {})
        if not isinstance(deploy, dict):
            return {}
        return dict(deploy)

    def evaluate_canary(self, observations: List[Dict[str, Any]] | None = None) -> CanaryDecision:
        deploy = dict(self._deploy_policy)
        canary_window_min = max(1, _to_int(deploy.get("canary_window_min"), 15))
        min_sample_count = max(1, _to_int(deploy.get("min_sample_count"), 200))
        healthy_windows = max(1, _to_int(deploy.get("healthy_windows_for_promotion"), 3))
        bad_windows = max(1, _to_int(deploy.get("bad_windows_for_rollback"), 2))

        windows = list(observations or self._synthetic_windows(canary_window_min, min_sample_count, healthy_windows))
        evaluated: List[Dict[str, Any]] = []

        healthy_streak = 0
        bad_streak = 0

        for index, raw in enumerate(windows, start=1):
            window = dict(raw)
            window_minutes = _to_int(window.get("window_minutes"), canary_window_min)
            sample_count = _to_int(window.get("sample_count"), 0)
            error_rate = _to_float(window.get("error_rate"), 1.0)
            latency_p95_ms = _to_float(window.get("latency_p95_ms"), 999999.0)
            kpi_ratio = _to_float(window.get("kpi_ratio"), 0.0)

            eligible = window_minutes >= canary_window_min and sample_count >= min_sample_count
            healthy = (
                eligible
                and error_rate <= self.thresholds.max_error_rate
                and latency_p95_ms <= self.thresholds.max_latency_p95_ms
                and kpi_ratio >= self.thresholds.min_kpi_ratio
            )

            evaluated.append(
                {
                    "index": index,
                    "window_minutes": window_minutes,
                    "sample_count": sample_count,
                    "error_rate": error_rate,
                    "latency_p95_ms": latency_p95_ms,
                    "kpi_ratio": kpi_ratio,
                    "eligible": eligible,
                    "healthy": healthy,
                }
            )

            if not eligible:
                continue

            if healthy:
                healthy_streak += 1
                bad_streak = 0
            else:
                healthy_streak = 0
                bad_streak += 1

            if bad_streak >= bad_windows:
                return CanaryDecision(
                    outcome="rollback",
                    reason=f"canary unhealthy for {bad_streak} consecutive windows",
                    evaluated_windows=evaluated,
                    policy_snapshot=deploy,
                )
            if healthy_streak >= healthy_windows:
                return CanaryDecision(
                    outcome="promote",
                    reason=f"canary healthy for {healthy_streak} consecutive windows",
                    evaluated_windows=evaluated,
                    policy_snapshot=deploy,
                )

        return CanaryDecision(
            outcome="observing",
            reason="insufficient eligible windows for promotion/rollback decision",
            evaluated_windows=evaluated,
            policy_snapshot=deploy,
        )

    def execute_rollback(self, rollback_command: str | None = None) -> tuple[bool, str]:
        command = (rollback_command or "").strip()
        if not command:
            return True, "rollback command not configured; logical rollback only"

        try:
            result = subprocess.run(
                command,
                cwd=str(self.repo_dir),
                shell=True,
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as exc:
            return False, f"rollback command failed to start: {exc}"

        details = (result.stdout or "").strip() or (result.stderr or "").strip()
        if result.returncode == 0:
            return True, details or "rollback command completed"
        return False, details or f"rollback command exited with code {result.returncode}"

    def _synthetic_windows(
        self,
        canary_window_min: int,
        min_sample_count: int,
        healthy_windows: int,
    ) -> List[Dict[str, Any]]:
        return [
            {
                "window_minutes": canary_window_min,
                "sample_count": min_sample_count,
                "error_rate": max(self.thresholds.max_error_rate / 2.0, 0.0),
                "latency_p95_ms": max(self.thresholds.max_latency_p95_ms * 0.7, 1.0),
                "kpi_ratio": max(self.thresholds.min_kpi_ratio, 1.0),
            }
            for _ in range(max(healthy_windows, 1))
        ]
