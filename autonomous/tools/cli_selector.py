"""CLI selection strategy."""

from __future__ import annotations

from typing import List, Sequence

from autonomous.types import OptimizationTask


class CliSelectionStrategy:
    """Pick one CLI based on preference, task shape, and availability."""

    def __init__(self, preferred: str = "claude", fallback_order: Sequence[str] | None = None) -> None:
        self.preferred = preferred
        self.fallback_order = list(fallback_order or ["claude", "gemini"])

    def select(self, task: OptimizationTask, available: List[str]) -> str | None:
        if not available:
            return None

        if self.preferred in available:
            return self.preferred

        if task.complexity in {"low", "medium"} and "claude" in available:
            return "claude"

        for candidate in self.fallback_order:
            if candidate in available:
                return candidate

        return available[0]
