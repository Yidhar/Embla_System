"""Test/lint command runner."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class RunnerResult:
    returncode: int
    command: List[str]
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class TestRunner:
    """Execute repository quality commands."""

    def __init__(self, repo_dir: str) -> None:
        self.repo_dir = Path(repo_dir)

    def run(self, command: List[str]) -> RunnerResult:
        result = subprocess.run(
            command,
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        return RunnerResult(result.returncode, command, result.stdout, result.stderr)

    def run_lint(self) -> RunnerResult:
        return self.run(["ruff", "check", "autonomous"])

    def run_tests(self) -> RunnerResult:
        return self.run(["python", "-m", "pytest", "autonomous/tests", "-q"])
