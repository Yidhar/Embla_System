"""Codex CLI adapter."""

from __future__ import annotations

from typing import List

from autonomous.tools.cli_adapter import BaseSubprocessCliAdapter, CliTaskSpec


class CodexAdapter(BaseSubprocessCliAdapter):
    cli_name = "codex"
    binary_name = "codex"

    def build_command(self, spec: CliTaskSpec) -> List[str]:
        return [
            self.binary_name,
            "--approval-mode",
            "full-auto",
            "-q",
            spec.instruction,
        ]
