"""Evaluator for CLI results."""

from __future__ import annotations

from pathlib import Path
from typing import List

from autonomous.tools.cli_adapter import CliTaskResult
from autonomous.tools.test_runner import TestRunner
from autonomous.types import EvaluationReport, OptimizationTask


class Evaluator:
    """Validate CLI output and optional quality gates."""

    def __init__(self, repo_dir: str, run_quality_checks: bool = False) -> None:
        self.repo_dir = Path(repo_dir)
        self.run_quality_checks = run_quality_checks
        self.test_runner = TestRunner(str(self.repo_dir))

    def evaluate(self, task: OptimizationTask, result: CliTaskResult) -> EvaluationReport:
        reasons: List[str] = []
        lint_ok = True
        tests_ok = True

        if not result.success:
            reasons.append(f"cli execution failed: {result.stderr or 'unknown error'}")

        # Scope check: if target files are provided, changed files should stay in scope.
        if task.target_files and result.files_changed:
            allowed_prefixes = tuple(task.target_files)
            out_of_scope = [f for f in result.files_changed if not f.startswith(allowed_prefixes)]
            if out_of_scope:
                reasons.append(f"changed files out of scope: {', '.join(out_of_scope)}")

        if self.run_quality_checks and result.success:
            lint = self.test_runner.run_lint()
            lint_ok = lint.ok
            if not lint_ok:
                reasons.append("lint failed")

            tests = self.test_runner.run_tests()
            tests_ok = tests.ok
            if not tests_ok:
                reasons.append("tests failed")

        approved = result.success and lint_ok and tests_ok and not reasons
        return EvaluationReport(approved=approved, reasons=reasons, lint_ok=lint_ok, tests_ok=tests_ok)
