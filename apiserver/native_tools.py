#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Native local tools for agentic loop.

Goal:
- Handle basic local tasks inside Embla System directly.
- Execute native local tools only.
"""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from core.security.killswitch import KillSwitchController
from system.artifact_store import get_artifact_store
from system.execution_backend import ExecutionBackendRegistry, ExecutionBackendUnavailableError
from system.native_executor import CommandResult, NativeExecutor, NativeSecurityError
from core.security import get_policy_firewall
from system.sandbox_context import SandboxContext
from system.sleep_watch import wait_for_log_pattern
from system.subagent_contract import validate_parallel_contract
from system.test_baseline_guard import TestBaselineGuard, TestPoisoningDetector
from system.tool_contract import ToolResultEnvelope, build_tool_result_with_artifact
from system.workspace_transaction import ConflictBackoffConfig, WorkspaceChange, WorkspaceTransactionManager

if TYPE_CHECKING:
    from agents.runtime.agent_session import AgentSessionStore


_DEFAULT_PREVIEW_CHARS = 6000
_PY_REPL_BOOTSTRAP = (
    "import os,base64;"
    "src=base64.b64decode(os.environ.get('EMBLA_SAFE_REPL_PAYLOAD','')).decode('utf-8');"
    "exec(compile(src,'<embla_safe_repl_payload>','exec'),{'__name__':'__main__'})"
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
_TOOL_RESULT_NONE_MARKERS = {"", "(none)", "none", "null", "nil", "n/a", "undefined"}
_TOOL_RESULT_TAG_LINE_RE = re.compile(r"^\[([A-Za-z0-9_]+)\](?:\s*(.*))?$")


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


def _detect_structured_content_type(text: str) -> str:
    stripped = (text or "").strip()
    if not stripped:
        return "text/plain"

    if (stripped.startswith("{") and stripped.endswith("}")) or (
        stripped.startswith("[") and stripped.endswith("]")
    ):
        try:
            json.loads(stripped)
            return "application/json"
        except Exception:
            pass

    if stripped.startswith("<?xml") or (stripped.startswith("<") and stripped.endswith(">")):
        return "application/xml"

    lines = stripped.splitlines()
    if len(lines) >= 2 and "," in lines[0]:
        header_cols = len(lines[0].split(","))
        if header_cols >= 2 and any(len(row.split(",")) == header_cols for row in lines[1: min(len(lines), 20)]):
            return "text/csv"

    return "text/plain"


def _jsonpath_deep_find(node: Any, key: str, out: List[Any], max_items: int) -> None:
    if len(out) >= max_items:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                out.append(v)
                if len(out) >= max_items:
                    return
            _jsonpath_deep_find(v, key, out, max_items)
            if len(out) >= max_items:
                return
    elif isinstance(node, list):
        for item in node:
            _jsonpath_deep_find(item, key, out, max_items)
            if len(out) >= max_items:
                return


def _jsonpath_extract(content: str, query: str, max_items: int = 50) -> List[Any]:
    data = json.loads(content)
    query = (query or "").strip()
    if not query:
        raise ValueError("jsonpath query 不能为空")

    if query.startswith("$.."):
        key = query[3:].strip()
        if not key:
            raise ValueError("jsonpath 深度查询缺少 key，例如 $..trace_id")
        out: List[Any] = []
        _jsonpath_deep_find(data, key, out, max_items=max_items)
        return out

    if not query.startswith("$."):
        raise ValueError("仅支持 '$..key' 或 '$.a.b[0]' 形式的简化 jsonpath")

    cursor: Any = data
    expr = query[1:]  # 保留 ".a.b[0]"
    while expr:
        if expr.startswith("."):
            expr = expr[1:]
            m = re.match(r"([A-Za-z0-9_\-]+)", expr)
            if not m:
                raise ValueError(f"jsonpath 字段解析失败: {query}")
            key = m.group(1)
            if not isinstance(cursor, dict) or key not in cursor:
                return []
            cursor = cursor[key]
            expr = expr[m.end():]
            continue

        if expr.startswith("["):
            m = re.match(r"\[(\d+)\]", expr)
            if not m:
                raise ValueError(f"jsonpath 索引解析失败: {query}")
            index = int(m.group(1))
            if not isinstance(cursor, list) or index >= len(cursor):
                return []
            cursor = cursor[index]
            expr = expr[m.end():]
            continue

        raise ValueError(f"不支持的 jsonpath 片段: {expr}")

    return [cursor]


def _format_artifact_reader_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return repr(value)


def _render_tool_result_envelope(
    envelope: ToolResultEnvelope,
    *,
    exit_code: int,
    stderr_text: str,
    stderr_limit: int,
) -> str:
    stderr_preview = _preview_text(stderr_text or "", stderr_limit)
    forensic_ref = envelope.forensic_artifact_ref or envelope.raw_result_ref
    narrative_summary = envelope.narrative_summary if envelope.narrative_summary is not None else envelope.display_preview
    hints = ", ".join(envelope.fetch_hints or [])
    critical_evidence = envelope.critical_evidence if isinstance(envelope.critical_evidence, dict) else {}
    critical_evidence_text = json.dumps(critical_evidence, ensure_ascii=False) if critical_evidence else "(none)"
    lines = [
        f"[exit_code] {exit_code}",
        f"[content_type] {envelope.content_type}",
        f"[total_chars] {envelope.total_chars}",
        f"[total_lines] {envelope.total_lines}",
        f"[truncated] {envelope.truncated}",
        f"[forensic_artifact_ref] {forensic_ref or '(none)'}",
        f"[raw_result_ref] {envelope.raw_result_ref or forensic_ref or '(none)'}",
        f"[fetch_hints] {hints if hints else '(none)'}",
        f"[critical_evidence] {critical_evidence_text}",
        "[narrative_summary]",
        narrative_summary if narrative_summary else "(empty)",
        "[display_preview]",
        envelope.display_preview if envelope.display_preview else (narrative_summary if narrative_summary else "(empty)"),
        "[stderr]",
        stderr_preview if stderr_preview else "(empty)",
    ]
    return "\n".join(lines)


def _clean_optional_ref(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        return ""
    if text.lower() in _TOOL_RESULT_NONE_MARKERS:
        return ""
    return text


def _parse_tool_result_sections(result_text: str) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    current_tag: Optional[str] = None
    current_lines: List[str] = []
    for line in str(result_text or "").splitlines():
        stripped = line.strip()
        matched = _TOOL_RESULT_TAG_LINE_RE.match(stripped)
        if matched:
            if current_tag is not None:
                sections[current_tag] = "\n".join(current_lines).strip()
            current_tag = str(matched.group(1) or "").strip().lower()
            inline = str(matched.group(2) or "").strip()
            current_lines = [inline] if inline else []
            continue
        if current_tag is not None:
            current_lines.append(line.rstrip())
    if current_tag is not None:
        sections[current_tag] = "\n".join(current_lines).strip()
    return sections


def _build_result_contract_fields(result_text: str) -> Dict[str, Any]:
    text = str(result_text or "")
    sections = _parse_tool_result_sections(text)
    narrative_summary = str(sections.get("narrative_summary") or sections.get("display_preview") or text).strip()
    display_preview = str(sections.get("display_preview") or narrative_summary).strip()
    forensic_ref = _clean_optional_ref(sections.get("forensic_artifact_ref") or sections.get("raw_result_ref"))
    payload: Dict[str, Any] = {
        "narrative_summary": narrative_summary,
        "display_preview": display_preview,
    }
    if forensic_ref:
        payload["forensic_artifact_ref"] = forensic_ref
        payload["raw_result_ref"] = forensic_ref
    return payload


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
        self.policy_firewall = get_policy_firewall()
        self.killswitch_controller = KillSwitchController(
            state_file=self.project_root / "scratch" / "runtime" / "killswitch_guard_state_ws28_028.json"
        )
        self.workspace_txn = WorkspaceTransactionManager(project_root=self.project_root)
        self.backend_registry = ExecutionBackendRegistry()
        self._doc_roots = [
            "doc",
            "docs",
            "README.md",
            "README_en.md",
        ]
        self._agent_session_store: Optional[AgentSessionStore] = None

    def set_agent_session_store(self, store: Optional[AgentSessionStore]) -> None:
        self._agent_session_store = store

    def _resolve_session_sandbox_context(self, call: Dict[str, Any], session_id: str) -> SandboxContext:
        effective_call = dict(call) if isinstance(call, dict) else {}
        normalized_session_id = str(session_id or effective_call.get("_session_id") or effective_call.get("session_id") or "").strip()
        store = self._agent_session_store
        if store is None:
            return SandboxContext.default(session_id=normalized_session_id, project_root=self.project_root)

        candidate_ids: List[str] = []
        for raw in (effective_call.get("_session_id"), normalized_session_id, effective_call.get("session_id")):
            normalized = str(raw or "").strip()
            if normalized and normalized not in candidate_ids:
                candidate_ids.append(normalized)

        for candidate_id in candidate_ids:
            session = store.get(candidate_id)
            if session is None:
                continue
            context = SandboxContext.from_metadata(session.metadata, session_id=candidate_id, project_root=self.project_root)
            raw_root = str(context.workspace_host_root or "").strip()
            if raw_root:
                resolved_root = Path(raw_root).resolve(strict=False)
                if not self.executor._is_within_root(resolved_root, self.executor.PROJECT_ROOT):
                    continue
            return context
        return SandboxContext.default(session_id=normalized_session_id, project_root=self.project_root)

    def _build_effective_call(self, tool_name: str, call: Dict[str, Any], session_id: str) -> tuple[Dict[str, Any], SandboxContext, Any]:
        effective_call = dict(call) if isinstance(call, dict) else {}
        normalized_session_id = str(session_id or effective_call.get("_session_id") or effective_call.get("session_id") or "").strip()
        if normalized_session_id:
            effective_call["_session_id"] = normalized_session_id
        effective_call.pop("session_id", None)

        context = self._resolve_session_sandbox_context(effective_call, normalized_session_id)
        backend = self.backend_registry.resolve(context)
        effective_call = backend.prepare_call(tool_name, effective_call, context=context, native_tool_executor=self)
        if context.workspace_host_root:
            effective_call.setdefault("_session_workspace_root", str(context.workspace_host_root))
        return effective_call, context, backend

    def _persist_execution_backend_fallback(self, context: SandboxContext, *, reason: str) -> None:
        store = self._agent_session_store
        session_id = str(getattr(context, "session_id", "") or "").strip()
        if store is None or not session_id:
            return
        fallback_root = str(context.workspace_host_root or context.project_root or self.project_root).strip()
        try:
            store.update_metadata(
                session_id,
                {
                    "execution_backend": "native",
                    "execution_root": fallback_root,
                    "box_fallback_reason": str(reason or "boxlite_runtime_unavailable").strip() or "boxlite_runtime_unavailable",
                },
            )
        except Exception:
            return

    async def execute(self, call: Dict[str, Any], session_id: str) -> Dict[str, Any]:
        tool_name = (call.get("tool_name") or call.get("tool") or "").strip().lower()
        if not tool_name:
            return self._error(call, "native工具缺少 tool_name")

        aliases = {
            "read": "read_file",
            "readfile": "read_file",
            "write": "write_file",
            "writefile": "write_file",
            "os_bash": "run_cmd",
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
            "artifact": "artifact_reader",
            "read_artifact": "artifact_reader",
            "file_ast_chunk": "file_ast_chunk_read",
            "readchunkbyrange": "file_ast_chunk_read",
            "sleep_watch": "sleep_and_watch",
            "watch_log": "sleep_and_watch",
            "txn_apply": "workspace_txn_apply",
            "scaffold_apply": "workspace_txn_apply",
            "killswitch": "killswitch_plan",
            "repl": "python_repl",
        }
        tool_name = aliases.get(tool_name, tool_name)
        effective_call, context, backend = self._build_effective_call(tool_name, call, session_id)

        decision = self.policy_firewall.validate_native_call(tool_name, effective_call)
        if not decision.allowed:
            audit_suffix = f" (audit_id={decision.audit_id})" if decision.audit_id else ""
            return self._error(call, f"安全限制: {decision.reason}{audit_suffix}", tool_name=tool_name)

        fallback_reason = ""
        execution_backend_name = getattr(backend, "name", "native")
        try:
            result = await backend.execute_tool(tool_name, effective_call, context=context, native_tool_executor=self)
            service_name = getattr(backend, "service_name", "native")
        except ExecutionBackendUnavailableError as exc:
            if getattr(backend, "name", "native") == "native":
                return self._error(call, f"执行失败: {exc}", tool_name=tool_name)
            fallback_reason = str(exc or "").strip() or "boxlite runtime unavailable"
            self._persist_execution_backend_fallback(context, reason=fallback_reason)
            fallback_call, fallback_context, fallback_backend = self._build_effective_call(tool_name, call, session_id)
            fallback_decision = self.policy_firewall.validate_native_call(tool_name, fallback_call)
            if not fallback_decision.allowed:
                audit_suffix = f" (audit_id={fallback_decision.audit_id})" if fallback_decision.audit_id else ""
                return self._error(call, f"安全限制: {fallback_decision.reason}{audit_suffix}", tool_name=tool_name)
            try:
                result = await fallback_backend.execute_tool(
                    tool_name,
                    fallback_call,
                    context=fallback_context,
                    native_tool_executor=self,
                )
            except Exception as fallback_exc:
                return self._error(call, f"执行失败: {fallback_exc}", tool_name=tool_name)
            service_name = getattr(fallback_backend, "service_name", "native")
            execution_backend_name = getattr(fallback_backend, "name", service_name)
        except NativeSecurityError as e:
            return self._error(call, f"安全限制: {e}", tool_name=tool_name)
        except Exception as e:
            return self._error(call, f"执行失败: {e}", tool_name=tool_name)

        contract_fields = _build_result_contract_fields(result)
        response = {
            "tool_call": call,
            "result": result,
            "status": "success",
            "service_name": service_name,
            "execution_backend": execution_backend_name,
            "tool_name": tool_name,
            **contract_fields,
        }
        if fallback_reason:
            response["box_fallback_reason"] = fallback_reason
        return response

    async def _read_file(self, call: Dict[str, Any]) -> str:
        path = str(call.get("path") or call.get("file_path") or "").strip()
        if not path:
            raise ValueError("read_file 缺少 path")

        content = await self.executor.read_file(path)
        mode = str(call.get("mode") or "").strip().lower()
        start_line = call.get("start_line")
        end_line = call.get("end_line")
        max_chars = _safe_int(call.get("max_chars"), _DEFAULT_PREVIEW_CHARS, 200, 50000)
        max_results = _safe_int(call.get("max_results"), 50, 1, 5000)

        if mode == "grep":
            pattern_text = str(
                call.get("pattern") or call.get("keyword") or call.get("query") or ""
            ).strip()
            if not pattern_text:
                raise ValueError("read_file(mode=grep) 缺少 pattern/keyword/query")
            use_regex = bool(call.get("use_regex", False))
            case_sensitive = bool(call.get("case_sensitive", False))
            flags = 0 if case_sensitive else re.IGNORECASE
            pattern = re.compile(pattern_text if use_regex else re.escape(pattern_text), flags=flags)
            matched: List[str] = []
            for idx, line in enumerate(content.splitlines(), 1):
                if pattern.search(line):
                    matched.append(f"{idx:4}: {line}")
                    if len(matched) >= max_results:
                        break
            rendered = "\n".join(matched) if matched else "(no matches)"
            return "\n".join([f"[path] {path}", "[mode] grep", "[content]", rendered])

        if mode == "jsonpath":
            query = str(call.get("query") or call.get("jsonpath") or "").strip()
            if not query:
                raise ValueError("read_file(mode=jsonpath) 缺少 query/jsonpath")
            try:
                values = _jsonpath_extract(content, query, max_items=max_results)
            except json.JSONDecodeError as exc:
                raise ValueError(f"文件不是合法 JSON，无法执行 jsonpath: {exc}") from exc
            rendered = [_format_artifact_reader_value(v) for v in values]
            content_out = "\n".join(f"[{idx}] {item}" for idx, item in enumerate(rendered, 1))
            if not content_out:
                content_out = "(no matches)"
            return "\n".join([f"[path] {path}", "[mode] jsonpath", "[content]", content_out])

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

        safe_path = self.executor._resolve_safe_path(path, kind="file")
        requester = (
            str(call.get("requester") or call.get("_session_id") or call.get("session_id") or "").strip() or None
        )

        # NGA-WS17-002: 写入前执行 Anti-Test-Poisoning 门禁
        guard = TestBaselineGuard()
        allowed, reason = guard.check_modification_allowed(safe_path, requester=requester)
        if not allowed:
            raise NativeSecurityError(reason)

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
            self._validate_test_poisoning(safe_path, merged)
            await self.executor.write_file(path, merged, encoding=encoding)
        else:
            self._validate_test_poisoning(safe_path, content)
            await self.executor.write_file(path, content, encoding=encoding)

        return f"已写入文件: {path} (mode={mode}, chars={len(content)})"

    async def _get_cwd(self, call: Dict[str, Any]) -> str:
        """Return the effective working directory for this tool call."""
        cwd = str(call.get("cwd") or "").strip()
        if cwd:
            return cwd.replace('\\', '/')
        return str(self.project_root).replace('\\', '/')


    async def _run_cmd(self, call: Dict[str, Any]) -> str:
        command = str(call.get("command") or call.get("cmd") or "").strip()
        if not command:
            raise ValueError("run_cmd 缺少 command")

        cwd = call.get("cwd")
        timeout_s = _safe_int(call.get("timeout_seconds"), 120, 1, 1200)
        stdout_limit, stderr_limit = self._resolve_output_limits(call, default_stdout=6000, default_stderr=3000)

        call_id = str(call.get("_tool_call_id") or f"call_{abs(hash(command)) % 10_000_000}")
        fencing_epoch_raw = call.get("_fencing_epoch")
        try:
            fencing_epoch = int(fencing_epoch_raw) if fencing_epoch_raw is not None else None
        except Exception:
            fencing_epoch = None
        result: CommandResult = await self.executor.execute_shell(
            command,
            cwd=cwd,
            timeout_s=timeout_s,
            call_id=call_id,
            fencing_epoch=fencing_epoch,
        )
        stdout_text = result.stdout or ""
        content_type = _detect_structured_content_type(stdout_text)
        if content_type in {"application/json", "text/csv", "application/xml"}:
            trace_id = str(call.get("_trace_id") or "trace_native")
            envelope = build_tool_result_with_artifact(
                call_id=call_id,
                trace_id=trace_id,
                tool_name="os_bash",
                raw_output=stdout_text,
                content_type=content_type,
                priority=str(call.get("artifact_priority") or "normal"),
            )
            return _render_tool_result_envelope(
                envelope,
                exit_code=result.returncode,
                stderr_text=result.stderr,
                stderr_limit=stderr_limit,
            )

        return self._format_process_result(result, stdout_limit=stdout_limit, stderr_limit=stderr_limit)

    @staticmethod
    def _validate_test_poisoning(path: Path, content: str) -> None:
        guard = TestBaselineGuard()
        if not guard.is_test_file(path):
            return

        detector = TestPoisoningDetector()
        analysis = {
            "weakened_assertions": detector.detect_weakened_assertions(content),
            "test_skipping": detector.detect_test_skipping(content),
            "exception_swallowing": detector.detect_exception_swallowing(content),
        }
        if not detector.has_poisoning_patterns(analysis):
            return

        lines: List[str] = [f"Anti-Test-Poisoning blocked write: {path}"]
        for category, issues in analysis.items():
            if not issues:
                continue
            lines.append(f"  {category}:")
            for line_num, desc in issues[:10]:
                lines.append(f"    Line {line_num}: {desc}")
        raise NativeSecurityError("\n".join(lines))

    async def _search_keyword(self, call: Dict[str, Any]) -> str:
        keyword = str(call.get("keyword") or call.get("query") or "").strip()
        if not keyword:
            raise ValueError("search_keyword 缺少 keyword/query")

        search_path = str(call.get("search_path") or ".").strip()
        include_glob = str(call.get("glob") or "").strip()
        case_sensitive = bool(call.get("case_sensitive", False))
        use_regex = bool(call.get("use_regex", False))
        max_results = _safe_int(call.get("max_results"), 50, 1, 200)
        max_file_size = _safe_int(call.get("max_file_size_kb"), 512, 64, 2048) * 1024

        base = self.executor._resolve_safe_path(search_path, kind="search_path")
        matches: List[str] = []

        ignore_dirs = {".git", ".venv", "__pycache__", "node_modules", "dist", "release", "logs"}
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.compile(keyword if use_regex else re.escape(keyword), flags=flags)

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

    async def _artifact_reader(self, call: Dict[str, Any]) -> str:
        artifact_id = str(
            call.get("forensic_artifact_ref") or call.get("raw_result_ref") or call.get("artifact_id") or ""
        ).strip()
        if not artifact_id:
            raise ValueError("artifact_reader 缺少 forensic_artifact_ref/raw_result_ref/artifact_id")

        store = get_artifact_store()
        ok, message, content = store.retrieve(artifact_id)
        if not ok or content is None:
            raise FileNotFoundError(message)

        metadata = store.get_metadata(artifact_id)
        mode = str(call.get("mode") or "preview").strip().lower()
        max_results = _safe_int(call.get("max_results"), 50, 1, 5000)

        content_out = ""
        if mode == "line_range":
            lines = content.splitlines()
            if not lines:
                content_out = "(empty)"
            else:
                start = _safe_int(call.get("start_line"), 1, 1, len(lines))
                end_default = min(len(lines), start + 200)
                end = _safe_int(call.get("end_line"), end_default, start, len(lines))
                selected = lines[start - 1: end]
                content_out = "\n".join(f"{idx + start:4}: {line}" for idx, line in enumerate(selected))
        elif mode == "grep":
            pattern_text = str(call.get("pattern") or call.get("keyword") or call.get("query") or "").strip()
            if not pattern_text:
                raise ValueError("artifact_reader(mode=grep) 缺少 pattern/keyword/query")
            use_regex = bool(call.get("use_regex", False))
            case_sensitive = bool(call.get("case_sensitive", False))
            flags = 0 if case_sensitive else re.IGNORECASE
            pattern = re.compile(pattern_text if use_regex else re.escape(pattern_text), flags=flags)
            matched: List[str] = []
            for idx, line in enumerate(content.splitlines(), 1):
                if pattern.search(line):
                    matched.append(f"{idx:4}: {line}")
                    if len(matched) >= max_results:
                        break
            content_out = "\n".join(matched) if matched else "(no matches)"
        elif mode == "jsonpath":
            query = str(call.get("query") or call.get("jsonpath") or "").strip()
            if not query:
                raise ValueError("artifact_reader(mode=jsonpath) 缺少 query/jsonpath")
            try:
                values = _jsonpath_extract(content, query, max_items=max_results)
            except json.JSONDecodeError as exc:
                raise ValueError(f"artifact 不是合法 JSON，无法执行 jsonpath: {exc}") from exc
            rendered = [_format_artifact_reader_value(v) for v in values]
            content_out = "\n".join(f"[{idx}] {item}" for idx, item in enumerate(rendered, 1))
            if not content_out:
                content_out = "(no matches)"
        else:
            max_chars = _safe_int(call.get("max_chars"), 3000, 200, 200000)
            content_out = _preview_text(content, max_chars)

        meta_lines = [
            f"[artifact_id] {artifact_id}",
            f"[mode] {mode}",
        ]
        if metadata:
            meta_lines.extend(
                [
                    f"[content_type] {metadata.content_type.value}",
                    f"[total_chars] {metadata.total_chars}",
                    f"[total_lines] {metadata.total_lines}",
                    f"[file_size_bytes] {metadata.file_size_bytes}",
                    f"[created_at] {metadata.created_at}",
                    f"[expires_at] {metadata.expires_at}",
                    f"[access_count] {metadata.access_count}",
                    f"[fetch_hints] {', '.join(metadata.fetch_hints) if metadata.fetch_hints else '(none)'}",
                ]
            )
        meta_lines.append("[content]")
        meta_lines.append(content_out)
        return "\n".join(meta_lines)

    async def _file_ast_skeleton(self, call: Dict[str, Any]) -> str:
        path = str(call.get("path") or call.get("file_path") or "").strip()
        if not path:
            raise ValueError("file_ast_skeleton 缺少 path")

        text = await self.executor.read_file(path)
        lines = text.splitlines()
        ext = Path(path).suffix.lower()
        max_symbols = _safe_int(call.get("max_results"), 300, 20, 5000)

        import_patterns = [
            re.compile(r"^\s*import\s+.+"),
            re.compile(r"^\s*from\s+.+\s+import\s+.+"),
            re.compile(r"^\s*using\s+.+;"),
        ]
        symbol_patterns: List[re.Pattern[str]] = []
        if ext in {".py"}:
            symbol_patterns = [re.compile(r"^\s*(class|def)\s+([A-Za-z_][A-Za-z0-9_]*)")]
        elif ext in {".ts", ".tsx", ".js", ".jsx"}:
            symbol_patterns = [
                re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(function|class|interface|type|enum)\s+([A-Za-z_][A-Za-z0-9_]*)"),
                re.compile(r"^\s*(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\("),
            ]
        elif ext in {".cs"}:
            symbol_patterns = [
                re.compile(
                    r"^\s*(?:public|private|protected|internal)?\s*(?:static\s+)?(class|interface|record|enum)\s+([A-Za-z_][A-Za-z0-9_]*)"
                ),
                re.compile(
                    r"^\s*(?:public|private|protected|internal)\s+(?:static\s+)?(?:async\s+)?[A-Za-z_<>\[\],?]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("
                ),
            ]
        else:
            symbol_patterns = [re.compile(r"^\s*(class|def|function)\s+([A-Za-z_][A-Za-z0-9_]*)")]

        imports: List[str] = []
        symbols: List[str] = []
        for idx, line in enumerate(lines, 1):
            if len(imports) < 200 and any(p.search(line) for p in import_patterns):
                imports.append(f"{idx:4}: {line.strip()}")

            if len(symbols) >= max_symbols:
                continue
            for pattern in symbol_patterns:
                m = pattern.search(line)
                if not m:
                    continue
                if len(m.groups()) >= 2:
                    kind = m.group(1)
                    name = m.group(2)
                else:
                    kind = "symbol"
                    name = m.group(1)
                symbols.append(f"{idx:4}: {kind} {name}")
                break

        sections = [
            f"[path] {path}",
            f"[language] {ext or '(unknown)'}",
            f"[total_lines] {len(lines)}",
            f"[total_chars] {len(text)}",
        ]
        if len(lines) > 5000:
            sections.append("[note] Monolith file detected; this is skeleton-only output.")
        sections.extend(["[imports]"])
        sections.append("\n".join(imports) if imports else "(none)")
        sections.extend(["[symbols]"])
        sections.append("\n".join(symbols) if symbols else "(none)")
        return "\n".join(sections)

    async def _file_ast_chunk_read(self, call: Dict[str, Any]) -> str:
        path = str(call.get("path") or call.get("file_path") or "").strip()
        if not path:
            raise ValueError("file_ast_chunk_read 缺少 path")

        text = await self.executor.read_file(path)
        lines = text.splitlines()
        if not lines:
            return f"[path] {path}\n(content is empty)"

        start_line = _safe_int(call.get("start_line"), 1, 1, len(lines))
        end_default = min(len(lines), start_line + 120)
        end_line = _safe_int(call.get("end_line"), end_default, start_line, len(lines))
        context_before = _safe_int(call.get("context_before"), 3, 0, 200)
        context_after = _safe_int(call.get("context_after"), 3, 0, 200)

        from_line = max(1, start_line - context_before)
        to_line = min(len(lines), end_line + context_after)
        selected = lines[from_line - 1: to_line]

        rendered: List[str] = [
            f"[path] {path}",
            f"[requested_range] {start_line}-{end_line}",
            f"[returned_range] {from_line}-{to_line}",
            "[content]",
        ]
        for idx, line in enumerate(selected, from_line):
            marker = ">>" if start_line <= idx <= end_line else "  "
            rendered.append(f"{marker} {idx:4}: {line}")
        return "\n".join(rendered)

    async def _workspace_txn_apply(self, call: Dict[str, Any]) -> str:
        changes_raw = call.get("changes")
        if not isinstance(changes_raw, list) or not changes_raw:
            raise ValueError("workspace_txn_apply 缺少 changes[]")

        def _parse_bool(value: Any, default: bool) -> bool:
            if value is None:
                return default
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                text = value.strip().lower()
                if text in {"1", "true", "yes", "on"}:
                    return True
                if text in {"0", "false", "no", "off"}:
                    return False
            return bool(value)

        changes: List[WorkspaceChange] = []
        changed_paths: List[str] = []
        semantic_rebase_default = _parse_bool(call.get("semantic_rebase"), True)
        backoff_raw = call.get("conflict_backoff")
        backoff_cfg = backoff_raw if isinstance(backoff_raw, dict) else {}

        def _pick_backoff_value(*keys: str) -> Any:
            for key in keys:
                if key in backoff_cfg and backoff_cfg.get(key) is not None:
                    return backoff_cfg.get(key)
                if call.get(key) is not None:
                    return call.get(key)
            return None

        def _safe_float(value: Any, default: float, min_value: float, max_value: float) -> float:
            try:
                num = float(value)
            except Exception:
                return default
            return max(min_value, min(max_value, num))

        def _optional_int(value: Any, min_value: int, max_value: int) -> Optional[int]:
            if value is None:
                return None
            try:
                num = int(value)
            except Exception:
                return None
            return max(min_value, min(max_value, num))

        def _optional_float(value: Any, min_value: float, max_value: float) -> Optional[float]:
            if value is None:
                return None
            try:
                num = float(value)
            except Exception:
                return None
            return max(min_value, min(max_value, num))

        backoff_base_ms = _safe_int(
            _pick_backoff_value("base_ms", "conflict_backoff_base_ms", "backoff_base_ms"), 200, 1, 600000
        )
        backoff_max_ms = _safe_int(
            _pick_backoff_value("max_ms", "conflict_backoff_max_ms", "backoff_max_ms"), 5000, 1, 600000
        )
        backoff_attempt = _safe_int(
            _pick_backoff_value("attempt", "conflict_backoff_attempt", "backoff_attempt"), 1, 1, 32
        )
        backoff_jitter_ratio = _safe_float(
            _pick_backoff_value("jitter_ratio", "conflict_backoff_jitter_ratio", "backoff_jitter_ratio"),
            0.25,
            0.0,
            1.0,
        )
        conflict_backoff = ConflictBackoffConfig(
            base_ms=backoff_base_ms,
            max_ms=max(backoff_base_ms, backoff_max_ms),
            attempt=backoff_attempt,
            jitter_ratio=backoff_jitter_ratio,
        )

        requester = (
            str(call.get("requester") or call.get("_session_id") or call.get("session_id") or "").strip() or None
        )
        guard = TestBaselineGuard()
        for idx, item in enumerate(changes_raw, 1):
            if not isinstance(item, dict):
                raise ValueError(f"changes[{idx}] must be object")
            path = str(item.get("path") or item.get("file_path") or "").strip()
            content = item.get("content")
            if not path or content is None:
                raise ValueError(f"changes[{idx}] missing path/content")
            mode = str(item.get("mode") or "overwrite").strip().lower()
            encoding = str(item.get("encoding") or "utf-8").strip()
            expected_hash = str(
                item.get("expected_hash") or item.get("expected_file_hash") or item.get("original_file_hash") or ""
            ).strip()
            original_content_raw = item.get("original_content")
            original_content = str(original_content_raw) if original_content_raw is not None else None
            semantic_rebase = _parse_bool(item.get("semantic_rebase"), semantic_rebase_default)
            item_backoff_raw = item.get("conflict_backoff")
            item_backoff_cfg = item_backoff_raw if isinstance(item_backoff_raw, dict) else {}

            def _pick_item_backoff_value(*keys: str) -> Any:
                for key in keys:
                    if key in item_backoff_cfg and item_backoff_cfg.get(key) is not None:
                        return item_backoff_cfg.get(key)
                    if item.get(key) is not None:
                        return item.get(key)
                return None

            item_backoff_base_ms = _optional_int(
                _pick_item_backoff_value("base_ms", "conflict_backoff_base_ms", "backoff_base_ms"), 1, 600000
            )
            item_backoff_max_ms = _optional_int(
                _pick_item_backoff_value("max_ms", "conflict_backoff_max_ms", "backoff_max_ms"), 1, 600000
            )
            item_backoff_attempt = _optional_int(
                _pick_item_backoff_value("attempt", "conflict_backoff_attempt", "backoff_attempt"), 1, 32
            )
            item_backoff_jitter_ratio = _optional_float(
                _pick_item_backoff_value("jitter_ratio", "conflict_backoff_jitter_ratio", "backoff_jitter_ratio"),
                0.0,
                1.0,
            )

            safe_path = self.executor._resolve_safe_path(path, kind="file")
            allowed, reason = guard.check_modification_allowed(safe_path, requester=requester)
            if not allowed:
                raise NativeSecurityError(reason)
            self._validate_test_poisoning(safe_path, str(content))

            rel = str(safe_path.relative_to(self.project_root)).replace("\\", "/")
            changed_paths.append(rel)
            changes.append(
                WorkspaceChange(
                    path=rel,
                    content=str(content),
                    mode=mode,
                    encoding=encoding,
                    original_file_hash=expected_hash,
                    expected_file_hash=expected_hash,
                    original_content=original_content,
                    semantic_rebase=semantic_rebase,
                    conflict_backoff_base_ms=item_backoff_base_ms,
                    conflict_backoff_max_ms=item_backoff_max_ms,
                    conflict_backoff_attempt=item_backoff_attempt,
                    conflict_backoff_jitter_ratio=item_backoff_jitter_ratio,
                )
            )

        contract_id = str(call.get("contract_id") or "").strip()
        contract_checksum = str(call.get("contract_checksum") or "").strip()
        contract_result = validate_parallel_contract(
            contract_id=contract_id,
            contract_checksum=contract_checksum,
            changed_paths=changed_paths,
        )
        if not contract_result.ok:
            raise NativeSecurityError(contract_result.message)

        verify_after_apply = bool(call.get("verify_after_apply", True))

        def _verify(receipt) -> tuple[bool, str]:
            if not verify_after_apply:
                return True, "verify skipped"
            for rel_path in receipt.changed_files:
                safe_path = self.executor._resolve_safe_path(rel_path, kind="file")
                if not safe_path.exists():
                    return False, f"missing file after apply: {rel_path}"
            return True, "verify ok"

        receipt = self.workspace_txn.apply_all(changes, verify_fn=_verify, conflict_backoff=conflict_backoff)
        if not receipt.committed:
            failed_meta = [
                f"clean_state={receipt.clean_state}",
                f"recovery_ticket={receipt.recovery_ticket}",
                f"rolled_back_files={len(receipt.rolled_back_files)}",
            ]
            if receipt.rollback_failed_files:
                failed_meta.append(f"rollback_failed_files={len(receipt.rollback_failed_files)}")
            if receipt.conflict_ticket:
                failed_meta.append(f"conflict_ticket={receipt.conflict_ticket}")
            if receipt.conflict_signature:
                failed_meta.append(f"conflict_signature={receipt.conflict_signature}")
            if receipt.backoff_ms > 0:
                failed_meta.append(f"backoff_ms={receipt.backoff_ms}")
            if receipt.conflict_path:
                failed_meta.append(f"conflict_path={receipt.conflict_path}")
            raise NativeSecurityError(
                "workspace transaction failed"
                f" ({', '.join(failed_meta)}): {receipt.error}"
            )

        lines = [
            f"[transaction_id] {receipt.transaction_id}",
            f"[committed] {receipt.committed}",
            f"[clean_state] {receipt.clean_state}",
            f"[recovery_ticket] {receipt.recovery_ticket}",
            f"[changed_files] {len(receipt.changed_files)}",
            f"[semantic_rebased_files] {len(receipt.semantic_rebased_files)}",
            f"[verify] {receipt.verify_message or 'verify ok'}",
        ]
        if contract_result.normalized_contract_id:
            lines.append(f"[contract_id] {contract_result.normalized_contract_id}")
            lines.append(f"[contract_checksum] {contract_result.expected_checksum}")
            lines.append(f"[scaffold_fingerprint] {contract_result.scaffold_fingerprint}")
        if receipt.semantic_rebased_files:
            lines.append("[semantic_rebase_paths]")
            lines.extend(receipt.semantic_rebased_files)
        lines.append("[files]")
        lines.extend(receipt.changed_files)
        return "\n".join(lines)

    async def _sleep_and_watch(self, call: Dict[str, Any]) -> str:
        log_file = str(call.get("log_file") or call.get("path") or "").strip()
        if not log_file:
            raise ValueError("sleep_and_watch missing log_file/path")

        pattern = str(call.get("pattern") or call.get("regex") or "").strip()
        if not pattern:
            raise ValueError("sleep_and_watch missing pattern/regex")

        timeout_seconds = _safe_int(call.get("timeout_seconds"), 600, 1, 86400)
        poll_interval_seconds = float(call.get("poll_interval_seconds") or 0.5)
        from_end = bool(call.get("from_end", True))
        max_line_chars = _safe_int(call.get("max_line_chars"), 4000, 64, 20000)

        safe_path = self.executor._resolve_safe_path(log_file, kind="log_file")
        watch_result = await wait_for_log_pattern(
            log_file=safe_path,
            pattern=pattern,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=max(0.05, min(5.0, poll_interval_seconds)),
            from_end=from_end,
            max_line_chars=max_line_chars,
        )

        lines = [
            f"[watch_id] {watch_result.watch_id}",
            f"[matched] {watch_result.matched}",
            f"[reason] {watch_result.reason}",
            f"[elapsed_seconds] {watch_result.elapsed_seconds:.3f}",
        ]
        if watch_result.matched_line:
            lines.append(f"[matched_line] {watch_result.matched_line}")
        return "\n".join(lines)

    async def _killswitch_plan(self, call: Dict[str, Any]) -> str:
        mode = str(call.get("mode") or "freeze").strip().lower()
        if mode not in {"freeze", "preview"}:
            raise ValueError("killswitch_plan mode supports freeze/preview")

        allowlist_raw = call.get("oob_allowlist")
        if isinstance(allowlist_raw, str):
            allowlist = [part.strip() for part in allowlist_raw.split(",") if part.strip()]
        elif isinstance(allowlist_raw, list):
            allowlist = [str(x).strip() for x in allowlist_raw if str(x).strip()]
        else:
            allowlist = []

        dns_allow = bool(call.get("dns_allow", True))
        requested_by = str(call.get("requested_by") or "native_tool").strip() or "native_tool"
        approval_ticket = str(call.get("approval_ticket") or "").strip()
        plan = self.killswitch_controller.create_freeze_plan(
            oob_allowlist=allowlist,
            dns_allow=dns_allow,
            requested_by=requested_by,
            approval_ticket=approval_ticket,
            activate=(mode == "freeze"),
        )
        lines = [
            f"[mode] {plan.mode}",
            f"[execution_state] {'planned' if mode == 'freeze' else 'previewed'}",
            "[engaged] false",
            f"[oob_allowlist] {', '.join(plan.oob_allowlist)}",
            "[commands]",
        ]
        lines.extend(plan.commands)
        return "\n".join(lines)

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
        call_id = str(call.get("_tool_call_id") or f"call_git_{abs(hash(' '.join(git_args))) % 10_000_000}")
        fencing_epoch_raw = call.get("_fencing_epoch")
        try:
            fencing_epoch = int(fencing_epoch_raw) if fencing_epoch_raw is not None else None
        except Exception:
            fencing_epoch = None
        return await self.executor.run(
            ["git", *git_args],
            cwd=repo_path,
            timeout_s=timeout_s,
            call_id=call_id,
            fencing_epoch=fencing_epoch,
        )

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
        call_id = str(call.get("_tool_call_id") or f"call_py_{abs(hash(code)) % 10_000_000}")
        fencing_epoch_raw = call.get("_fencing_epoch")
        try:
            fencing_epoch = int(fencing_epoch_raw) if fencing_epoch_raw is not None else None
        except Exception:
            fencing_epoch = None

        payload_script = _build_safe_python_payload(code)
        payload_b64 = base64.b64encode(payload_script.encode("utf-8")).decode("ascii")
        env = {"EMBLA_SAFE_REPL_PAYLOAD": payload_b64}

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
            process = await self.executor.run(
                command,
                env=env,
                timeout_s=timeout_s + 10,
                call_id=call_id,
                fencing_epoch=fencing_epoch,
            )
        else:
            python_cmd = str(call.get("python_cmd") or "python").strip()
            if not python_cmd:
                python_cmd = "python"
            process = await self.executor.run(
                [python_cmd, "-I", "-c", _PY_REPL_BOOTSTRAP],
                env=env,
                timeout_s=timeout_s,
                call_id=call_id,
                fencing_epoch=fencing_epoch,
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

    async def _execute_native_tool(self, tool_name: str, call: Dict[str, Any]) -> str:
        if tool_name == "read_file":
            return await self._read_file(call)
        if tool_name == "write_file":
            return await self._write_file(call)
        if tool_name == "get_cwd":
            return await self._get_cwd(call)
        if tool_name == "run_cmd":
            return await self._run_cmd(call)
        if tool_name == "search_keyword":
            return await self._search_keyword(call)
        if tool_name == "query_docs":
            return await self._query_docs(call)
        if tool_name == "list_files":
            return await self._list_files(call)
        if tool_name == "git_status":
            return await self._git_status(call)
        if tool_name == "git_diff":
            return await self._git_diff(call)
        if tool_name == "git_log":
            return await self._git_log(call)
        if tool_name == "git_show":
            return await self._git_show(call)
        if tool_name == "git_blame":
            return await self._git_blame(call)
        if tool_name == "git_grep":
            return await self._git_grep(call)
        if tool_name == "git_changed_files":
            return await self._git_changed_files(call)
        if tool_name == "git_checkout_file":
            return await self._git_checkout_file(call)
        if tool_name == "python_repl":
            return await self._python_repl(call)
        if tool_name == "artifact_reader":
            return await self._artifact_reader(call)
        if tool_name == "file_ast_skeleton":
            return await self._file_ast_skeleton(call)
        if tool_name == "file_ast_chunk_read":
            return await self._file_ast_chunk_read(call)
        if tool_name == "workspace_txn_apply":
            return await self._workspace_txn_apply(call)
        if tool_name == "sleep_and_watch":
            return await self._sleep_and_watch(call)
        if tool_name == "killswitch_plan":
            return await self._killswitch_plan(call)
        raise ValueError(f"不支持的native工具: {tool_name}")

    @staticmethod
    def _error(call: Dict[str, Any], message: str, *, tool_name: Optional[str] = None) -> Dict[str, Any]:
        contract_fields = _build_result_contract_fields(message)
        return {
            "tool_call": call,
            "result": message,
            "status": "error",
            "service_name": "native",
            "tool_name": tool_name or str(call.get("tool_name") or call.get("tool") or "native"),
            **contract_fields,
        }


_native_tool_executor: Optional[NativeToolExecutor] = None


def get_native_tool_executor() -> NativeToolExecutor:
    global _native_tool_executor
    if _native_tool_executor is None:
        _native_tool_executor = NativeToolExecutor()
    return _native_tool_executor
