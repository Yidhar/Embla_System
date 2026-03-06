"""Review Agent — independent reviewer for completed tasks.

Spawned by an Expert Agent after Dev agents finish their own verification.
Provides both a prompt-driven child-review path and a local fallback review helper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.prompt_engine import PromptAssembler
from agents.runtime.task_board import TaskBoardEngine, TaskStatus


@dataclass
class ReviewResult:
    """Result of a review pass."""

    verdict: str = "pending"  # approve | request_changes | reject
    requirement_alignment: List[Dict[str, Any]] = field(default_factory=list)
    code_quality: Dict[str, Any] = field(default_factory=dict)
    regression_risk: Dict[str, Any] = field(default_factory=dict)
    test_coverage: Dict[str, Any] = field(default_factory=dict)
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "requirement_alignment": self.requirement_alignment,
            "code_quality": self.code_quality,
            "regression_risk": self.regression_risk,
            "test_coverage": self.test_coverage,
            "issues": self.issues,
            "suggestions": self.suggestions,
            "summary": self.summary,
        }


@dataclass
class ReviewAgentConfig:
    """Configuration for a Review Agent instance."""

    prompt_blocks: List[str] = field(default_factory=list)
    memory_hints: List[str] = field(default_factory=list)
    prompts_root: str = "system/prompts"


class ReviewAgent:
    """Review Agent: the independent quality gate.

    Local fallback review methodology:
        1. Completeness: every task on the TaskBoard is done
        2. Consistency: modified files match TaskBoard file targets
        3. Correctness: tests pass
    """

    def __init__(
        self,
        *,
        config: Optional[ReviewAgentConfig] = None,
        task_board_engine: Optional[TaskBoardEngine] = None,
    ) -> None:
        self._config = config or ReviewAgentConfig()
        self._task_board = task_board_engine
        self._assembler = PromptAssembler(prompts_root=self._config.prompts_root)

    def build_system_prompt(self) -> str:
        """Build the independent reviewer system prompt."""
        review_rules = (
            "\n## Review Agent 行为准则\n"
            "1. 你是独立审查者，不直接修改代码；只做审查、质疑、归纳和结论。\n"
            "2. 先读原始任务、Dev 的 verification_report、改动文件列表，再做判断。\n"
            "3. 如有相关 L1 经验提示，可用 memory_read / memory_grep 检查团队经验、规范、历史案例。\n"
            "4. 必须覆盖以下五项：需求对齐、代码质量、回归风险、测试覆盖、最终结论。\n"
            "5. 审查完成后，调用 report_to_parent(type='completed')，并附带结构化 review_result。\n"
            "6. review_result.verdict 只能是 approve / request_changes / reject。\n"
            "7. 若信息不足以形成可靠结论，优先 request_changes 或 reject，并在 issues 中写清缺口。\n"
            "\nreview_result 最少必须包含以下字段：\n"
            "- verdict: approve | request_changes | reject\n"
            "- requirement_alignment: [{requirement, status, details}, ...]\n"
            "- code_quality: {status, issues, summary}\n"
            "- regression_risk: {level, summary}\n"
            "- test_coverage: {status, summary, missing_cases}\n"
            "- issues: [issue, ...]\n"
            "- suggestions: [suggestion, ...]\n"
        )
        try:
            return self._assembler.assemble(
                blocks=list(self._config.prompt_blocks),
                memory_hints=list(self._config.memory_hints) if self._config.memory_hints else None,
                extra_sections=[review_rules],
            )
        except Exception:
            parts: List[str] = []
            for block_path in self._config.prompt_blocks:
                full_path = Path(self._config.prompts_root) / block_path
                if full_path.exists():
                    parts.append(full_path.read_text(encoding="utf-8"))
            parts.append(review_rules)
            if self._config.memory_hints:
                parts.append("\n## 相关经验\n")
                for hint in self._config.memory_hints:
                    parts.append(f"- 参考: `{hint}`")
            return "\n".join(parts)

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

        declared_files: set[str] = set()
        for task in board.tasks:
            declared_files.update(str(path).strip() for path in list(task.files or []) if str(path).strip())

        actual_set = {str(path).strip() for path in actual_changed_files if str(path).strip()}
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
        passed = int(test_results.get("passed", 0) or 0)
        failed = int(test_results.get("failed", 0) or 0)
        errors = int(test_results.get("errors", 0) or 0)

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
        """Run fallback checks and produce a canonical review result."""
        completeness = self.check_completeness(board_id)
        consistency = self.check_consistency(board_id, actual_changed_files)
        correctness = self.check_correctness(test_results)

        requirement_alignment = [
            {
                "requirement": "All assigned TaskBoard items are completed.",
                "status": "passed" if completeness.get("ok") else "failed",
                "details": (
                    f"done={completeness.get('done', 0)}/{completeness.get('total', 0)}"
                    if "total" in completeness else str(completeness.get("reason") or "")
                ),
            },
            {
                "requirement": "Changed files remain aligned with declared task scope.",
                "status": "passed" if consistency.get("ok") else "failed",
                "details": (
                    f"actual={len(consistency.get('actual_files', []))}, declared={len(consistency.get('declared_files', []))}"
                    if "actual_files" in consistency or "declared_files" in consistency
                    else str(consistency.get("reason") or "")
                ),
            },
            {
                "requirement": "Validation checks pass without failures.",
                "status": "passed" if correctness.get("ok") else "failed",
                "details": (
                    f"passed={correctness.get('passed', 0)}, failed={correctness.get('failed', 0)}, errors={correctness.get('errors', 0)}"
                ),
            },
        ]

        issues: List[str] = []
        suggestions: List[str] = []
        if not completeness.get("ok"):
            issues.append(f"Incomplete tasks: {completeness.get('incomplete_tasks', [])}")
            suggestions.append("Finish all TaskBoard items before marking the work complete.")
        if not consistency.get("ok"):
            if consistency.get("undeclared_modifications"):
                issues.append(f"Undeclared file changes: {consistency['undeclared_modifications']}")
                suggestions.append("Either narrow the diff or update the declared task/file scope.")
            if consistency.get("declared_but_unmodified"):
                issues.append(f"Declared but not changed: {consistency['declared_but_unmodified']}")
                suggestions.append("Verify whether the untouched declared files are still required by the task.")
        if not correctness.get("ok"):
            issues.append(f"Test failures: {correctness.get('failed', 0)}, errors: {correctness.get('errors', 0)}")
            suggestions.append("Fix failing validation paths and rerun the affected test suite.")

        fatal = any(
            str(item.get("reason") or "").strip()
            for item in (completeness, consistency)
            if not item.get("ok") and "reason" in item
        )
        all_ok = completeness.get("ok", False) and consistency.get("ok", False) and correctness.get("ok", False)
        if all_ok:
            verdict = "approve"
        elif fatal:
            verdict = "reject"
        else:
            verdict = "request_changes"

        if verdict == "approve":
            regression_level = "low"
            regression_summary = "No obvious regression risk found in the fallback checks."
        elif not correctness.get("ok"):
            regression_level = "high"
            regression_summary = "Validation is failing, so regression risk is high until fixes are verified."
        else:
            regression_level = "medium"
            regression_summary = "Scope or completeness mismatches introduce follow-on regression risk."

        code_quality = {
            "status": "passed" if all_ok else "needs_attention",
            "issues": list(issues),
            "summary": (
                "Fallback reviewer did not inspect full source context directly; quality judgment is based on task board, file scope, and validation results."
            ),
        }
        test_coverage = {
            "status": "passed" if correctness.get("ok") else "failed",
            "summary": correctness.get("details") or (
                f"passed={correctness.get('passed', 0)}, failed={correctness.get('failed', 0)}, errors={correctness.get('errors', 0)}"
            ),
            "missing_cases": [],
            "passed": correctness.get("passed", 0),
            "failed": correctness.get("failed", 0),
            "errors": correctness.get("errors", 0),
        }
        regression_risk = {
            "level": regression_level,
            "summary": regression_summary,
        }

        status_icons = {
            "approve": "✅",
            "request_changes": "⚠️",
            "reject": "❌",
        }
        summary = " | ".join(
            [
                f"Verdict: {status_icons.get(verdict, 'ℹ️')} {verdict}",
                f"Requirements: {'✅' if completeness.get('ok') and consistency.get('ok') else '❌'}",
                f"Validation: {'✅' if correctness.get('ok') else '❌'}",
                f"Regression: {regression_level}",
            ]
        )

        return ReviewResult(
            verdict=verdict,
            requirement_alignment=requirement_alignment,
            code_quality=code_quality,
            regression_risk=regression_risk,
            test_coverage=test_coverage,
            issues=issues,
            suggestions=suggestions,
            summary=summary,
        )


__all__ = ["ReviewAgent", "ReviewAgentConfig", "ReviewResult"]
