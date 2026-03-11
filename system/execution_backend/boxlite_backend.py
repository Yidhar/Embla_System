from __future__ import annotations

import base64
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List

from system.boxlite.manager import BoxLiteManager, build_box_session_name, probe_boxlite_runtime
from system.execution_backend.base import ExecutionBackend, ExecutionBackendUnavailableError
from system.native_executor import NativeSecurityError
from system.test_baseline_guard import TestBaselineGuard


def _safe_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        number = int(value) if value is not None else int(default)
    except Exception:
        number = int(default)
    return max(min_value, min(max_value, number))


def _preview_text(text: str, limit: int = 6000) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 14)] + "\n...(truncated)"


def _preview_lines(text: str, max_lines: int) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    clipped = lines[:max_lines]
    clipped.append(f"...(truncated, total={len(lines)} lines)")
    return "\n".join(clipped)


class BoxLiteExecutionBackend(ExecutionBackend):
    name = "boxlite"
    service_name = "boxlite"

    def __init__(self) -> None:
        self.manager = BoxLiteManager()

    @staticmethod
    def _map_to_guest_path(value: Any, context) -> str:
        text = str(value or "").strip()
        if not text:
            return text
        execution_root = str(context.execution_root or "/workspace").rstrip("/") or "/workspace"
        host_root = str(context.workspace_host_root or "").strip()
        posix_root = PurePosixPath(execution_root)
        candidate = PurePosixPath(text)
        if candidate.is_absolute():
            if host_root:
                try:
                    rel = Path(text).resolve(strict=False).relative_to(Path(host_root).resolve(strict=False))
                    return str(posix_root.joinpath(*rel.parts))
                except Exception:
                    return str(candidate)
            return str(candidate)
        return str(posix_root.joinpath(*candidate.parts))

    @staticmethod
    def _map_to_host_path(value: Any, context) -> str:
        text = str(value or "").strip()
        if not text:
            return text
        workspace_root = Path(str(context.workspace_host_root or context.project_root)).resolve(strict=False)
        execution_root = str(context.execution_root or "/workspace").rstrip("/") or "/workspace"
        if text.startswith(execution_root.rstrip("/") + "/") or text == execution_root:
            rel = PurePosixPath(text).relative_to(PurePosixPath(execution_root))
            return str((workspace_root / Path(*rel.parts)).resolve(strict=False))
        raw = Path(text)
        if raw.is_absolute():
            return str(raw.resolve(strict=False))
        return str((workspace_root / raw).resolve(strict=False))

    @staticmethod
    def _resolve_requester(call: Dict[str, Any], *, context) -> str | None:
        requester = (
            str(call.get("requester") or call.get("_session_id") or call.get("session_id") or getattr(context, "session_id", "") or "").strip()
        )
        return requester or None

    def _resolve_host_safe_path(self, value: Any, *, context, native_tool_executor, kind: str = "file") -> Path:
        host_path = self._map_to_host_path(value, context)
        return native_tool_executor.executor._resolve_safe_path(host_path, kind=kind)

    def prepare_call(self, tool_name: str, call: Dict[str, Any], *, context, native_tool_executor) -> Dict[str, Any]:
        del native_tool_executor
        safe_call = dict(call) if isinstance(call, dict) else {}
        safe_call.setdefault("_execution_backend", self.name)
        safe_call.setdefault("_execution_root", str(context.execution_root or "/workspace"))
        execution_root = str(context.execution_root or "/workspace")

        if tool_name in {"read_file", "write_file", "file_ast_skeleton", "file_ast_chunk_read"}:
            for key in ("path", "file_path"):
                if key in safe_call:
                    safe_call[key] = self._map_to_guest_path(safe_call.get(key), context)
        elif tool_name in {"search_keyword", "list_files"}:
            key = "search_path" if tool_name == "search_keyword" else "path"
            current = safe_call.get(key)
            if current in (None, "", "."):
                safe_call[key] = execution_root
            else:
                safe_call[key] = self._map_to_guest_path(current, context)
        elif tool_name in {"run_cmd", "get_cwd", "python_repl", "sleep_and_watch"}:
            current_cwd = safe_call.get("cwd")
            if current_cwd in (None, "", "."):
                safe_call["cwd"] = execution_root
            else:
                safe_call["cwd"] = self._map_to_guest_path(current_cwd, context)
            if tool_name == "sleep_and_watch":
                for key in ("log_file", "path"):
                    if key in safe_call:
                        safe_call[key] = self._map_to_guest_path(safe_call.get(key), context)
        elif tool_name.startswith("git_"):
            current_cwd = safe_call.get("cwd")
            current_repo_path = safe_call.get("repo_path")
            safe_call["cwd"] = execution_root if current_cwd in (None, "", ".") else self._map_to_guest_path(current_cwd, context)
            safe_call["repo_path"] = execution_root if current_repo_path in (None, "", ".") else self._map_to_guest_path(current_repo_path, context)
            for key in ("target_path", "path", "file_path", "pathspec"):
                if key in safe_call and safe_call.get(key) not in (None, ""):
                    safe_call[key] = self._map_to_guest_path(safe_call.get(key), context)
        elif tool_name == "workspace_txn_apply":
            raw_changes = safe_call.get("changes")
            if isinstance(raw_changes, list):
                rewritten = []
                for item in raw_changes:
                    if not isinstance(item, dict):
                        rewritten.append(item)
                        continue
                    next_item = dict(item)
                    if "path" in next_item:
                        next_item["path"] = self._map_to_guest_path(next_item.get("path"), context)
                    rewritten.append(next_item)
                safe_call["changes"] = rewritten
        return safe_call

    @staticmethod
    def _box_command_not_found(result: Dict[str, Any], command: str) -> bool:
        exit_code = int(result.get("exit_code", 1))
        if exit_code != 127:
            return False
        haystack = ((str(result.get('stdout') or '')) + '\n' + (str(result.get('stderr') or ''))).lower()
        command_text = str(command or '').strip().lower()
        if not command_text:
            return True
        return command_text in haystack or "not found" in haystack or "no such file" in haystack

    def _make_host_delegate_call(self, tool_name: str, call: Dict[str, Any], *, context) -> Dict[str, Any]:
        delegated = dict(call) if isinstance(call, dict) else {}
        repo_root = str(context.workspace_host_root or context.project_root).strip()
        execution_root = str(context.execution_root or "/workspace").rstrip("/") or "/workspace"

        def _map_repo_relative(value: Any) -> str:
            text_value = str(value or "").strip()
            if not text_value:
                return text_value
            if text_value == execution_root:
                return "."
            prefix = execution_root.rstrip("/") + "/"
            if text_value.startswith(prefix):
                rel = PurePosixPath(text_value).relative_to(PurePosixPath(execution_root))
                rel_text = str(PurePosixPath(*rel.parts))
                return rel_text or "."
            if repo_root:
                try:
                    rel = Path(text_value).resolve(strict=False).relative_to(Path(repo_root).resolve(strict=False))
                    rel_text = str(rel).replace('\\', '/')
                    return rel_text or "."
                except Exception:
                    pass
            return text_value

        if tool_name in {"artifact_reader", "killswitch_plan"}:
            return delegated

        if tool_name in {"file_ast_skeleton", "file_ast_chunk_read"}:
            for key in ("path", "file_path"):
                if key in delegated and delegated.get(key) not in (None, ""):
                    delegated[key] = self._map_to_host_path(delegated.get(key), context)
            return delegated

        if tool_name.startswith("git_"):
            delegated["repo_path"] = repo_root or delegated.get("repo_path") or delegated.get("cwd") or "."
            delegated["cwd"] = repo_root or delegated.get("cwd") or delegated.get("repo_path") or "."
            for key in ("target_path", "path", "file_path", "pathspec"):
                if key in delegated and delegated.get(key) not in (None, ""):
                    delegated[key] = _map_repo_relative(delegated.get(key))
            return delegated

        return delegated

    async def _delegate_to_native_tool(self, tool_name: str, call: Dict[str, Any], *, context, native_tool_executor) -> str:
        delegated = self._make_host_delegate_call(tool_name, call, context=context)
        return await native_tool_executor._execute_native_tool(tool_name, delegated)

    @staticmethod
    def _resolve_box_name(context) -> str:
        return build_box_session_name(getattr(context, "session_id", ""))

    @staticmethod
    def _as_process_result(result: Dict[str, Any]):
        return type(
            "BoxCmd",
            (),
            {
                "returncode": int(result.get("exit_code", 1)),
                "stdout": str(result.get("stdout", "") or ""),
                "stderr": str(result.get("stderr", "") or ""),
            },
        )()

    def _persist_box_runtime_metadata(self, result: Dict[str, Any], *, context, native_tool_executor) -> None:
        store = getattr(native_tool_executor, "_agent_session_store", None)
        session_id = str(getattr(context, "session_id", "") or "").strip()
        if store is None or not session_id:
            return

        updates = {"box_name": self._resolve_box_name(context)}
        box_id = str(result.get("box_id") or "").strip()
        if box_id:
            updates["box_id"] = box_id

        try:
            store.update_metadata(session_id, updates)
        except Exception:
            return

    async def _run_box_command(
        self,
        *,
        context,
        command: str,
        args: list[str],
        native_tool_executor=None,
        env: Dict[str, str] | None = None,
        timeout_seconds: float | None = None,
        working_dir: str | None = None,
    ) -> Dict[str, Any]:
        box_name = self._resolve_box_name(context)
        resolved_working_dir = str(working_dir or context.execution_root or "/workspace").strip() or str(context.execution_root or "/workspace")
        result = await self.manager.exec_in_box(
            box_name=box_name,
            workspace_host_root=str(context.workspace_host_root or context.project_root),
            command=command,
            args=args,
            env=env,
            working_dir=resolved_working_dir,
            timeout_seconds=timeout_seconds,
            project_root=str(context.project_root or ""),
        )
        result.setdefault("box_name", box_name)
        if native_tool_executor is not None:
            self._persist_box_runtime_metadata(result, context=context, native_tool_executor=native_tool_executor)
        return result

    async def _python_repl(self, call: Dict[str, Any], *, context, native_tool_executor) -> str:
        from apiserver.native_tools import _PY_REPL_BOOTSTRAP, _build_safe_python_payload

        code = str(call.get("code") or "").strip()
        expression = call.get("expression")
        if not code and expression is not None:
            expr = str(expression).strip()
            if expr:
                code = f"result = ({expr})"
        if not code:
            raise ValueError("python_repl 缺少 code 或 expression")
        if len(code) > 20000:
            raise ValueError("python_repl code 过长，最多 20000 字符")

        sandbox = str(call.get("sandbox") or "restricted").strip().lower()
        if sandbox not in {"restricted", "docker"}:
            raise ValueError("python_repl sandbox 仅支持 restricted 或 docker")

        timeout_s = _safe_int(call.get("timeout_seconds"), 15, 1, 180)
        max_output_chars = _safe_int(call.get("max_output_chars"), 10000, 200, 500000)
        payload_script = _build_safe_python_payload(code)
        payload_b64 = base64.b64encode(payload_script.encode("utf-8")).decode("ascii")
        python_cmd = str(call.get("python_cmd") or "python").strip() or "python"

        result = await self._run_box_command(
            context=context,
            command=python_cmd,
            args=["-I", "-c", _PY_REPL_BOOTSTRAP],
            env={"EMBLA_SAFE_REPL_PAYLOAD": payload_b64},
            timeout_seconds=float(timeout_s),
            native_tool_executor=native_tool_executor,
        )

        raw_stdout = str(result.get("stdout") or "")
        raw_stderr = str(result.get("stderr") or "")
        parsed_payload: Dict[str, Any] | None = None
        for line in reversed(raw_stdout.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                maybe = json.loads(line)
            except Exception:
                continue
            if isinstance(maybe, dict) and "ok" in maybe:
                parsed_payload = maybe
                break

        if parsed_payload is None:
            body = native_tool_executor._format_process_result(
                self._as_process_result(result),
                stdout_limit=max_output_chars,
                stderr_limit=3000,
            )
            return f"[sandbox] boxlite\n{body}"

        stdout_limit = max(200, int(max_output_chars * 0.6))
        result_limit = max(200, int(max_output_chars * 0.4))
        payload_stdout = _preview_text(str(parsed_payload.get("stdout") or ""), stdout_limit)
        payload_error = str(parsed_payload.get("error") or "")
        payload_error_type = str(parsed_payload.get("error_type") or "")
        has_result = bool(parsed_payload.get("has_result"))
        result_repr = _preview_text(str(parsed_payload.get("result_repr") or ""), result_limit)
        result_type = str(parsed_payload.get("result_type") or "")
        exit_code = int(result.get("exit_code", 1))

        if parsed_payload.get("ok"):
            result_block = "(result 未设置)"
            if has_result:
                result_block = f"{result_repr}\n(type={result_type})" if result_type else result_repr
            stderr_preview = _preview_text(raw_stderr, 2000)
            return (
                f"[sandbox] boxlite\n"
                f"[exit_code] {exit_code}\n"
                f"[stdout]\n{payload_stdout if payload_stdout else '(empty)'}\n"
                f"[result]\n{result_block}\n"
                f"[stderr]\n{stderr_preview if stderr_preview else '(empty)'}"
            )

        stderr_preview = _preview_text(raw_stderr, 3000)
        error_text = f"{payload_error_type}: {payload_error}" if payload_error_type else payload_error
        return (
            f"[sandbox] boxlite\n"
            f"[exit_code] {exit_code}\n"
            f"[error]\n{error_text if error_text else '(unknown error)'}\n"
            f"[stdout]\n{payload_stdout if payload_stdout else '(empty)'}\n"
            f"[stderr]\n{stderr_preview if stderr_preview else '(empty)'}"
        )

    async def _sleep_and_watch(self, call: Dict[str, Any], *, context, native_tool_executor) -> str:
        log_file = str(call.get("log_file") or call.get("path") or "").strip()
        if not log_file:
            raise ValueError("sleep_and_watch missing log_file/path")

        pattern = str(call.get("pattern") or call.get("regex") or "").strip()
        if not pattern:
            raise ValueError("sleep_and_watch missing pattern/regex")

        timeout_seconds = _safe_int(call.get("timeout_seconds"), 600, 1, 86400)
        try:
            poll_interval_seconds = float(call.get("poll_interval_seconds") or 0.5)
        except Exception:
            poll_interval_seconds = 0.5
        poll_interval_seconds = max(0.05, min(5.0, poll_interval_seconds))
        from_end = bool(call.get("from_end", True))
        max_line_chars = _safe_int(call.get("max_line_chars"), 4000, 64, 20000)

        py = (
            "import asyncio, json\n"
            "from pathlib import Path\n"
            "from system.sleep_watch import wait_for_log_pattern\n"
            "async def _main():\n"
            f"    result = await wait_for_log_pattern(log_file=Path({log_file!r}), pattern={pattern!r}, timeout_seconds={timeout_seconds}, poll_interval_seconds={poll_interval_seconds!r}, from_end={from_end!r}, max_line_chars={max_line_chars})\n"
            "    print(json.dumps({\n"
            "        'watch_id': result.watch_id,\n"
            "        'matched': result.matched,\n"
            "        'reason': result.reason,\n"
            "        'matched_line': result.matched_line,\n"
            "        'elapsed_seconds': result.elapsed_seconds,\n"
            "    }, ensure_ascii=False))\n"
            "asyncio.run(_main())\n"
        )
        result = await self._run_box_command(
            context=context,
            command="python",
            args=["-c", py],
            timeout_seconds=float(timeout_seconds + 5),
            native_tool_executor=native_tool_executor,
        )
        if int(result.get("exit_code", 1)) != 0:
            raise RuntimeError(result.get("stderr") or result.get("stdout") or "sleep_and_watch failed")

        parsed = None
        for line in reversed(str(result.get("stdout") or "").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                maybe = json.loads(line)
            except Exception:
                continue
            if isinstance(maybe, dict) and "watch_id" in maybe:
                parsed = maybe
                break
        if parsed is None:
            raise RuntimeError("sleep_and_watch failed: missing structured result")

        lines = [
            f"[watch_id] {parsed.get('watch_id') or ''}",
            f"[matched] {bool(parsed.get('matched', False))}",
            f"[reason] {parsed.get('reason') or ''}",
            f"[elapsed_seconds] {float(parsed.get('elapsed_seconds') or 0.0):.3f}",
        ]
        matched_line = str(parsed.get("matched_line") or "")
        if matched_line:
            lines.append(f"[matched_line] {matched_line}")
        return "\n".join(lines)

    async def _run_git_tool(self, tool_name: str, call: Dict[str, Any], *, native_tool_executor, context) -> str:
        git_working_dir = str(call.get("cwd") or call.get("repo_path") or context.execution_root or "/workspace").strip() or str(context.execution_root or "/workspace")
        if tool_name == "git_status":
            porcelain = bool(call.get("porcelain", False))
            include_untracked = bool(call.get("include_untracked", True))
            short = bool(call.get("short", True))
            branch = bool(call.get("branch", True))
            args = ["status", "--porcelain=v1"] if porcelain else ["status"]
            if not porcelain:
                if short:
                    args.append("--short")
                if branch:
                    args.append("--branch")
            if not include_untracked:
                args.append("--untracked-files=no")
            stdout_limit, stderr_limit = native_tool_executor._resolve_output_limits(call, default_stdout=10000, default_stderr=3000)
            result = await self._run_box_command(context=context, command="git", args=args, timeout_seconds=90, native_tool_executor=native_tool_executor, working_dir=git_working_dir)
            if self._box_command_not_found(result, "git"):
                return await self._delegate_to_native_tool(tool_name, call, context=context, native_tool_executor=native_tool_executor)
            return native_tool_executor._format_process_result(self._as_process_result(result), stdout_limit=stdout_limit, stderr_limit=stderr_limit)

        if tool_name == "git_diff":
            name_only = bool(call.get("name_only", False))
            stat = bool(call.get("stat", False))
            cached = bool(call.get("cached", False) or call.get("staged", False))
            unified = _safe_int(call.get("unified"), 3, 0, 20)
            ref = str(call.get("ref") or "").strip()
            base_ref = str(call.get("base_ref") or "").strip()
            target_path = str(call.get("target_path") or call.get("pathspec") or "").strip()
            args = ["diff"]
            args.append("--name-only" if name_only else f"--unified={unified}")
            if stat:
                args.append("--stat")
            if cached:
                args.append("--cached")
            if base_ref and ref:
                args.extend([base_ref, ref])
            elif ref:
                args.append(ref)
            if target_path:
                args.extend(["--", target_path])
            stdout_limit, stderr_limit = native_tool_executor._resolve_output_limits(call, default_stdout=24000, default_stderr=4000)
            result = await self._run_box_command(context=context, command="git", args=args, timeout_seconds=120, native_tool_executor=native_tool_executor, working_dir=git_working_dir)
            if self._box_command_not_found(result, "git"):
                return await self._delegate_to_native_tool(tool_name, call, context=context, native_tool_executor=native_tool_executor)
            return native_tool_executor._format_process_result(self._as_process_result(result), stdout_limit=stdout_limit, stderr_limit=stderr_limit)

        if tool_name == "git_log":
            max_count = max(1, min(200, int(call.get("max_count") or 20)))
            oneline = bool(call.get("oneline", True))
            pretty = str(call.get("pretty") or "").strip()
            since = str(call.get("since") or "").strip()
            ref = str(call.get("ref") or "").strip()
            target_path = str(call.get("target_path") or call.get("pathspec") or "").strip()
            args = ["log", f"--max-count={max_count}", "--decorate"]
            if oneline:
                args.append("--oneline")
            elif pretty:
                args.append(f"--pretty={pretty}")
            if since:
                args.append(f"--since={since}")
            if ref:
                args.append(ref)
            if target_path:
                args.extend(["--", target_path])
            stdout_limit, stderr_limit = native_tool_executor._resolve_output_limits(call, default_stdout=12000, default_stderr=3000)
            result = await self._run_box_command(context=context, command="git", args=args, timeout_seconds=120, native_tool_executor=native_tool_executor, working_dir=git_working_dir)
            if self._box_command_not_found(result, "git"):
                return await self._delegate_to_native_tool(tool_name, call, context=context, native_tool_executor=native_tool_executor)
            return native_tool_executor._format_process_result(self._as_process_result(result), stdout_limit=stdout_limit, stderr_limit=stderr_limit)

        if tool_name == "git_show":
            ref = str(call.get("ref") or "HEAD").strip()
            stat_only = bool(call.get("stat_only", False))
            name_only = bool(call.get("name_only", False))
            target_path = str(call.get("target_path") or call.get("pathspec") or "").strip()
            args = ["show"]
            if stat_only:
                args.extend(["--stat", "--oneline"])
            elif name_only:
                args.extend(["--name-only", "--oneline"])
            args.append(ref)
            if target_path:
                args.extend(["--", target_path])
            stdout_limit, stderr_limit = native_tool_executor._resolve_output_limits(call, default_stdout=18000, default_stderr=3000)
            result = await self._run_box_command(context=context, command="git", args=args, timeout_seconds=120, native_tool_executor=native_tool_executor, working_dir=git_working_dir)
            if self._box_command_not_found(result, "git"):
                return await self._delegate_to_native_tool(tool_name, call, context=context, native_tool_executor=native_tool_executor)
            return native_tool_executor._format_process_result(self._as_process_result(result), stdout_limit=stdout_limit, stderr_limit=stderr_limit)

        if tool_name == "git_blame":
            target_path = str(call.get("target_path") or call.get("path") or call.get("file_path") or "").strip()
            if not target_path:
                raise ValueError("git_blame 缺少 target_path/path")
            ref = str(call.get("ref") or "HEAD").strip()
            max_lines = _safe_int(call.get("max_lines"), 200, 1, 5000)
            start_line = call.get("start_line")
            end_line = call.get("end_line")
            _, stderr_limit = native_tool_executor._resolve_output_limits(call, default_stdout=10000, default_stderr=3000)
            args = ["blame", "--date=short"]
            if start_line is not None or end_line is not None:
                s = _safe_int(start_line, 1, 1, 1_000_000_000)
                e_default = s + min(max_lines - 1, 199)
                e = _safe_int(end_line, e_default, s, min(1_000_000_000, s + 10_000))
                if e - s + 1 > max_lines:
                    e = s + max_lines - 1
                args.extend(["-L", f"{s},{e}"])
            if ref:
                args.append(ref)
            args.extend(["--", target_path])
            result = await self._run_box_command(context=context, command="git", args=args, timeout_seconds=120, native_tool_executor=native_tool_executor, working_dir=git_working_dir)
            if self._box_command_not_found(result, "git"):
                return await self._delegate_to_native_tool(tool_name, call, context=context, native_tool_executor=native_tool_executor)
            if int(result["exit_code"]) != 0:
                return native_tool_executor._format_process_result(self._as_process_result(result), stdout_limit=18000, stderr_limit=stderr_limit)
            clipped = _preview_lines(str(result.get("stdout") or ""), max_lines)
            stderr_preview = _preview_text(str(result.get("stderr") or ""), stderr_limit)
            return (
                f"[exit_code] {int(result['exit_code'])}\n"
                f"[stdout]\n{clipped if clipped else '(empty)'}\n"
                f"[stderr]\n{stderr_preview if stderr_preview else '(empty)'}"
            )

        if tool_name == "git_grep":
            pattern = str(call.get("pattern") or call.get("keyword") or call.get("query") or "").strip()
            if not pattern:
                raise ValueError("git_grep 缺少 pattern/keyword/query")
            case_sensitive = bool(call.get("case_sensitive", False))
            use_regex = bool(call.get("use_regex", False))
            max_results = max(1, min(10000, int(call.get("max_results") or 200)))
            ref = str(call.get("ref") or "").strip()
            target_path = str(call.get("target_path") or call.get("pathspec") or "").strip()
            args = ["grep", "-n", "--full-name"]
            if not case_sensitive:
                args.append("-i")
            if not use_regex:
                args.append("-F")
            args.extend(["-e", pattern])
            if ref:
                args.append(ref)
            if target_path:
                args.extend(["--", target_path])
            result = await self._run_box_command(context=context, command="git", args=args, timeout_seconds=120, native_tool_executor=native_tool_executor, working_dir=git_working_dir)
            if self._box_command_not_found(result, "git"):
                return await self._delegate_to_native_tool(tool_name, call, context=context, native_tool_executor=native_tool_executor)
            if int(result["exit_code"]) == 1 and not str(result["stdout"] or "").strip():
                return f"No matches for: {pattern}"
            if int(result["exit_code"]) != 0:
                _, stderr_limit = native_tool_executor._resolve_output_limits(call, default_stdout=12000, default_stderr=3000)
                return native_tool_executor._format_process_result(self._as_process_result(result), stdout_limit=18000, stderr_limit=stderr_limit)
            clipped = _preview_lines(str(result.get("stdout") or ""), max_results)
            stderr_preview = _preview_text(str(result.get("stderr") or ""), 3000)
            return (
                f"[exit_code] {result['exit_code']}\n"
                f"[stdout]\n{clipped if clipped else '(empty)'}\n"
                f"[stderr]\n{stderr_preview if stderr_preview else '(empty)'}"
            )

        if tool_name == "git_changed_files":
            max_results = max(1, min(5000, int(call.get("max_results") or 300)))
            result = await self._run_box_command(context=context, command="git", args=["status", "--porcelain=v1"], timeout_seconds=90, native_tool_executor=native_tool_executor, working_dir=git_working_dir)
            if self._box_command_not_found(result, "git"):
                return await self._delegate_to_native_tool(tool_name, call, context=context, native_tool_executor=native_tool_executor)
            if int(result["exit_code"]) != 0:
                stdout_limit, stderr_limit = native_tool_executor._resolve_output_limits(call, default_stdout=12000, default_stderr=3000)
                return native_tool_executor._format_process_result(self._as_process_result(result), stdout_limit=stdout_limit, stderr_limit=stderr_limit)
            lines = [line.rstrip() for line in str(result["stdout"] or "").splitlines() if line.strip()]
            if not lines:
                return "工作区干净，无改动文件"
            changed: List[str] = []
            for line in lines[:max_results]:
                status = line[:2].strip() or "??"
                path = line[3:].strip() if len(line) > 3 else line.strip()
                changed.append(f"{status:>2} {path}")
            if len(lines) > max_results:
                changed.append(f"...(truncated, total={len(lines)} files)")
            return "\n".join(changed)

        if tool_name == "git_checkout_file":
            target_path = str(call.get("target_path") or call.get("path") or call.get("file_path") or "").strip()
            if not target_path:
                raise ValueError("git_checkout_file 缺少 target_path/path")
            if not bool(call.get("confirm", False)):
                raise ValueError("git_checkout_file 是破坏性操作，需要设置 confirm=true")
            ref = str(call.get("ref") or "HEAD").strip()
            staged = bool(call.get("staged", False))
            worktree = bool(call.get("worktree", True))
            if not staged and not worktree:
                raise ValueError("git_checkout_file 至少需要 staged 或 worktree 之一为 true")
            args = ["restore", "--source", ref]
            if staged:
                args.append("--staged")
            if worktree:
                args.append("--worktree")
            args.extend(["--", target_path])
            result = await self._run_box_command(context=context, command="git", args=args, timeout_seconds=120, native_tool_executor=native_tool_executor, working_dir=git_working_dir)
            if self._box_command_not_found(result, "git"):
                return await self._delegate_to_native_tool(tool_name, call, context=context, native_tool_executor=native_tool_executor)
            stdout_limit, stderr_limit = native_tool_executor._resolve_output_limits(call, default_stdout=12000, default_stderr=3000)
            body = native_tool_executor._format_process_result(self._as_process_result(result), stdout_limit=stdout_limit, stderr_limit=stderr_limit)
            if int(result["exit_code"]) == 0:
                return f"已从 {ref} 恢复文件: {target_path}\n{body}"
            return body

        raise ExecutionBackendUnavailableError(f"boxlite git tool not implemented: {tool_name}")

    async def _run_guest_helper(
        self,
        helper_name: str,
        helper_args: list[str],
        *,
        context,
        native_tool_executor,
        timeout_seconds: float,
        env: Dict[str, str] | None = None,
    ) -> str:
        result = await self._run_box_command(
            context=context,
            command="python",
            args=["-m", "system.boxlite.guest_tools", helper_name, *helper_args],
            env=env,
            timeout_seconds=timeout_seconds,
            native_tool_executor=native_tool_executor,
        )
        if int(result.get("exit_code", 1)) != 0:
            raise RuntimeError(result.get("stderr") or result.get("stdout") or f"{helper_name} failed")
        return str(result.get("stdout") or "").strip()

    async def execute_tool(self, tool_name: str, call: Dict[str, Any], *, context, native_tool_executor) -> str:
        host_bridge_tools = {"artifact_reader", "killswitch_plan"}
        if tool_name in host_bridge_tools:
            return await self._delegate_to_native_tool(tool_name, call, context=context, native_tool_executor=native_tool_executor)

        status = probe_boxlite_runtime()
        if not status.available:
            raise ExecutionBackendUnavailableError(status.reason or "boxlite runtime unavailable")

        if tool_name.startswith("git_"):
            return await self._run_git_tool(tool_name, call, native_tool_executor=native_tool_executor, context=context)

        if tool_name == "query_docs":
            query = str(call.get("query") or call.get("keyword") or "").strip()
            if not query:
                raise ValueError("query_docs 缺少 query/keyword")
            return await self._run_guest_helper(
                "query_docs",
                [
                    "--root", str(context.execution_root or "/workspace"),
                    "--query", query,
                    "--max-results", str(_safe_int(call.get("max_results"), 30, 1, 200)),
                    "--max-file-size-kb", str(_safe_int(call.get("max_file_size_kb"), 768, 64, 2048)),
                ],
                context=context,
                native_tool_executor=native_tool_executor,
                timeout_seconds=60,
            )

        if tool_name == "file_ast_skeleton":
            path = str(call.get("path") or call.get("file_path") or "").strip()
            if not path:
                raise ValueError("file_ast_skeleton 缺少 path")
            return await self._run_guest_helper(
                "file_ast_skeleton",
                [
                    "--path", path,
                    "--max-results", str(_safe_int(call.get("max_results"), 300, 20, 5000)),
                ],
                context=context,
                native_tool_executor=native_tool_executor,
                timeout_seconds=60,
            )

        if tool_name == "file_ast_chunk_read":
            path = str(call.get("path") or call.get("file_path") or "").strip()
            if not path:
                raise ValueError("file_ast_chunk_read 缺少 path")
            start_line = _safe_int(call.get("start_line"), 1, 1, 1_000_000)
            end_default = max(start_line, start_line + 120)
            end_line = _safe_int(call.get("end_line"), end_default, start_line, 1_000_000)
            return await self._run_guest_helper(
                "file_ast_chunk_read",
                [
                    "--path", path,
                    "--start-line", str(start_line),
                    "--end-line", str(end_line),
                    "--context-before", str(_safe_int(call.get("context_before"), 3, 0, 200)),
                    "--context-after", str(_safe_int(call.get("context_after"), 3, 0, 200)),
                ],
                context=context,
                native_tool_executor=native_tool_executor,
                timeout_seconds=60,
            )

        if tool_name == "workspace_txn_apply":
            payload = base64.b64encode(json.dumps(call, ensure_ascii=False).encode("utf-8")).decode("ascii")
            return await self._run_guest_helper(
                "workspace_txn_apply",
                [],
                context=context,
                native_tool_executor=native_tool_executor,
                timeout_seconds=120,
                env={"EMBLA_WORKSPACE_TXN_PAYLOAD": payload},
            )

        if tool_name == "get_cwd":
            return str(call.get("cwd") or context.execution_root or "/workspace").replace("\\", "/")

        if tool_name == "run_cmd":
            command = str(call.get("command") or call.get("cmd") or "").strip()
            if not command:
                raise ValueError("run_cmd 缺少 command")
            timeout_seconds = float(call.get("timeout_seconds") or 120)
            working_dir = str(call.get("cwd") or context.execution_root or "/workspace").strip() or str(context.execution_root or "/workspace")
            result = await self._run_box_command(
                context=context,
                command="bash",
                args=["-lc", command],
                timeout_seconds=timeout_seconds,
                native_tool_executor=native_tool_executor,
                working_dir=working_dir,
            )
            if self._box_command_not_found(result, "bash"):
                result = await self._run_box_command(
                    context=context,
                    command="sh",
                    args=["-lc", command],
                    timeout_seconds=timeout_seconds,
                    native_tool_executor=native_tool_executor,
                    working_dir=working_dir,
                )
            stdout_limit, stderr_limit = native_tool_executor._resolve_output_limits(call, default_stdout=6000, default_stderr=3000)
            return native_tool_executor._format_process_result(self._as_process_result(result), stdout_limit=stdout_limit, stderr_limit=stderr_limit)

        if tool_name == "python_repl":
            return await self._python_repl(call, context=context, native_tool_executor=native_tool_executor)

        if tool_name == "sleep_and_watch":
            return await self._sleep_and_watch(call, context=context, native_tool_executor=native_tool_executor)

        if tool_name == "read_file":
            path = str(call.get("path") or call.get("file_path") or "").strip()
            if not path:
                raise ValueError("read_file 缺少 path")
            result = await self._run_box_command(
                context=context,
                command="cat",
                args=[path],
                timeout_seconds=30,
                native_tool_executor=native_tool_executor,
            )
            if int(result["exit_code"]) != 0:
                raise RuntimeError(result["stderr"] or result["stdout"] or f"failed to read file: {path}")
            content = str(result["stdout"] or "")
            start_line = call.get("start_line")
            end_line = call.get("end_line")
            max_chars = int(call.get("max_chars") or 6000)
            if start_line is not None or end_line is not None:
                lines = content.splitlines()
                s = max(1, int(start_line or 1))
                e = min(len(lines) if lines else s, int(end_line or min(s + 200, len(lines) if lines else s)))
                selected = lines[s - 1 : e]
                content = "\n".join(f"{idx + s:4}: {line}" for idx, line in enumerate(selected))
            return content[:max_chars] if len(content) > max_chars else content

        if tool_name == "write_file":
            path = str(call.get("path") or call.get("file_path") or "").strip()
            if not path:
                raise ValueError("write_file 缺少 path")
            content = call.get("content")
            if content is None:
                raise ValueError("write_file 缺少 content")
            mode = str(call.get("mode") or "overwrite").strip().lower()
            encoding = str(call.get("encoding") or "utf-8")
            content_text = str(content)
            safe_path = self._resolve_host_safe_path(path, context=context, native_tool_executor=native_tool_executor, kind="file")
            guard = TestBaselineGuard()
            allowed, reason = guard.check_modification_allowed(safe_path, requester=self._resolve_requester(call, context=context))
            if not allowed:
                raise NativeSecurityError(reason)

            write_text = content_text
            if mode == "append":
                existing = ""
                try:
                    existing = native_tool_executor.executor.read_text(safe_path)
                except FileNotFoundError:
                    existing = ""
                if existing and not existing.endswith("\n"):
                    existing += "\n"
                write_text = existing + content_text

            native_tool_executor._validate_test_poisoning(safe_path, write_text)
            python_payload = (
                "from pathlib import Path; "
                f"p=Path({path!r}); "
                "p.parent.mkdir(parents=True, exist_ok=True); "
                f"p.write_text({write_text!r}, encoding={encoding!r})"
            )
            result = await self._run_box_command(
                context=context,
                command="python",
                args=["-c", python_payload],
                timeout_seconds=30,
                native_tool_executor=native_tool_executor,
            )
            if int(result["exit_code"]) != 0:
                raise RuntimeError(result["stderr"] or result["stdout"] or f"failed to write file: {path}")
            return f"已写入文件: {path} (mode={mode}, chars={len(content_text)})"

        if tool_name == "search_keyword":
            keyword = str(call.get("keyword") or call.get("query") or "").strip()
            if not keyword:
                raise ValueError("search_keyword 缺少 keyword/query")
            search_path = str(call.get("search_path") or context.execution_root or "/workspace").strip() or str(context.execution_root or "/workspace")
            include_glob = str(call.get("glob") or "").strip()
            case_sensitive = bool(call.get("case_sensitive", False))
            use_regex = bool(call.get("use_regex", False))
            max_results = max(1, min(200, int(call.get("max_results") or 50)))
            max_file_size = _safe_int(call.get("max_file_size_kb"), 512, 64, 2048) * 1024
            flags_line = "flags = 0\n" if case_sensitive else "flags = re.IGNORECASE\n"
            pattern_expr = f"pattern_text" if use_regex else f"re.escape({keyword!r})"
            py = (
                "from pathlib import Path\n"
                "import re\n"
                f"base = Path({search_path!r})\n"
                f"pattern_text = {keyword!r}\n"
                f"include_glob = {include_glob!r}\n"
                f"max_results = {max_results}\n"
                f"max_file_size = {max_file_size}\n"
                + flags_line
                + f"pat = re.compile({pattern_expr}, flags=flags)\n"
                + "out = []\n"
                + "ignore = {'.git', '.venv', '__pycache__', 'node_modules', 'dist', 'release', 'logs'}\n"
                + "for p in base.rglob('*'):\n"
                + "    if any(part in ignore for part in p.parts):\n"
                + "        continue\n"
                + "    if not p.is_file():\n"
                + "        continue\n"
                + "    if include_glob and not Path(p.name).match(include_glob):\n"
                + "        continue\n"
                + "    try:\n"
                + "        if p.stat().st_size > max_file_size:\n"
                + "            continue\n"
                + "        text = p.read_text(encoding='utf-8', errors='ignore')\n"
                + "    except Exception:\n"
                + "        continue\n"
                + "    rel = p.relative_to(base)\n"
                + "    for idx, line in enumerate(text.splitlines(), start=1):\n"
                + "        if pat.search(line):\n"
                + "            out.append(f'{rel}:{idx}:{line.strip()}')\n"
                + "            if len(out) >= max_results:\n"
                + "                print('\\n'.join(out))\n"
                + "                raise SystemExit(0)\n"
                + "print('\\n'.join(out))\n"
            )
            result = await self._run_box_command(
                context=context,
                command="python",
                args=["-c", py],
                timeout_seconds=60,
                native_tool_executor=native_tool_executor,
            )
            if int(result["exit_code"]) != 0:
                raise RuntimeError(result["stderr"] or result["stdout"] or "search failed")
            body = str(result["stdout"] or "").strip()
            return body or f"未找到关键字: {keyword}"

        if tool_name == "list_files":
            path = str(call.get("path") or context.execution_root or "/workspace").strip()
            py = (
                "from pathlib import Path\n"
                f"base = Path({path!r})\n"
                "items = []\n"
                "for child in sorted(base.iterdir(), key=lambda p: p.name):\n"
                "    suffix = '/' if child.is_dir() else ''\n"
                "    items.append(child.name + suffix)\n"
                "print('\\n'.join(items))\n"
            )
            result = await self._run_box_command(
                context=context,
                command="python",
                args=["-c", py],
                timeout_seconds=30,
                native_tool_executor=native_tool_executor,
            )
            if int(result["exit_code"]) != 0:
                raise RuntimeError(result["stderr"] or result["stdout"] or "list_files failed")
            body = str(result["stdout"] or "").strip()
            return body or f"目录为空: {path}"

        raise ExecutionBackendUnavailableError(f"boxlite backend for tool not implemented yet: {tool_name}")
