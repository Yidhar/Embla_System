"""Review Agent — triple-check verifier for completed tasks.

Spawned by an Expert Agent after all Dev agents finish.
Verifies completeness, consistency, and correctness.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agents.runtime.task_board import TaskBoardEngine, TaskStatus

logger = logging.getLogger(__name__)


@dataclass
class ReviewResult:
    """Result of a review pass."""

    verdict: str = "pending"  # pass | fail | partial
    completeness: Dict[str, Any] = field(default_factory=dict)
    consistency: Dict[str, Any] = field(default_factory=dict)
    correctness: Dict[str, Any] = field(default_factory=dict)
    issues: List[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "completeness": self.completeness,
            "consistency": self.consistency,
            "correctness": self.correctness,
            "issues": self.issues,
            "summary": self.summary,
        }


@dataclass
class ReviewAgentConfig:
    """Configuration for a Review Agent instance."""

    prompt_blocks: List[str] = field(default_factory=list)


class ReviewAgent:
    """Review Agent: the quality gate.

    Triple-check methodology:
        1. Completeness: every task on the TaskBoard is done
        2. Consistency: modified files match TaskBoard file_targets
        3. Correctness: tests pass (deferred to LLM/tool execution)
    """

    def __init__(
        self,
        *,
        config: Optional[ReviewAgentConfig] = None,
        task_board_engine: Optional[TaskBoardEngine] = None,
    ) -> None:
        self._config = config or ReviewAgentConfig()
        self._task_board = task_board_engine

    def check_completeness(self, board_id: str) -> Dict[str, Any]:
        """Check 1: every task on the board is marked done."""
        if not self._task_board:
            return {"ok": False, "reason": "no_task_board_engine"}

        board = self._task_board.get_board(board_id)
        if not board:
            return {"ok": False, "reason": f"board {board_id} not found"}

        total = len(board.tasks)
        done = sum(1 for t in board.tasks if t.status == TaskStatus.DONE)
        failed = sum(1 for t in board.tasks if t.status == TaskStatus.FAILED)
        incomplete = [t.task_id for t in board.tasks if t.status not in (TaskStatus.DONE, TaskStatus.FAILED)]

        return {
            "ok": len(incomplete) == 0,
            "total": total,
            "done": done,
            "failed": failed,
            "incomplete_tasks": incomplete,
        }

    def check_consistency(
        self,
        board_id: str,
        actual_changed_files: List[str],
    ) -> Dict[str, Any]:
        """Check 2: actual changed files match TaskBoard declared files."""
        if not self._task_board:
            return {"ok": False, "reason": "no_task_board_engine"}

        board = self._task_board.get_board(board_id)
        if not board:
            return {"ok": False, "reason": f"board {board_id} not found"}

        declared_files: set = set()
        for task in board.tasks:
            declared_files.update(task.files)

        actual_set = set(actual_changed_files)

        undeclared = actual_set - declared_files
        unmodified = declared_files - actual_set

        return {
            "ok": len(undeclared) == 0 and len(unmodified) == 0,
            "declared_files": sorted(declared_files),
            "actual_files": sorted(actual_set),
            "undeclared_modifications": sorted(undeclared),
            "declared_but_unmodified": sorted(unmodified),
        }

    def check_correctness(self, test_results: Dict[str, Any]) -> Dict[str, Any]:
        """Check 3: tests all pass.

        Takes test results from an external tool call (e.g. run_tests).
        """
        passed = test_results.get("passed", 0)
        failed = test_results.get("failed", 0)
        errors = test_results.get("errors", 0)

        return {
            "ok": failed == 0 and errors == 0,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "details": test_results.get("details", ""),
        }

    def run_full_review(
        self,
        board_id: str,
        actual_changed_files: List[str],
        test_results: Dict[str, Any],
    ) -> ReviewResult:
        """Run all three checks and produce a review result."""
        c1 = self.check_completeness(board_id)
        c2 = self.check_consistency(board_id, actual_changed_files)
        c3 = self.check_correctness(test_results)

        issues: List[str] = []
        if not c1.get("ok"):
            issues.append(f"Incomplete tasks: {c1.get('incomplete_tasks', [])}")
        if not c2.get("ok"):
            if c2.get("undeclared_modifications"):
                issues.append(f"Undeclared file changes: {c2['undeclared_modifications']}")
            if c2.get("declared_but_unmodified"):
                issues.append(f"Declared but not changed: {c2['declared_but_unmodified']}")
        if not c3.get("ok"):
            issues.append(f"Test failures: {c3.get('failed', 0)}, errors: {c3.get('errors', 0)}")

        all_ok = c1.get("ok", False) and c2.get("ok", False) and c3.get("ok", False)
        verdict = "pass" if all_ok else ("partial" if c1.get("ok") else "fail")

        summary_parts = []
        summary_parts.append(f"Completeness: {'✅' if c1.get('ok') else '❌'}")
        summary_parts.append(f"Consistency: {'✅' if c2.get('ok') else '❌'}")
        summary_parts.append(f"Correctness: {'✅' if c3.get('ok') else '❌'}")

        return ReviewResult(
            verdict=verdict,
            completeness=c1,
            consistency=c2,
            correctness=c3,
            issues=issues,
            summary=" | ".join(summary_parts),
        )


__all__ = ["ReviewAgent", "ReviewAgentConfig", "ReviewResult"]
