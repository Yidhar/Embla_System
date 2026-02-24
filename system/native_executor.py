from __future__ import annotations

import asyncio
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from system.killswitch_guard import validate_freeze_command
from system.process_lineage import get_process_lineage_registry


class NativeSecurityError(PermissionError):
    """Raised when a file or command operation violates security restrictions."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class NativeExecutor:
    """
    Native command/file executor with strict project-root confinement.

    Security goals:
    - All file operations are restricted to E:\\Programs\\NagaAgent.
    - Command execution uses asyncio.create_subprocess_exec.
    - High-risk commands are blocked (format, del /f /s, rm, etc.).
    - Deletion is file-only and limited to project-root files.
    """

    PROJECT_ROOT = Path(r"E:\Programs\NagaAgent").resolve()

    _BLOCKED_TOKENS = {
        "format",
        "diskpart",
        "del",
        "erase",
        "rd",
        "rmdir",
        "rm",
        "remove-item",
    }

    _BLOCKED_FLOW_TOKENS = {
        "cd",
        "chdir",
        "pushd",
        "popd",
    }

    _INTERPRETER_GUARD_PATTERNS = (
        (r"(?i)(^|[\s;&|()<>])python(?:3)?\s+-c\s+", "python -c"),
        (r"(?i)(^|[\s;&|()<>])node\s+-e\s+", "node -e"),
        (r"(?i)(^|[\s;&|()<>])(?:bash|sh)\s+-c\s+", "shell -c"),
        (r"(?i)(^|[\s;&|()<>])(?:powershell|pwsh)\s+-(?:enc|encodedcommand)\b", "powershell encoded"),
        (r"(?i)base64\s+-d\s*\|\s*(?:bash|sh)\b", "base64 | sh"),
    )

    _DETACHED_PROCESS_PATTERNS = (
        (r"(?i)\bnohup\b", "nohup"),
        (r"(?i)\bsetsid\b", "setsid"),
        (r"(?i)\bdocker\s+run\s+-d\b", "docker run -d"),
        (r"(?i)(^|[\s;&|()<>])start\s+/b\b", "start /b"),
        (r"(?i)\s&\s*$", "background '&'"),
    )

    _ABS_PATH_RE = re.compile(
        r"(?i)(?:\"([a-z]:[\\/][^\"]+)\"|'([a-z]:[\\/][^']+)'|([a-z]:[\\/][^\s\"']+))"
    )
    _UNC_PATH_RE = re.compile(
        r"(?:\"(\\\\[^\\\"]+)\"|'(\\\\[^\\']+)'|(\\\\[^\s\"']+))"
    )
    _TRAVERSAL_RE = re.compile(r"(?i)(^|[\s\"'])\.\.(?:[\\/]|$)")
    _TOKEN_BOUNDARY_RE = r"(?i)(^|[\s;&|()<>]){token}(?=\s|$)"

    def __init__(
        self,
        project_root: str | os.PathLike[str] | None = None,
        *,
        default_timeout_s: float | None = 120.0,
    ) -> None:
        """
        `project_root` can narrow scope to a subdirectory, but never outside PROJECT_ROOT.
        """
        fixed_root = self.PROJECT_ROOT
        if project_root is None:
            resolved_root = fixed_root
        else:
            candidate = Path(project_root)
            if not candidate.is_absolute():
                candidate = fixed_root / candidate
            resolved_root = candidate.resolve(strict=False)
            if not self._is_within_root(resolved_root, fixed_root):
                raise NativeSecurityError(
                    f"Project root must stay inside {fixed_root}, got: {resolved_root}"
                )

        resolved_root.mkdir(parents=True, exist_ok=True)
        self.base_dir = resolved_root
        self.default_timeout_s = default_timeout_s

    @staticmethod
    def _is_within_root(candidate: Path, root: Path) -> bool:
        """
        Robust Windows-safe containment check.

        Avoids prefix bugs like:
        - E:\\Programs\\NagaAgent2 incorrectly matching E:\\Programs\\NagaAgent
        """
        try:
            root_s = os.path.normcase(os.path.abspath(str(root)))
            cand_s = os.path.normcase(os.path.abspath(str(candidate)))
            return os.path.commonpath([root_s, cand_s]) == root_s
        except Exception:
            return False

    def _resolve_safe_path(self, path: str | os.PathLike[str], *, kind: str = "path") -> Path:
        raw = Path(path)
        full = raw if raw.is_absolute() else (self.base_dir / raw)
        resolved = full.resolve(strict=False)

        if not self._is_within_root(resolved, self.PROJECT_ROOT):
            raise NativeSecurityError(f"{kind} is outside project root: {path}")

        return resolved

    @staticmethod
    def _decode_text_auto(data: bytes) -> str:
        """
        Auto-detect UTF-8/GBK for Windows command output and file bytes.
        """
        if not data:
            return ""

        for encoding in ("utf-8-sig", "utf-8", "gbk"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue

        return data.decode("utf-8", errors="replace")

    def _validate_command_string(self, command: str) -> None:
        cmd = command.strip()
        if not cmd:
            raise ValueError("Command is empty")

        lowered = cmd.lower()

        # NGA-WS14-002: 解释器入口硬门禁（阻断高风险 inline 执行）
        for pattern, label in self._INTERPRETER_GUARD_PATTERNS:
            if re.search(pattern, cmd):
                raise NativeSecurityError(f"Interpreter gate blocked: {label}")

        # NGA-WS14-005/006: 最小 detached 进程防护（防幽灵进程）
        for pattern, label in self._DETACHED_PROCESS_PATTERNS:
            if re.search(pattern, cmd):
                raise NativeSecurityError(f"Detached process pattern blocked: {label}")

        for token in sorted(self._BLOCKED_TOKENS | self._BLOCKED_FLOW_TOKENS, key=len, reverse=True):
            pattern = self._TOKEN_BOUNDARY_RE.format(token=re.escape(token))
            if re.search(pattern, lowered):
                raise NativeSecurityError(f"Blocked shell token: {token}")

        if self._TRAVERSAL_RE.search(cmd):
            raise NativeSecurityError("Blocked path traversal ('..') in command")

        if self._UNC_PATH_RE.search(cmd):
            raise NativeSecurityError("Blocked UNC path in command")

        for match in self._ABS_PATH_RE.finditer(cmd):
            path_token = next((group for group in match.groups() if group), "")
            if not path_token:
                continue
            resolved = Path(path_token).resolve(strict=False)
            if not self._is_within_root(resolved, self.PROJECT_ROOT):
                raise NativeSecurityError(f"Blocked absolute path outside project root: {path_token}")

        # NGA-WS14-009: KillSwitch 命令必须保留 OOB allowlist，不允许无差别 OUTPUT DROP。
        ok, reason = validate_freeze_command(cmd)
        if not ok:
            raise NativeSecurityError(reason)

    def is_safe_command(self, command: str) -> bool:
        """Best-effort safety precheck for shell command strings."""
        try:
            self._validate_command_string(command)
            return True
        except Exception:
            return False

    @staticmethod
    def _program_key(program: str) -> str:
        name = Path(program).name.lower()
        if name.endswith((".exe", ".cmd", ".bat", ".com")):
            name = Path(name).stem
        return name

    def _validate_argv(self, argv: Sequence[str], *, cwd: Path) -> None:
        if not argv:
            raise ValueError("Command argv is empty")

        program_key = self._program_key(str(argv[0]))
        if program_key in self._BLOCKED_TOKENS:
            raise NativeSecurityError(f"Blocked program: {program_key}")

        args_lower = [str(x).strip().lower() for x in argv[1:]]

        # WS14-002: argv-level interpreter gate (avoid bypassing shell-string checks).
        if program_key in {"python", "python3"} and "-c" in args_lower:
            raise NativeSecurityError("Interpreter gate blocked: python -c")
        if program_key in {"bash", "sh"} and "-c" in args_lower:
            raise NativeSecurityError("Interpreter gate blocked: shell -c")
        if program_key == "node" and "-e" in args_lower:
            raise NativeSecurityError("Interpreter gate blocked: node -e")
        if program_key in {"powershell", "pwsh"} and any(a in {"-enc", "-encodedcommand"} for a in args_lower):
            raise NativeSecurityError("Interpreter gate blocked: powershell encoded")

        # WS14-005/006: detached process guard in argv mode.
        if program_key in {"nohup", "setsid"}:
            raise NativeSecurityError(f"Detached process pattern blocked: {program_key}")
        if program_key == "docker" and len(args_lower) >= 2 and args_lower[0] == "run" and "-d" in args_lower:
            raise NativeSecurityError("Detached process pattern blocked: docker run -d")

        if program_key in {"cmd", "powershell", "pwsh"}:
            # Validate full command text to catch embedded destructive operations.
            self._validate_command_string(" ".join(str(x) for x in argv))

        ok, reason = validate_freeze_command(" ".join(str(x) for x in argv))
        if not ok:
            raise NativeSecurityError(reason)

        for token in argv[1:]:
            tok = str(token)
            if not tok:
                continue

            if self._UNC_PATH_RE.fullmatch(tok):
                raise NativeSecurityError(f"Blocked UNC path argument: {tok}")

            if self._TRAVERSAL_RE.search(tok):
                raise NativeSecurityError(f"Blocked traversal argument: {tok}")

            # Best-effort absolute-path check for argv mode.
            if re.match(r"(?i)^[a-z]:[\\/]", tok):
                resolved = Path(tok).resolve(strict=False)
                if not self._is_within_root(resolved, self.PROJECT_ROOT):
                    raise NativeSecurityError(f"Blocked absolute path argument: {tok}")
            elif "/" in tok or "\\" in tok:
                resolved = (cwd / tok).resolve(strict=False)
                if not self._is_within_root(resolved, self.PROJECT_ROOT):
                    raise NativeSecurityError(f"Blocked path argument outside project root: {tok}")

    async def execute_shell(
        self,
        command: str,
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
        call_id: str | None = None,
        fencing_epoch: int | None = None,
    ) -> CommandResult:
        """
        Execute a shell command using cmd.exe and asyncio.create_subprocess_exec.
        """
        self._validate_command_string(command)

        safe_cwd = self._resolve_safe_path(cwd or self.base_dir, kind="cwd")
        if not safe_cwd.exists() or not safe_cwd.is_dir():
            raise FileNotFoundError(f"cwd does not exist or is not a directory: {safe_cwd}")

        merged_env: dict[str, str] | None
        if env is None:
            merged_env = None
        else:
            merged_env = os.environ.copy()
            merged_env.update({str(k): str(v) for k, v in env.items()})

        process = await asyncio.create_subprocess_exec(
            "cmd.exe",
            "/d",
            "/s",
            "/c",
            command,
            cwd=str(safe_cwd),
            env=merged_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        job_root_id: str | None = None
        try:
            job_root_id = get_process_lineage_registry().register_start(
                call_id=call_id or f"call_{uuid.uuid4().hex[:12]}",
                command=command,
                root_pid=int(process.pid or 0),
                fencing_epoch=fencing_epoch,
            )
        except Exception:
            job_root_id = None

        effective_timeout = self.default_timeout_s if timeout_s is None else timeout_s
        try:
            if effective_timeout is None:
                stdout_b, stderr_b = await process.communicate()
            else:
                stdout_b, stderr_b = await asyncio.wait_for(process.communicate(), timeout=effective_timeout)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.communicate()
            if job_root_id:
                try:
                    get_process_lineage_registry().register_end(
                        job_root_id,
                        return_code=None,
                        status="timeout",
                        reason=f"timeout_after_{effective_timeout}s",
                    )
                except Exception:
                    pass
            raise TimeoutError(f"Command timed out after {effective_timeout}s") from exc

        if job_root_id:
            try:
                get_process_lineage_registry().register_end(
                    job_root_id,
                    return_code=int(process.returncode or 0),
                    status="ok" if int(process.returncode or 0) == 0 else "error",
                )
            except Exception:
                pass

        return CommandResult(
            returncode=int(process.returncode or 0),
            stdout=self._decode_text_auto(stdout_b).rstrip(),
            stderr=self._decode_text_auto(stderr_b).rstrip(),
        )

    async def run(
        self,
        cmd: str | Sequence[str],
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
        call_id: str | None = None,
        fencing_epoch: int | None = None,
    ) -> CommandResult:
        """
        General async command runner.

        - str input -> shell execution via cmd.exe /c
        - sequence input -> direct argv exec with guard checks
        """
        if isinstance(cmd, str):
            return await self.execute_shell(
                cmd,
                cwd=cwd,
                env=env,
                timeout_s=timeout_s,
                call_id=call_id,
                fencing_epoch=fencing_epoch,
            )

        argv = [str(x) for x in cmd]
        safe_cwd = self._resolve_safe_path(cwd or self.base_dir, kind="cwd")
        if not safe_cwd.exists() or not safe_cwd.is_dir():
            raise FileNotFoundError(f"cwd does not exist or is not a directory: {safe_cwd}")

        self._validate_argv(argv, cwd=safe_cwd)

        merged_env = os.environ.copy()
        if env:
            merged_env.update({str(k): str(v) for k, v in env.items()})

        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(safe_cwd),
            env=merged_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        joined_cmd = " ".join(argv)
        job_root_id: str | None = None
        try:
            job_root_id = get_process_lineage_registry().register_start(
                call_id=call_id or f"call_{uuid.uuid4().hex[:12]}",
                command=joined_cmd,
                root_pid=int(process.pid or 0),
                fencing_epoch=fencing_epoch,
            )
        except Exception:
            job_root_id = None

        effective_timeout = self.default_timeout_s if timeout_s is None else timeout_s
        try:
            if effective_timeout is None:
                stdout_b, stderr_b = await process.communicate()
            else:
                stdout_b, stderr_b = await asyncio.wait_for(process.communicate(), timeout=effective_timeout)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.communicate()
            if job_root_id:
                try:
                    get_process_lineage_registry().register_end(
                        job_root_id,
                        return_code=None,
                        status="timeout",
                        reason=f"timeout_after_{effective_timeout}s",
                    )
                except Exception:
                    pass
            raise TimeoutError(f"Command timed out after {effective_timeout}s") from exc

        if job_root_id:
            try:
                get_process_lineage_registry().register_end(
                    job_root_id,
                    return_code=int(process.returncode or 0),
                    status="ok" if int(process.returncode or 0) == 0 else "error",
                )
            except Exception:
                pass

        return CommandResult(
            returncode=int(process.returncode or 0),
            stdout=self._decode_text_auto(stdout_b).rstrip(),
            stderr=self._decode_text_auto(stderr_b).rstrip(),
        )

    async def execute_command(self, cmd_name: str, args: list[str] | None = None) -> tuple[int, str, str]:
        """
        Backward-compatible wrapper:
        - For cmd builtins, executes through `execute_shell`.
        - Otherwise executes argv directly.
        """
        args = args or []
        cmd_key = self._program_key(cmd_name)
        if cmd_key in {"dir", "echo", "type"}:
            command = " ".join([cmd_key, *args]).strip()
            result = await self.execute_shell(command)
        else:
            result = await self.run([cmd_name, *args])
        return result.returncode, result.stdout, result.stderr

    def read_text(self, path: str | os.PathLike[str]) -> str:
        safe_path = self._resolve_safe_path(path, kind="file")
        data = safe_path.read_bytes()
        return self._decode_text_auto(data)

    def write_text(
        self,
        path: str | os.PathLike[str],
        content: str,
        *,
        encoding: str = "utf-8",
        newline: str | None = None,
    ) -> None:
        safe_path = self._resolve_safe_path(path, kind="file")
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        safe_path.write_text(content, encoding=encoding, newline=newline)

    def delete_file(self, path: str | os.PathLike[str], *, missing_ok: bool = True) -> None:
        """
        Safe deletion:
        - path must resolve inside project root
        - only regular files can be deleted
        - symlink/reparse-point files are refused for extra safety
        """
        safe_path = self._resolve_safe_path(path, kind="file")

        if not safe_path.exists():
            if missing_ok:
                return
            raise FileNotFoundError(str(safe_path))

        if safe_path.is_symlink():
            raise NativeSecurityError(f"Refusing to delete symlink/reparse point: {safe_path}")

        if safe_path.is_dir():
            raise IsADirectoryError(str(safe_path))

        safe_path.unlink()

    async def read_file(self, path: str | os.PathLike[str]) -> str:
        return await asyncio.to_thread(self.read_text, path)

    async def write_file(
        self,
        path: str | os.PathLike[str],
        content: str,
        *,
        encoding: str = "utf-8",
        newline: str | None = None,
    ) -> None:
        await asyncio.to_thread(self.write_text, path, content, encoding=encoding, newline=newline)

    async def delete(self, path: str | os.PathLike[str], *, missing_ok: bool = True) -> None:
        await asyncio.to_thread(self.delete_file, path, missing_ok=missing_ok)


if __name__ == "__main__":
    async def _self_test() -> None:
        ex = NativeExecutor()
        result = await ex.execute_shell("echo NativeExecutor OK")
        print(result)

        await ex.write_file("system/_native_executor_test.txt", "hello")
        print(await ex.read_file("system/_native_executor_test.txt"))
        await ex.delete("system/_native_executor_test.txt")

        try:
            await ex.execute_shell("del /f /s *")
        except NativeSecurityError as exc:
            print("blocked:", exc)

    asyncio.run(_self_test())
