"""Task dispatcher for CLI execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from autonomous.monitor import ExecutionMonitor
from autonomous.tools.claude_adapter import ClaudeAdapter
from autonomous.tools.cli_adapter import AgentCliAdapter, CliTaskResult, CliTaskSpec
from autonomous.tools.cli_selector import CliSelectionStrategy
from autonomous.tools.codex_adapter import CodexAdapter
from autonomous.tools.gemini_adapter import GeminiAdapter
from autonomous.types import OptimizationTask


@dataclass
class DispatchResult:
    selected_cli: str | None
    result: CliTaskResult


class Dispatcher:
    """Chooses a CLI and executes tasks through adapter contracts."""

    def __init__(
        self,
        repo_dir: str,
        preferred_cli: str = "codex",
        fallback_order: List[str] | None = None,
        default_timeout_seconds: int = 3600,
    ) -> None:
        self.repo_dir = Path(repo_dir)
        self.selector = CliSelectionStrategy(preferred=preferred_cli, fallback_order=fallback_order or ["claude", "gemini"])
        self.adapters: Dict[str, AgentCliAdapter] = {
            "codex": CodexAdapter(default_timeout_seconds=default_timeout_seconds),
            "claude": ClaudeAdapter(default_timeout_seconds=default_timeout_seconds),
            "gemini": GeminiAdapter(default_timeout_seconds=default_timeout_seconds),
        }

    async def dispatch(self, task: OptimizationTask) -> DispatchResult:
        available = await self._available_cli_names()
        selected = self.selector.select(task, available)

        if not selected:
            return DispatchResult(
                selected_cli=None,
                result=CliTaskResult(
                    task_id=task.task_id,
                    cli_name="none",
                    exit_code=127,
                    stdout="",
                    stderr="No CLI available",
                    files_changed=[],
                    duration_seconds=0.0,
                    success=False,
                    execution_snapshots=[],
                ),
            )

        spec = CliTaskSpec(
            task_id=task.task_id,
            instruction=task.instruction,
            working_dir=str(self.repo_dir),
            target_files=task.target_files,
            context_files=task.context_files,
            timeout_seconds=0,
            complexity_hint=task.complexity,
        )
        monitor = ExecutionMonitor()
        result = await self.adapters[selected].execute(spec, on_status=monitor.on_status)
        return DispatchResult(selected_cli=selected, result=result)

    async def _available_cli_names(self) -> List[str]:
        names = list(self.adapters.keys())
        checks = [self.adapters[name].check_available() for name in names]
        results = await asyncio.gather(*checks, return_exceptions=True)
        available: List[str] = []
        for name, value in zip(names, results):
            if value is True:
                available.append(name)
        return available
