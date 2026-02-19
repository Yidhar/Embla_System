#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Native local tools for agentic loop.

Goal:
- Handle basic local tasks inside NagaAgent directly.
- Keep OpenClaw for heavier cross-app/browser/cloud workflows.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from system.native_executor import CommandResult, NativeExecutor, NativeSecurityError


_DEFAULT_PREVIEW_CHARS = 6000


def _preview_text(text: str, limit: int = _DEFAULT_PREVIEW_CHARS) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...(truncated, total={len(text)} chars)"


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
            "agentserver/openclaw/README.md",
        ]

    def maybe_intercept_openclaw_call(self, call: Dict[str, Any], session_id: str) -> Optional[Dict[str, Any]]:
        """Map simple openclaw message tasks to local native tools."""
        if (call.get("agentType") or "").strip() != "openclaw":
            return None

        message = str(call.get("message") or "").strip()
        if not message:
            return None

        lowered = message.lower()

        remote_markers = [
            "http://",
            "https://",
            "网页",
            "浏览器",
            "联网",
            "internet",
            "google",
            "bing",
            "bilibili",
            "open website",
            "web search",
        ]
        if any(marker in lowered for marker in remote_markers):
            return None

        cwd_markers = ["cwd", "当前工作目录", "工作目录", "pwd"]
        if any(marker in lowered for marker in cwd_markers):
            return {
                "agentType": "native",
                "tool_name": "get_cwd",
                "_intercepted_from": "openclaw",
            }

        cmd_markers = [
            "执行命令",
            "运行命令",
            "终端执行",
            "运行指令",
            "run command",
            "execute command",
            "shell",
            "powershell",
            "cmd",
        ]
        if any(marker in lowered for marker in cmd_markers):
            command = _extract_command_candidate(message)
            if command and self.executor.is_safe_command(command):
                return {
                    "agentType": "native",
                    "tool_name": "run_cmd",
                    "command": command,
                    "_intercepted_from": "openclaw",
                }

        read_markers = ["读取文件", "查看文件", "打开文件", "read file", "cat "]
        if any(marker in lowered for marker in read_markers):
            paths = _extract_path_candidates(message)
            if paths:
                return {
                    "agentType": "native",
                    "tool_name": "read_file",
                    "path": paths[0],
                    "_intercepted_from": "openclaw",
                }

        write_markers = ["写入文件", "保存到", "创建文件", "覆盖文件", "append to", "write file"]
        if any(marker in lowered for marker in write_markers):
            paths = _extract_path_candidates(message)
            quoted = _extract_quoted_segments(message)
            content = None
            for seg in quoted:
                if not _looks_like_path(seg):
                    content = seg
                    break
            if paths and content is not None:
                return {
                    "agentType": "native",
                    "tool_name": "write_file",
                    "path": paths[0],
                    "content": content,
                    "mode": "overwrite",
                    "_intercepted_from": "openclaw",
                }

        search_markers = [
            "关键词",
            "关键字",
            "搜索",
            "查找",
            "grep",
            "rg ",
            "search keyword",
            "keyword search",
            "find keyword",
        ]
        if any(marker in lowered for marker in search_markers):
            keyword = _extract_first_keyword(message)
            if keyword:
                return {
                    "agentType": "native",
                    "tool_name": "search_keyword",
                    "keyword": keyword,
                    "search_path": ".",
                    "_intercepted_from": "openclaw",
                }

        doc_markers = ["文档查询", "查阅文档", "在文档中", "readme", "docs", "doc/"]
        if any(marker in lowered for marker in doc_markers):
            query = _extract_first_keyword(message) or message
            return {
                "agentType": "native",
                "tool_name": "query_docs",
                "query": query,
                "_intercepted_from": "openclaw",
            }

        return None

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

        result: CommandResult = await self.executor.execute_shell(command, cwd=cwd, timeout_s=timeout_s)
        stdout = _preview_text(result.stdout or "", 6000)
        stderr = _preview_text(result.stderr or "", 3000)
        return (
            f"[exit_code] {result.returncode}\n"
            f"[stdout]\n{stdout if stdout else '(empty)'}\n"
            f"[stderr]\n{stderr if stderr else '(empty)'}"
        )

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
