"""WS21-005 scaffold verify pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Tuple

VerifyStepFn = Callable[[Dict[str, Any]], bool | Tuple[bool, str]]


@dataclass(frozen=True)
class VerifyStep:
    name: str
    fn: VerifyStepFn
    severity: str = "error"  # error|warn


@dataclass(frozen=True)
class VerifyStepResult:
    name: str
    passed: bool
    severity: str
    detail: str


@dataclass(frozen=True)
class VerifyPipelineResult:
    passed: bool
    summary: str
    step_results: List[VerifyStepResult] = field(default_factory=list)


class ScaffoldVerifyPipeline:
    """Composable verify pipeline used by scaffold engine before commit."""

    def __init__(self, steps: Iterable[VerifyStep] | None = None) -> None:
        self.steps = list(steps or [])

    def run(self, context: Dict[str, Any]) -> VerifyPipelineResult:
        results: List[VerifyStepResult] = []
        hard_failed = False
        hard_failed_step = ""

        for step in self.steps:
            try:
                outcome = step.fn(context)
                if isinstance(outcome, tuple):
                    passed = bool(outcome[0])
                    detail = str(outcome[1])
                else:
                    passed = bool(outcome)
                    detail = "ok" if passed else "failed"
            except Exception as exc:  # defensive
                passed = False
                detail = f"exception: {exc}"

            result = VerifyStepResult(
                name=step.name,
                passed=passed,
                severity=step.severity,
                detail=detail,
            )
            results.append(result)

            if not passed and step.severity == "error":
                hard_failed = True
                hard_failed_step = step.name
                break

        if hard_failed:
            summary = f"verify failed at step={hard_failed_step}"
        elif any(not item.passed for item in results):
            summary = "verify passed with warnings"
        else:
            summary = "verify ok"

        return VerifyPipelineResult(
            passed=not hard_failed,
            summary=summary,
            step_results=results,
        )


def build_default_verify_pipeline() -> ScaffoldVerifyPipeline:
    return ScaffoldVerifyPipeline([])


__all__ = [
    "VerifyStep",
    "VerifyStepResult",
    "VerifyPipelineResult",
    "ScaffoldVerifyPipeline",
    "build_default_verify_pipeline",
]
