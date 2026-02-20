"""Claude Code CLI adapter."""

from __future__ import annotations

from typing import List

from autonomous.tools.cli_adapter import BaseSubprocessCliAdapter, CliTaskSpec


class ClaudeAdapter(BaseSubprocessCliAdapter):
    cli_name = "claude"
    binary_name = "claude"

    def build_command(self, spec: CliTaskSpec) -> List[str]:
        return [
            self.binary_name,
            "-p",
            spec.instruction,
            "--dangerously-skip-permissions",
        ]
