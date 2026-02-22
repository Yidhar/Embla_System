#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Native local tools for agentic loop.

Goal:
- Handle basic local tasks inside NagaAgent directly.
- Execute native local tools only.
"""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from system.native_executor import CommandResult, NativeExecutor, NativeSecurityError


_DEFAULT_PREVIEW_CHARS = 6000
_PY_REPL_BOOTSTRAP = (
    "import os,base64;"
    "src=base64.b64decode(os.environ.get('NAGA_SAFE_REPL_PAYLOAD','')).decode('utf-8');"
    "exec(compile(src,'<naga_safe_repl_payload>','exec'),{'__name__':'__main__'})"
)
_SAFE_PY_BUILTINS = [
    "abs",
    "all",
    "any",
    "bool",
    "complex",
    "dict",
    "enumerate",
    "Exception",
    "filter",
    "float",
    "int",
    "isinstance",
    "len",
    "list",
    "map",
    "max",
    "min",
    "pow",
    "print",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "slice",
    "sorted",
    "str",
    "sum",
    "tuple",
    "TypeError",
    "ValueError",
    "zip",
    "ZeroDivisionError",
]
_BLOCKED_PY_NAMES = [
    "__import__",
    "eval",
    "exec",
    "open",
    "input",
    "compile",
    "globals",
    "locals",
    "vars",
    "dir",
    "getattr",
    "setattr",
    "delattr",
    "help",
    "breakpoint",
    "builtins",
    "os",
    "sys",
    "subprocess",
    "socket",
    "shutil",
    "pathlib",
    "ctypes",
    "importlib",
]
_SAFE_PY_MODULES = [
    "math",
    "statistics",
    "decimal",
    "fractions",
    "itertools",
    "collections",
    "functools",
    "random",
    "json",
    "csv",
]


def _preview_text(text: str, limit: int = _DEFAULT_PREVIEW_CHARS) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...(truncated, total={len(text)} chars)"


def _preview_lines(text: str, max_lines: int) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    head = lines[:max_lines]
    head.append(f"...(truncated, total={len(lines)} lines)")
    return "\n".join(head)


def _safe_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        num = int(value)
    except Exception:
        return default
    return max(min_value, min(max_value, num))


def _extract_quoted_segments(text: str) -> List[str]:
    if not text:
        return []
    segments: List[str] = []
    for m in re.finditer(r"'([^']+)'|\"([^\"]+)\"|`([^`]+)`", text):
        seg = next((g for g in m.groups() if g), "")
        if seg:
            segments.append(seg.strip())
    return segments


def _looks_like_path(value: str) -> bool:
    if not value:
        return False
    v = value.strip().replace("\\", "/")
    if "/" in v:
        return True
    if "." in Path(v).name:
        return True
    return False


def _extract_path_candidates(text: str) -> List[str]:
    if not text:
        return []

    candidates: List[str] = []
    quoted = _extract_quoted_segments(text)
    for seg in quoted:
        if _looks_like_path(seg):
            candidates.append(seg)

    # Fallback for unquoted common repo-relative path tokens.
    for token in re.findall(r"[A-Za-z0-9_\-./\\]+\.[A-Za-z0-9_]+", text):
        if _looks_like_path(token):
            candidates.append(token)

    # Preserve order while deduplicating.
    seen = set()
    out: List[str] = []
    for item in candidates:
        key = item.strip()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _extract_first_keyword(text: str) -> Optional[str]:
    for seg in _extract_quoted_segments(text):
        if len(seg) >= 2 and not _looks_like_path(seg):
            return seg

    # Fallback: after common keyword markers.
    patterns = [
        r"关键词[:：]\s*([^\s,，。]+)",
        r"搜索[:：]\s*([^\s,，。]+)",
        r"查找[:：]\s*([^\s,，。]+)",
    ]
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _extract_command_candidate(text: str) -> Optional[str]:
    quoted = _extract_quoted_segments(text)
    for seg in quoted:
        if seg and not _looks_like_path(seg):
            return seg

    patterns = [
        r"(?:run command|execute command|执行命令|运行命令|终端执行|cmd[:：]?|shell[:：]?|powershell[:：]?)\s+(.+)$",
    ]
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            cmd = m.group(1).strip()
            if cmd:
                return cmd
    return None


def _build_safe_python_payload(user_code: str) -> str:
    """Build restricted python runner payload executed by a separate interpreter process."""
    return f"""
import ast
import builtins
import collections
import contextlib
import csv
import decimal
import fractions
import functools
import io
import itertools
import json
import math
import random
import statistics

USER_CODE = {user_code!r}
SAFE_BUILTIN_NAMES = {_SAFE_PY_BUILTINS!r}
BLOCKED_NAMES = set({_BLOCKED_PY_NAMES!r})

def _validate(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ValueError("import 语句不允许，请使用预置模块")
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            raise ValueError("global/nonlocal 不允许")
        if isinstance(node, ast.Attribute):
            attr = str(getattr(node, "attr", ""))
            if attr.startswith("__"):
                raise ValueError("不允许访问 dunder 属性")
        if isinstance(node, ast.Name):
            name = str(node.id)
            if name.startswith("__") or name in BLOCKED_NAMES:
                raise ValueError(f"检测到受限名称: {{name}}")
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in BLOCKED_NAMES:
                raise ValueError(f"检测到受限调用: {{fn.id}}")

stdout_buf = io.StringIO()
try:
    tree = ast.parse(USER_CODE, mode="exec")
    _validate(tree)
    safe_builtins = {{n: getattr(builtins, n) for n in SAFE_BUILTIN_NAMES if hasattr(builtins, n)}}
    safe_globals = {{
        "__builtins__": safe_builtins,
        "math": math,
        "statistics": statistics,
        "decimal": decimal,
        "fractions": fractions,
        "itertools": itertools,
        "collections": collections,
        "functools": functools,
        "random": random,
        "json": json,
        "csv": csv,
    }}
    safe_locals = {{}}
    with contextlib.redirect_stdout(stdout_buf):
        exec(compile(tree, "<safe_python_repl>", "exec"), safe_globals, safe_locals)

    has_result = ("result" in safe_locals) or ("result" in safe_globals)
    result_obj = safe_locals.get("result", safe_globals.get("result"))
    payload = {{
        "ok": True,
        "stdout": stdout_buf.getvalue(),
        "has_result": has_result,
        "result_repr": repr(result_obj) if has_result else "",
        "result_type": type(result_obj).__name__ if has_result else "",
    }}
    print(json.dumps(payload, ensure_ascii=False))
except Exception as exc:
    payload = {{
        "ok": False,
        "stdout": stdout_buf.getvalue(),
        "error_type": type(exc).__name__,
        "error": str(exc),
    }}
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(1)
""".strip()


class NativeToolExecutor:
    """Local-first tool execution with safe project-root confinement."""

    def __init__(self) -> None:
        self.executor = NativeExecutor()
        self.project_root = self.executor.base_dir
        self._doc_roots = [
            "doc",
            "docs",
            "README.md",
            "README_en.md",
        ]

    async def execute(self, call: Dict[str, Any], session_id: str) -> Dict[str, Any]:
        tool_name = (call.get("tool_name") or call.get("tool") or "").strip().lower()
        if not tool_name:
            return self._error(call, "native工具缺少 tool_name")

        aliases = {
            "read": "read_file",
            "readfile": "read_file",
            "write": "write_file",
            "writefile": "write_file",
            "pwd": "get_cwd",
            "cwd": "get_cwd",
            "cmd": "run_cmd",
            "command": "run_cmd",
            "search": "search_keyword",
            "grep": "search_keyword",
            "doc_search": "query_docs",
            "docs_query": "query_docs",
            "ls": "list_files",
            "gitstatus": "git_status",
            "gitdiff": "git_diff",
            "gitlog": "git_log",
            "gitshow": "git_show",
            "gitblame": "git_blame",
            "gitgrep": "git_grep",
            "changed_files": "git_changed_files",
            "restore_file": "git_checkout_file",
            "checkout_file": "git_checkout_file",
            "py": "python_repl",
            "python": "python_repl",
            "python_exec": "python_repl",
            "repl": "python_repl",
        }
        tool_name = aliases.get(tool_name, tool_name)

        try:
            if tool_name == "read_file":
                result = await self._read_file(call)
            elif tool_name == "write_file":
                result = await self._write_file(call)
            elif tool_name == "get_cwd":
                result = await self._get_cwd(call)
            elif tool_name == "run_cmd":
                result = await self._run_cmd(call)
            elif tool_name == "search_keyword":
                result = await self._search_keyword(call)
            elif tool_name == "query_docs":
                result = await self._query_docs(call)
            elif tool_name == "list_files":
                result = await self._list_files(call)
            elif tool_name == "git_status":
                result = await self._git_status(call)
            elif tool_name == "git_diff":
                result = await self._git_diff(call)
            elif tool_name == "git_log":
                result = await self._git_log(call)
            elif tool_name == "git_show":
                result = await self._git_show(call)
            elif tool_name == "git_blame":
                result = await self._git_blame(call)
            elif tool_name == "git_grep":
                result = await self._git_grep(call)
            elif tool_name == "git_changed_files":
                result = await self._git_changed_files(call)
            elif tool_name == "git_checkout_file":
                result = await self._git_checkout_file(call)
            elif tool_name == "python_repl":
                result = await self._python_repl(call)
            else:
                return self._error(call, f"不支持的native工具: {tool_name}", tool_name=tool_name)

            return {
                "tool_call": call,
                "result": result,
                "status": "success",
                "service_name": "native",
                "tool_name": tool_name,
            }
        except NativeSecurityError as e:
            return self._error(call, f"安全限制: {e}", tool_name=tool_name)
        except Exception as e:
            return self._error(call, f"执行失败: {e}", tool_name=tool_name)

    async def _read_file(self, call: Dict[str, Any]) -> str:
        path = str(call.get("path") or call.get("file_path") or "").strip()
        if not path:
            raise ValueError("read_file 缺少 path")

        content = await self.executor.read_file(path)
        start_line = call.get("start_line")
        end_line = call.get("end_line")
        max_chars = _safe_int(call.get("max_chars"), _DEFAULT_PREVIEW_CHARS, 200, 50000)

        if start_line is not None or end_line is not None:
            lines = content.splitlines()
            s = _safe_int(start_line, 1, 1, len(lines) if lines else 1)
            e = _safe_int(end_line, min(s + 200, len(lines) if lines else 1), s, len(lines) if lines else s)
            selected = lines[s - 1 : e]
            numbered = [f"{idx + s:4}: {line}" for idx, line in enumerate(selected)]
            content = "\n".join(numbered)

        return _preview_text(content, max_chars)

    async def _write_file(self, call: Dict[str, Any]) -> str:
        path = str(call.get("path") or call.get("file_path") or "").strip()
        if not path:
            raise ValueError("write_file 缺少 path")

        content = call.get("content")
        if content is None:
            raise ValueError("write_file 缺少 content")
        content = str(content)

        mode = str(call.get("mode") or "overwrite").strip().lower()
        encoding = str(call.get("encoding") or "utf-8")

        if mode == "append":
            existing = ""
            try:
                existing = await self.executor.read_file(path)
            except FileNotFoundError:
                existing = ""
            if existing and not existing.endswith("\n"):
                existing += "\n"
            merged = existing + content
            await self.executor.write_file(path, merged, encoding=encoding)
        else:
            await self.executor.write_file(path, content, encoding=encoding)

        return f"已写入文件: {path} (mode={mode}, chars={len(content)})"

    async def _get_cwd(self, call: Dict[str, Any]) -> str:
        """Return native sandbox working directory (project root)."""
        return str(self.project_root).replace('\\', '/')


    async def _run_cmd(self, call: Dict[str, Any]) -> str:
        command = str(call.get("command") or call.get("cmd") or "").strip()
        if not command:
            raise ValueError("run_cmd 缺少 command")

        cwd = call.get("cwd")
        timeout_s = _safe_int(call.get("timeout_seconds"), 120, 1, 1200)
        stdout_limit, stderr_limit = self._resolve_output_limits(call, default_stdout=6000, default_stderr=3000)

        result: CommandResult = await self.executor.execute_shell(command, cwd=cwd, timeout_s=timeout_s)
        return self._format_process_result(result, stdout_limit=stdout_limit, stderr_limit=stderr_limit)

    async def _search_keyword(self, call: Dict[str, Any]) -> str:
        keyword = str(call.get("keyword") or call.get("query") or "").strip()
        if not keyword:
            raise ValueError("search_keyword 缺少 keyword/query")

        search_path = str(call.get("search_path") or ".").strip()
        include_glob = str(call.get("glob") or "").strip()
        case_sensitive = bool(call.get("case_sensitive", False))
        max_results = _safe_int(call.get("max_results"), 50, 1, 200)
        max_file_size = _safe_int(call.get("max_file_size_kb"), 512, 64, 2048) * 1024

        base = self.executor._resolve_safe_path(search_path, kind="search_path")
        matches: List[str] = []

        ignore_dirs = {".git", ".venv", "__pycache__", "node_modules", "dist", "release", "logs"}
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.compile(re.escape(keyword), flags=flags)

        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in ignore_dirs]
            for filename in files:
                if include_glob and not Path(filename).match(include_glob):
                    continue
                path = Path(root) / filename
                try:
                    if path.stat().st_size > max_file_size:
                        continue
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                rel = path.relative_to(self.project_root)
                for line_no, line in enumerate(text.splitlines(), start=1):
                    if pattern.search(line):
                        matches.append(f"{rel}:{line_no}: {line.strip()}")
                        if len(matches) >= max_results:
                            break
                if len(matches) >= max_results:
                    break
            if len(matches) >= max_results:
                break

        if not matches:
            return f"未找到关键词: {keyword}"
        return "\n".join(matches)

    async def _query_docs(self, call: Dict[str, Any]) -> str:
        query = str(call.get("query") or call.get("keyword") or "").strip()
        if not query:
            raise ValueError("query_docs 缺少 query/keyword")

        max_results = _safe_int(call.get("max_results"), 30, 1, 200)
        synthetic_call = {
            "keyword": query,
            "search_path": ".",
            "max_results": max_results,
            "max_file_size_kb": call.get("max_file_size_kb", 768),
            "case_sensitive": call.get("case_sensitive", False),
        }
        raw = await self._search_keyword(synthetic_call)
        if raw.startswith("未找到关键词"):
            return raw

        filtered: List[str] = []
        doc_prefixes = tuple(p.lower() for p in self._doc_roots)
        for line in raw.splitlines():
            path_part = line.split(":", 1)[0].replace("\\", "/").lower()
            if path_part.startswith("doc/") or path_part.startswith("docs/"):
                filtered.append(line)
            elif path_part in ("readme.md", "readme_en.md"):
                filtered.append(line)
            elif path_part.endswith("/readme.md"):
                filtered.append(line)
            elif any(path_part.startswith(prefix) for prefix in doc_prefixes):
                filtered.append(line)
            if len(filtered) >= max_results:
                break

        if filtered:
            return "\n".join(filtered)
        return raw

    async def _list_files(self, call: Dict[str, Any]) -> str:
        path = str(call.get("path") or ".").strip()
        recursive = bool(call.get("recursive", False))
        max_results = _safe_int(call.get("max_results"), 200, 1, 1000)
        include_glob = str(call.get("glob") or "").strip()

        base = self.executor._resolve_safe_path(path, kind="list_path")
        if not base.exists():
            raise FileNotFoundError(f"path 不存在: {path}")

        items: List[str] = []
        if base.is_file():
            rel = base.relative_to(self.project_root)
            return str(rel).replace("\\", "/")

        if recursive:
            for root, dirs, files in os.walk(base):
                for d in dirs:
                    p = Path(root) / d
                    rel = p.relative_to(self.project_root)
                    rel_text = str(rel).replace("\\", "/")
                    items.append(f"{rel_text}/")
                    if len(items) >= max_results:
                        break
                if len(items) >= max_results:
                    break
                for f in files:
                    p = Path(root) / f
                    if include_glob and not p.match(include_glob):
                        continue
                    rel = p.relative_to(self.project_root)
                    items.append(str(rel).replace("\\", "/"))
                    if len(items) >= max_results:
                        break
                if len(items) >= max_results:
                    break
        else:
            for child in sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
                if include_glob and not child.match(include_glob):
                    continue
                rel = child.relative_to(self.project_root)
                rel_text = str(rel).replace("\\", "/")
                if child.is_dir():
                    items.append(f"{rel_text}/")
                else:
                    items.append(rel_text)
                if len(items) >= max_results:
                    break

        if not items:
            return f"目录为空: {path}"
        return "\n".join(items)

    @staticmethod
    def _format_process_result(
        result: CommandResult,
        *,
        stdout_limit: int = 8000,
        stderr_limit: int = 3000,
    ) -> str:
        stdout = _preview_text(result.stdout or "", stdout_limit)
        stderr = _preview_text(result.stderr or "", stderr_limit)
        return (
            f"[exit_code] {result.returncode}\n"
            f"[stdout]\n{stdout if stdout else '(empty)'}\n"
            f"[stderr]\n{stderr if stderr else '(empty)'}"
        )

    @staticmethod
    def _resolve_output_limits(
        call: Dict[str, Any],
        *,
        default_stdout: int,
        default_stderr: int = 3000,
    ) -> tuple[int, int]:
        stdout_limit = _safe_int(call.get("max_output_chars"), default_stdout, 200, 500000)
        stderr_limit = min(50000, max(default_stderr, stdout_limit // 4))
        return stdout_limit, stderr_limit

    async def _run_git(self, git_args: List[str], call: Dict[str, Any], *, default_timeout: int = 120) -> CommandResult:
        repo_path = str(call.get("repo_path") or call.get("cwd") or ".").strip()
        timeout_s = _safe_int(call.get("timeout_seconds"), default_timeout, 1, 1200)
        return await self.executor.run(["git", *git_args], cwd=repo_path, timeout_s=timeout_s)

    async def _git_status(self, call: Dict[str, Any]) -> str:
        porcelain = bool(call.get("porcelain", False))
        include_untracked = bool(call.get("include_untracked", True))
        short = bool(call.get("short", True))
        branch = bool(call.get("branch", True))
        stdout_limit, stderr_limit = self._resolve_output_limits(call, default_stdout=10000, default_stderr=3000)

        if porcelain:
            args = ["status", "--porcelain=v1"]
        else:
            args = ["status"]
            if short:
                args.append("--short")
            if branch:
                args.append("--branch")

        if not include_untracked:
            args.append("--untracked-files=no")

        result = await self._run_git(args, call, default_timeout=90)
        return self._format_process_result(result, stdout_limit=stdout_limit, stderr_limit=stderr_limit)

    async def _git_diff(self, call: Dict[str, Any]) -> str:
        name_only = bool(call.get("name_only", False))
        stat = bool(call.get("stat", False))
        cached = bool(call.get("cached", False) or call.get("staged", False))
        unified = _safe_int(call.get("unified"), 3, 0, 20)
        ref = str(call.get("ref") or "").strip()
        base_ref = str(call.get("base_ref") or "").strip()
        target_path = str(call.get("target_path") or call.get("pathspec") or "").strip()
        stdout_limit, stderr_limit = self._resolve_output_limits(call, default_stdout=24000, default_stderr=4000)

        args = ["diff"]
        if name_only:
            args.append("--name-only")
        else:
            args.append(f"--unified={unified}")
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

        result = await self._run_git(args, call, default_timeout=120)
        return self._format_process_result(result, stdout_limit=stdout_limit, stderr_limit=stderr_limit)

    async def _git_log(self, call: Dict[str, Any]) -> str:
        max_count = _safe_int(call.get("max_count"), 20, 1, 200)
        oneline = bool(call.get("oneline", True))
        pretty = str(call.get("pretty") or "").strip()
        since = str(call.get("since") or "").strip()
        ref = str(call.get("ref") or "").strip()
        target_path = str(call.get("target_path") or call.get("pathspec") or "").strip()
        stdout_limit, stderr_limit = self._resolve_output_limits(call, default_stdout=12000, default_stderr=3000)

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

        result = await self._run_git(args, call, default_timeout=120)
        return self._format_process_result(result, stdout_limit=stdout_limit, stderr_limit=stderr_limit)

    async def _git_show(self, call: Dict[str, Any]) -> str:
        ref = str(call.get("ref") or "HEAD").strip()
        stat_only = bool(call.get("stat_only", False))
        name_only = bool(call.get("name_only", False))
        target_path = str(call.get("target_path") or call.get("pathspec") or "").strip()
        stdout_limit, stderr_limit = self._resolve_output_limits(call, default_stdout=18000, default_stderr=3000)

        args = ["show"]
        if stat_only:
            args.extend(["--stat", "--oneline"])
        elif name_only:
            args.extend(["--name-only", "--oneline"])
        args.append(ref)
        if target_path:
            args.extend(["--", target_path])

        result = await self._run_git(args, call, default_timeout=120)
        return self._format_process_result(result, stdout_limit=stdout_limit, stderr_limit=stderr_limit)

    async def _git_blame(self, call: Dict[str, Any]) -> str:
        target_path = str(call.get("target_path") or call.get("path") or call.get("file_path") or "").strip()
        if not target_path:
            raise ValueError("git_blame 缺少 target_path/path")

        ref = str(call.get("ref") or "HEAD").strip()
        max_lines = _safe_int(call.get("max_lines"), 200, 1, 5000)
        start_line = call.get("start_line")
        end_line = call.get("end_line")
        _, stderr_limit = self._resolve_output_limits(call, default_stdout=10000, default_stderr=3000)

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

        result = await self._run_git(args, call, default_timeout=120)
        if result.returncode != 0:
            return self._format_process_result(result, stdout_limit=18000, stderr_limit=stderr_limit)

        clipped = _preview_lines(result.stdout or "", max_lines)
        stderr_preview = _preview_text(result.stderr or "", stderr_limit)
        return (
            f"[exit_code] {result.returncode}\n"
            f"[stdout]\n{clipped if clipped else '(empty)'}\n"
            f"[stderr]\n{stderr_preview if stderr_preview else '(empty)'}"
        )

    async def _git_grep(self, call: Dict[str, Any]) -> str:
        pattern = str(call.get("pattern") or call.get("keyword") or call.get("query") or "").strip()
        if not pattern:
            raise ValueError("git_grep 缺少 pattern/keyword/query")

        case_sensitive = bool(call.get("case_sensitive", False))
        use_regex = bool(call.get("use_regex", False))
        max_results = _safe_int(call.get("max_results"), 200, 1, 10000)
        ref = str(call.get("ref") or "").strip()
        target_path = str(call.get("target_path") or call.get("pathspec") or "").strip()
        _, stderr_limit = self._resolve_output_limits(call, default_stdout=12000, default_stderr=3000)

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

        result = await self._run_git(args, call, default_timeout=120)

        # `git grep` typically returns code 1 when there are no matches.
        if result.returncode == 1 and not (result.stdout or "").strip():
            return f"No matches for: {pattern}"
        if result.returncode != 0:
            return self._format_process_result(result, stdout_limit=18000, stderr_limit=stderr_limit)

        clipped = _preview_lines(result.stdout or "", max_results)
        stderr_preview = _preview_text(result.stderr or "", stderr_limit)
        return (
            f"[exit_code] {result.returncode}\n"
            f"[stdout]\n{clipped if clipped else '(empty)'}\n"
            f"[stderr]\n{stderr_preview if stderr_preview else '(empty)'}"
        )

    async def _git_changed_files(self, call: Dict[str, Any]) -> str:
        max_results = _safe_int(call.get("max_results"), 300, 1, 5000)
        result = await self._run_git(["status", "--porcelain=v1"], call, default_timeout=90)
        if result.returncode != 0:
            stdout_limit, stderr_limit = self._resolve_output_limits(call, default_stdout=12000, default_stderr=3000)
            return self._format_process_result(result, stdout_limit=stdout_limit, stderr_limit=stderr_limit)

        lines = [line.rstrip() for line in (result.stdout or "").splitlines() if line.strip()]
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

    async def _git_checkout_file(self, call: Dict[str, Any]) -> str:
        target_path = str(call.get("target_path") or call.get("path") or call.get("file_path") or "").strip()
        if not target_path:
            raise ValueError("git_checkout_file 缺少 target_path/path")

        # destructive guard: caller must explicitly acknowledge.
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

        result = await self._run_git(args, call, default_timeout=120)
        stdout_limit, stderr_limit = self._resolve_output_limits(call, default_stdout=12000, default_stderr=3000)
        body = self._format_process_result(result, stdout_limit=stdout_limit, stderr_limit=stderr_limit)
        if result.returncode == 0:
            return f"已从 {ref} 恢复文件: {target_path}\n{body}"
        return body

    async def _python_repl(self, call: Dict[str, Any]) -> str:
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
        env = {"NAGA_SAFE_REPL_PAYLOAD": payload_b64}

        if sandbox == "docker":
            docker_image = str(call.get("docker_image") or "python:3.11-alpine").strip()
            if not re.fullmatch(r"[A-Za-z0-9._:/-]+", docker_image):
                raise ValueError("docker_image 格式非法")
            command = [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--cpus",
                "0.50",
                "--memory",
                "256m",
                "--pids-limit",
                "128",
                docker_image,
                "python",
                "-I",
                "-c",
                _PY_REPL_BOOTSTRAP,
            ]
            process = await self.executor.run(command, env=env, timeout_s=timeout_s + 10)
        else:
            python_cmd = str(call.get("python_cmd") or "python").strip()
            if not python_cmd:
                python_cmd = "python"
            process = await self.executor.run(
                [python_cmd, "-I", "-c", _PY_REPL_BOOTSTRAP],
                env=env,
                timeout_s=timeout_s,
            )

        raw_stdout = process.stdout or ""
        raw_stderr = process.stderr or ""

        parsed_payload: Optional[Dict[str, Any]] = None
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
            body = self._format_process_result(process, stdout_limit=max_output_chars, stderr_limit=3000)
            return f"[sandbox] {sandbox}\n{body}"

        stdout_limit = max(200, int(max_output_chars * 0.6))
        result_limit = max(200, int(max_output_chars * 0.4))
        payload_stdout = _preview_text(str(parsed_payload.get("stdout") or ""), stdout_limit)
        payload_error = str(parsed_payload.get("error") or "")
        payload_error_type = str(parsed_payload.get("error_type") or "")
        has_result = bool(parsed_payload.get("has_result"))
        result_repr = _preview_text(str(parsed_payload.get("result_repr") or ""), result_limit)
        result_type = str(parsed_payload.get("result_type") or "")

        if parsed_payload.get("ok"):
            result_block = "(result 未设置)"
            if has_result:
                result_block = f"{result_repr}\n(type={result_type})" if result_type else result_repr
            stderr_preview = _preview_text(raw_stderr, 2000)
            return (
                f"[sandbox] {sandbox}\n"
                f"[exit_code] {process.returncode}\n"
                f"[stdout]\n{payload_stdout if payload_stdout else '(empty)'}\n"
                f"[result]\n{result_block}\n"
                f"[stderr]\n{stderr_preview if stderr_preview else '(empty)'}"
            )

        stderr_preview = _preview_text(raw_stderr, 3000)
        error_text = f"{payload_error_type}: {payload_error}" if payload_error_type else payload_error
        return (
            f"[sandbox] {sandbox}\n"
            f"[exit_code] {process.returncode}\n"
            f"[error]\n{error_text if error_text else '(unknown error)'}\n"
            f"[stdout]\n{payload_stdout if payload_stdout else '(empty)'}\n"
            f"[stderr]\n{stderr_preview if stderr_preview else '(empty)'}"
        )

    @staticmethod
    def _error(call: Dict[str, Any], message: str, *, tool_name: Optional[str] = None) -> Dict[str, Any]:
        return {
            "tool_call": call,
            "result": message,
            "status": "error",
            "service_name": "native",
            "tool_name": tool_name or str(call.get("tool_name") or call.get("tool") or "native"),
        }


_native_tool_executor: Optional[NativeToolExecutor] = None


def get_native_tool_executor() -> NativeToolExecutor:
    global _native_tool_executor
    if _native_tool_executor is None:
        _native_tool_executor = NativeToolExecutor()
    return _native_tool_executor
