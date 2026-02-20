"""Unified Agent CLI adapter interfaces."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional


@dataclass
class CliTaskSpec:
    """Task payload sent to a CLI adapter."""

    task_id: str
    instruction: str
    working_dir: str
    target_files: List[str] = field(default_factory=list)
    context_files: List[str] = field(default_factory=list)
    timeout_seconds: int = 0
    complexity_hint: str = "medium"


@dataclass
class CliExecutionStatus:
    """Execution status sampled during CLI run."""

    elapsed_seconds: float
    last_stdout_line: str
    stdout_line_count: int
    is_stalled: bool
    files_touched: List[str]
    estimated_progress: float


@dataclass
class CliTaskResult:
    """Final execution output from CLI adapter."""

    task_id: str
    cli_name: str
    exit_code: int
    stdout: str
    stderr: str
    files_changed: List[str]
    duration_seconds: float
    success: bool
    execution_snapshots: List[CliExecutionStatus] = field(default_factory=list)


class AgentCliAdapter(ABC):
    """Common adapter contract for non-interactive CLI tools."""

    @abstractmethod
    async def execute(
        self,
        spec: CliTaskSpec,
        on_status: Optional[Callable[[CliExecutionStatus], None]] = None,
    ) -> CliTaskResult:
        """Execute one coding task and return a structured result."""

    @abstractmethod
    async def check_available(self) -> bool:
        """Return True if this CLI is available on PATH."""


class BaseSubprocessCliAdapter(AgentCliAdapter):
    """Generic subprocess-backed adapter."""

    cli_name: str = "base"
    binary_name: str = ""

    def __init__(self, default_timeout_seconds: int = 3600) -> None:
        self.default_timeout_seconds = max(1, default_timeout_seconds)

    @abstractmethod
    def build_command(self, spec: CliTaskSpec) -> List[str]:
        """Build command tokens for subprocess execution."""

    async def check_available(self) -> bool:
        return shutil.which(self.binary_name) is not None

    async def execute(
        self,
        spec: CliTaskSpec,
        on_status: Optional[Callable[[CliExecutionStatus], None]] = None,
    ) -> CliTaskResult:
        started = time.monotonic()
        snapshots: List[CliExecutionStatus] = []
        timeout_seconds = spec.timeout_seconds or self.default_timeout_seconds
        cmd = self.build_command(spec)

        if on_status:
            initial = CliExecutionStatus(
                elapsed_seconds=0.0,
                last_stdout_line="",
                stdout_line_count=0,
                is_stalled=False,
                files_touched=[],
                estimated_progress=0.0,
            )
            snapshots.append(initial)
            on_status(initial)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=spec.working_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
            exit_code = process.returncode or 0
            stdout = stdout_b.decode("utf-8", errors="replace")
            stderr = stderr_b.decode("utf-8", errors="replace")
        except asyncio.TimeoutError:
            try:
                if process.returncode is None:
                    process.kill()
                    await process.communicate()
            except Exception:
                pass
            elapsed = time.monotonic() - started
            timeout_stderr = f"{self.cli_name} timed out after {timeout_seconds}s"
            result = CliTaskResult(
                task_id=spec.task_id,
                cli_name=self.cli_name,
                exit_code=124,
                stdout="",
                stderr=timeout_stderr,
                files_changed=self._get_changed_files(spec.working_dir),
                duration_seconds=elapsed,
                success=False,
                execution_snapshots=snapshots,
            )
            if on_status:
                status = CliExecutionStatus(
                    elapsed_seconds=elapsed,
                    last_stdout_line=timeout_stderr,
                    stdout_line_count=0,
                    is_stalled=True,
                    files_touched=result.files_changed,
                    estimated_progress=0.0,
                )
                snapshots.append(status)
                on_status(status)
            return result
        except FileNotFoundError:
            elapsed = time.monotonic() - started
            msg = f"{self.binary_name} not found in PATH"
            return CliTaskResult(
                task_id=spec.task_id,
                cli_name=self.cli_name,
                exit_code=127,
                stdout="",
                stderr=msg,
                files_changed=[],
                duration_seconds=elapsed,
                success=False,
                execution_snapshots=snapshots,
            )

        elapsed = time.monotonic() - started
        files_changed = self._get_changed_files(spec.working_dir)
        stdout_lines = [line for line in stdout.splitlines() if line.strip()]
        status_line = stdout_lines[-1] if stdout_lines else ""

        final_status = CliExecutionStatus(
            elapsed_seconds=elapsed,
            last_stdout_line=status_line,
            stdout_line_count=len(stdout_lines),
            is_stalled=False,
            files_touched=files_changed,
            estimated_progress=1.0,
        )
        snapshots.append(final_status)
        if on_status:
            on_status(final_status)

        return CliTaskResult(
            task_id=spec.task_id,
            cli_name=self.cli_name,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            files_changed=files_changed,
            duration_seconds=elapsed,
            success=exit_code == 0,
            execution_snapshots=snapshots,
        )

    @staticmethod
    def _get_changed_files(working_dir: str) -> List[str]:
        cwd = Path(working_dir)
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                return []
            files: List[str] = []
            for line in result.stdout.splitlines():
                if len(line) > 3:
                    files.append(line[3:].strip())
            return files
        except Exception:
            return []
