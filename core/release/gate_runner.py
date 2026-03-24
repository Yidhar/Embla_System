"""Release gate evaluation engine.

Reads gate_policy.yaml and runs the configured checks for each gate.
Emits events on pass/fail via the optional EventStore.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol

import yaml

logger = logging.getLogger("embla.release.gate_runner")

_DEFAULT_POLICY_PATH = Path("policy/gate_policy.yaml")


class EventEmitter(Protocol):
    def emit(self, event_type: str, payload: Dict[str, Any], **kwargs: Any) -> None: ...


@dataclass
class GateCheckResult:
    """Outcome of a single check within a gate."""

    check_name: str
    passed: bool
    output: str = ""
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_name": self.check_name,
            "passed": self.passed,
            "output": self.output,
            "error": self.error,
        }


@dataclass
class GateEvaluation:
    """Aggregate outcome of evaluating a full gate."""

    gate_name: str
    passed: bool
    checks: List[GateCheckResult] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_name": self.gate_name,
            "passed": self.passed,
            "checks": [c.to_dict() for c in self.checks],
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# Check runners
# ---------------------------------------------------------------------------

def _run_unit_test() -> GateCheckResult:
    """Run pytest and report pass/fail."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--tb=line", "-x"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        passed = result.returncode == 0
        output = (result.stdout or "")[:2000]
        error = (result.stderr or "")[:1000] if not passed else ""
        return GateCheckResult(check_name="unit_test", passed=passed, output=output, error=error)
    except subprocess.TimeoutExpired:
        return GateCheckResult(check_name="unit_test", passed=False, output="", error="pytest timed out after 300s")
    except Exception as exc:
        return GateCheckResult(check_name="unit_test", passed=False, output="", error=str(exc))


def _run_lint() -> GateCheckResult:
    """Run ruff check and report pass/fail."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "."],
            capture_output=True,
            text=True,
            timeout=120,
        )
        passed = result.returncode == 0
        output = (result.stdout or "")[:2000]
        error = (result.stderr or "")[:1000] if not passed else ""
        return GateCheckResult(check_name="lint", passed=passed, output=output, error=error)
    except subprocess.TimeoutExpired:
        return GateCheckResult(check_name="lint", passed=False, output="", error="ruff timed out after 120s")
    except Exception as exc:
        return GateCheckResult(check_name="lint", passed=False, output="", error=str(exc))


def _run_static_scan() -> GateCheckResult:
    """Static scan — auto-pass (placeholder for future integration)."""
    return GateCheckResult(check_name="static_scan", passed=True, output="auto-pass (no scanner configured)")


def _run_short_lived_token() -> GateCheckResult:
    """Short-lived token check — auto-pass (placeholder for future integration)."""
    return GateCheckResult(check_name="short_lived_token", passed=True, output="auto-pass (token policy not enforced)")


def _run_audit_log() -> GateCheckResult:
    """Verify audit log file exists."""
    audit_path = Path("scratch/runtime/audit_ledger.jsonl")
    if audit_path.exists():
        return GateCheckResult(check_name="audit_log", passed=True, output=f"audit log found at {audit_path}")
    return GateCheckResult(
        check_name="audit_log",
        passed=False,
        output="",
        error=f"audit log not found at {audit_path}",
    )


_CHECK_RUNNERS: Dict[str, Callable[[], GateCheckResult]] = {
    "unit_test": _run_unit_test,
    "lint": _run_lint,
    "static_scan": _run_static_scan,
    "short_lived_token": _run_short_lived_token,
    "audit_log": _run_audit_log,
}


# ---------------------------------------------------------------------------
# GateRunner
# ---------------------------------------------------------------------------


class GateRunner:
    """Evaluates release gates from gate_policy.yaml."""

    def __init__(
        self,
        *,
        policy_path: Path | None = None,
        event_emitter: Optional[EventEmitter] = None,
        check_runners: Optional[Dict[str, Callable[[], GateCheckResult]]] = None,
    ) -> None:
        self.policy_path = Path(policy_path or _DEFAULT_POLICY_PATH)
        self.event_emitter = event_emitter
        self._check_runners = dict(check_runners or _CHECK_RUNNERS)
        self._policy: Dict[str, Any] = self._load_policy()

    def _load_policy(self) -> Dict[str, Any]:
        if not self.policy_path.exists():
            logger.warning("Gate policy file not found: %s", self.policy_path)
            return {}
        try:
            text = self.policy_path.read_text(encoding="utf-8")
            policy = yaml.safe_load(text)
            return dict(policy or {})
        except Exception as exc:
            logger.warning("Failed to load gate policy: %s", exc)
            return {}

    def list_gates(self) -> List[str]:
        """Return the names of all configured gates."""
        gates = self._policy.get("gates")
        if not isinstance(gates, dict):
            return []
        return sorted(gates.keys())

    def evaluate_gate(self, gate_name: str) -> GateEvaluation:
        """Evaluate a single gate by running its configured checks."""
        name = str(gate_name or "").strip()
        gates = self._policy.get("gates")
        if not isinstance(gates, dict) or name not in gates:
            evaluation = GateEvaluation(gate_name=name, passed=False, reason=f"gate not found: {name}")
            self._emit_event(evaluation)
            return evaluation

        gate_cfg = gates[name]
        if not isinstance(gate_cfg, dict):
            gate_cfg = {}

        # auto_allow gates pass immediately with no checks
        if bool(gate_cfg.get("auto_allow", False)):
            evaluation = GateEvaluation(gate_name=name, passed=True, reason="auto_allow")
            self._emit_event(evaluation)
            return evaluation

        required_checks: List[str] = list(gate_cfg.get("required_checks") or [])

        # Handle special flags that add implicit checks
        if bool(gate_cfg.get("require_short_lived_token", False)) and "short_lived_token" not in required_checks:
            required_checks.append("short_lived_token")
        if bool(gate_cfg.get("require_audit_log", False)) and "audit_log" not in required_checks:
            required_checks.append("audit_log")

        if not required_checks:
            evaluation = GateEvaluation(gate_name=name, passed=True, reason="no checks configured")
            self._emit_event(evaluation)
            return evaluation

        check_results: List[GateCheckResult] = []
        for check_name in required_checks:
            runner = self._check_runners.get(str(check_name).strip())
            if runner is None:
                check_results.append(
                    GateCheckResult(
                        check_name=str(check_name),
                        passed=False,
                        error=f"no runner registered for check: {check_name}",
                    )
                )
                continue
            try:
                result = runner()
                check_results.append(result)
            except Exception as exc:
                check_results.append(
                    GateCheckResult(check_name=str(check_name), passed=False, error=str(exc))
                )

        all_passed = all(c.passed for c in check_results)
        failed_names = [c.check_name for c in check_results if not c.passed]
        reason = "all checks passed" if all_passed else f"failed checks: {', '.join(failed_names)}"

        evaluation = GateEvaluation(gate_name=name, passed=all_passed, checks=check_results, reason=reason)
        self._emit_event(evaluation)
        return evaluation

    def _emit_event(self, evaluation: GateEvaluation) -> None:
        if self.event_emitter is None:
            return
        event_type = "GateEvaluationPassed" if evaluation.passed else "GateEvaluationFailed"
        try:
            self.event_emitter.emit(
                event_type,
                evaluation.to_dict(),
                source="core.release.gate_runner",
            )
        except Exception as exc:
            logger.debug("Failed to emit gate evaluation event: %s", exc)


__all__ = ["GateRunner", "GateEvaluation", "GateCheckResult"]
