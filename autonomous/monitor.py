"""Execution status monitor helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from autonomous.tools.cli_adapter import CliExecutionStatus


@dataclass
class ExecutionMonitor:
    """Collects snapshots emitted from adapter callbacks."""

    snapshots: List[CliExecutionStatus] = field(default_factory=list)

    def on_status(self, status: CliExecutionStatus) -> None:
        self.snapshots.append(status)
