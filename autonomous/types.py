"""Shared types for the autonomous skeleton."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class OptimizationTask:
    """A unit of autonomous work produced by the planner."""

    task_id: str
    instruction: str
    complexity: str = "medium"
    target_files: List[str] = field(default_factory=list)
    context_files: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationReport:
    """Result produced by the evaluator."""

    approved: bool
    reasons: List[str] = field(default_factory=list)
    lint_ok: bool = True
    tests_ok: bool = True
