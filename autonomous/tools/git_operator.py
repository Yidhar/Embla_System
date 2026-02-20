"""Git helper wrappers for autonomous tasks."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class GitOperator:
    """Thin wrapper around non-interactive git commands."""

    def __init__(self, repo_dir: str) -> None:
        self.repo_dir = Path(repo_dir)

    def _run(self, *args: str) -> CommandResult:
        result = subprocess.run(
            ["git", *args],
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        return CommandResult(result.returncode, result.stdout, result.stderr)

    def create_branch(self, branch_name: str) -> CommandResult:
        return self._run("checkout", "-b", branch_name)

    def checkout(self, branch_name: str) -> CommandResult:
        return self._run("checkout", branch_name)

    def diff(self, target: str = "main") -> CommandResult:
        return self._run("diff", "--", target)

    def merge(self, branch_name: str) -> CommandResult:
        return self._run("merge", "--no-ff", branch_name)

    def delete_branch(self, branch_name: str) -> CommandResult:
        return self._run("branch", "-D", branch_name)
