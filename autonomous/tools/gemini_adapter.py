"""Gemini CLI adapter."""

from __future__ import annotations

from typing import List

from autonomous.tools.cli_adapter import BaseSubprocessCliAdapter, CliTaskSpec


class GeminiAdapter(BaseSubprocessCliAdapter):
    cli_name = "gemini"
    binary_name = "gemini"

    def build_command(self, spec: CliTaskSpec) -> List[str]:
        return [self.binary_name, "-p", spec.instruction]
