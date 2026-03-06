"""Shell Agent read-only tool definitions and handlers.

Canonical Shell tools:
  1. memory_read      — read project files (path + optional line range)
  2. memory_list      — list L1 memory files by scope
  3. memory_grep      — grep L1 memory files by keyword/regex
  4. memory_search    — unified L1 index + episodic archive + Shell L2 quintuple search
  5. get_system_status — brainstem posture + agent stats + git status
  6. list_tasks       — active tasks from TaskBoardEngine
  7. search_web       — extensible stub (requires external API config)

Legacy aliases remain supported:
  - read_file -> memory_read
  - search_memory -> memory_search
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SHELL_TOOL_ALIASES = {
    "read_file": "memory_read",
    "search_memory": "memory_search",
}


def normalize_shell_tool_name(tool_name: str) -> str:
    text = str(tool_name or "").strip()
    if not text:
        return ""
    return _SHELL_TOOL_ALIASES.get(text, text)


def is_shell_tool_supported(tool_name: str) -> bool:
    return normalize_shell_tool_name(tool_name) in {
        "memory_read",
        "memory_list",
        "memory_grep",
        "memory_search",
        "get_system_status",
        "list_tasks",
        "search_web",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Tool Definitions (LLM schema)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TOOL_DEF_READ_FILE: Dict[str, Any] = {
    "name": "memory_read",
    "description": (
        "Read a file from the project. Returns file content with optional "
        "line range selection. Shell can read any file but cannot modify."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative or absolute path to the file.",
            },
            "start_line": {
                "type": "integer",
                "description": "Optional start line (1-indexed).",
            },
            "end_line": {
                "type": "integer",
                "description": "Optional end line (1-indexed, inclusive).",
            },
        },
        "required": ["path"],
    },
}

TOOL_DEF_MEMORY_LIST: Dict[str, Any] = {
    "name": "memory_list",
    "description": "List Layer-1 memory files by scope.",
    "parameters": {
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "enum": ["all", "working", "episodic", "domain", "deprecated"],
                "description": "Memory scope to list (default: all).",
            },
            "pattern": {
                "type": "string",
                "description": "Glob pattern, default `*.md`.",
            },
            "recursive": {
                "type": "boolean",
                "description": "Whether to recurse subdirectories.",
            },
        },
    },
}

TOOL_DEF_MEMORY_GREP: Dict[str, Any] = {
    "name": "memory_grep",
    "description": "Search matching lines across Layer-1 memory markdown files.",
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Keyword or regex to search for.",
            },
            "scope": {
                "type": "string",
                "enum": ["all", "working", "episodic", "domain", "deprecated"],
                "description": "Memory scope to search (default: all).",
            },
            "top_k": {
                "type": "integer",
                "description": "Max matches to return (default 20).",
            },
            "use_regex": {
                "type": "boolean",
                "description": "Treat `pattern` as regex.",
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Whether matching is case-sensitive.",
            },
        },
        "required": ["pattern"],
    },
}

TOOL_DEF_SYSTEM_STATUS: Dict[str, Any] = {
    "name": "get_system_status",
    "description": (
        "Get the current system status including brainstem posture, "
        "agent session statistics, and git repository status."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

TOOL_DEF_SEARCH_MEMORY: Dict[str, Any] = {
    "name": "memory_search",
    "description": (
        "Search across the memory system: L1 episodic index (tag-based), "
        "episodic archive (narrative similarity), and the Shell L2 quintuple graph. "
        "Returns matching memory entries with relevance."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query string.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tag filter for L1 index.",
            },
            "top_k": {
                "type": "integer",
                "description": "Max results per source (default 5).",
            },
        },
        "required": ["query"],
    },
}

TOOL_DEF_LIST_TASKS: Dict[str, Any] = {
    "name": "list_tasks",
    "description": (
        "List active tasks from the TaskBoard. Shows task IDs, status, "
        "assigned agents, and progress."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "status_filter": {
                "type": "string",
                "enum": ["all", "pending", "in_progress", "blocked", "done", "completed", "failed"],
                "description": "Filter by task status (default: all).",
            },
        },
    },
}

TOOL_DEF_SEARCH_WEB: Dict[str, Any] = {
    "name": "search_web",
    "description": (
        "Search the web for information. Currently requires external API "
        "configuration. Returns search results or a configuration reminder."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query.",
            },
        },
        "required": ["query"],
    },
}


def get_shell_tool_definitions() -> List[Dict[str, Any]]:
    """Return all Shell read-only tool definitions for the LLM."""
    return [
        TOOL_DEF_READ_FILE,
        TOOL_DEF_MEMORY_LIST,
        TOOL_DEF_MEMORY_GREP,
        TOOL_DEF_SYSTEM_STATUS,
        TOOL_DEF_SEARCH_MEMORY,
        TOOL_DEF_LIST_TASKS,
        TOOL_DEF_SEARCH_WEB,
    ]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Tool Handlers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def handle_shell_tool(
    tool_name: str,
    arguments: Dict[str, Any],
    *,
    project_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Dispatch a Shell read-only tool call to the appropriate handler.

    Returns a dict with 'result' key containing the tool output.
    """
    root = project_root or _PROJECT_ROOT
    normalized_tool_name = normalize_shell_tool_name(tool_name)
    try:
        if normalized_tool_name == "memory_read":
            result = _handle_read_file(arguments, project_root=root)
        elif normalized_tool_name == "memory_list":
            result = _handle_memory_list(arguments, project_root=root)
        elif normalized_tool_name == "memory_grep":
            result = _handle_memory_grep(arguments, project_root=root)
        elif normalized_tool_name == "get_system_status":
            result = _handle_get_system_status(project_root=root)
        elif normalized_tool_name == "memory_search":
            result = _handle_search_memory(arguments, project_root=root)
        elif normalized_tool_name == "list_tasks":
            result = _handle_list_tasks(arguments, project_root=root)
        elif normalized_tool_name == "search_web":
            result = _handle_search_web(arguments)
        else:
            return {"error": f"Unknown shell tool: {tool_name}", "status": "error"}

        return {"result": result, "status": "success", "tool_name": normalized_tool_name}
    except Exception as exc:
        logger.warning("Shell tool %s failed: %s", tool_name, exc)
        return {
            "error": str(exc),
            "status": "error",
            "tool_name": normalized_tool_name or tool_name,
        }


# ── 1. memory_read ─────────────────────────────────────────────


def _handle_read_file(
    args: Dict[str, Any],
    *,
    project_root: Path,
) -> str:
    """Read a file from the project."""
    path_str = str(args.get("path", "")).strip()
    if not path_str:
        raise ValueError("memory_read: 缺少 path 参数")

    filepath = Path(path_str)
    if not filepath.is_absolute():
        filepath = project_root / filepath

    if not filepath.exists():
        raise FileNotFoundError(f"文件不存在: {path_str}")

    # Security: only allow reading within project root
    try:
        filepath.resolve().relative_to(project_root.resolve())
    except ValueError:
        raise PermissionError(f"memory_read: 不允许访问项目外文件: {path_str}")

    content = filepath.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()

    start = args.get("start_line")
    end = args.get("end_line")
    if start is not None or end is not None:
        s = max(1, int(start or 1))
        e = min(len(lines), int(end or min(s + 200, len(lines))))
        selected = lines[s - 1 : e]
        numbered = [f"{idx + s:4}: {line}" for idx, line in enumerate(selected)]
        return f"[{filepath.name}] lines {s}-{e} of {len(lines)}:\n" + "\n".join(numbered)

    # Truncate if too long
    max_chars = 6000
    if len(content) > max_chars:
        return (
            f"[{filepath.name}] ({len(lines)} lines, {len(content)} chars, 截断显示)\n"
            + content[:max_chars]
            + f"\n... [截断: 共 {len(content)} 字符]"
        )

    return f"[{filepath.name}] ({len(lines)} lines):\n{content}"


# ── 2. memory_list ─────────────────────────────────────────────


def _handle_memory_list(
    args: Dict[str, Any],
    *,
    project_root: Path,
) -> str:
    """List memory files under the project's `memory/` root."""
    from agents.memory.l1_memory import L1MemoryManager

    mgr = L1MemoryManager(memory_root=str(project_root / "memory"))
    scope = str(args.get("scope") or "all").strip().lower() or "all"
    pattern = str(args.get("pattern") or "*.md").strip() or "*.md"
    recursive = bool(args.get("recursive", True))
    items = mgr.list_memory(scope=scope, pattern=pattern, recursive=recursive)
    lines = [f"## 记忆列表 (scope={scope}, count={len(items)})"]
    if not items:
        lines.append("\n未找到匹配的记忆文件。")
        return "\n".join(lines)
    for item in items[:50]:
        lines.append(f"- {item}")
    if len(items) > 50:
        lines.append(f"- ... 还有 {len(items) - 50} 项")
    return "\n".join(lines)


# ── 3. memory_grep ─────────────────────────────────────────────


def _handle_memory_grep(
    args: Dict[str, Any],
    *,
    project_root: Path,
) -> str:
    """Search matching lines across the L1 memory store."""
    from agents.memory.l1_memory import L1MemoryManager

    pattern = str(args.get("pattern") or "").strip()
    if not pattern:
        raise ValueError("memory_grep: 缺少 pattern 参数")

    mgr = L1MemoryManager(memory_root=str(project_root / "memory"))
    scope = str(args.get("scope") or "all").strip().lower() or "all"
    matches = mgr.grep_memory(
        pattern,
        scope=scope,
        top_k=int(args.get("top_k") or 20),
        use_regex=bool(args.get("use_regex", False)),
        case_sensitive=bool(args.get("case_sensitive", False)),
    )
    lines = [f"## 记忆 grep: {pattern} (scope={scope})"]
    if not matches:
        lines.append("\n未找到匹配项。")
        return "\n".join(lines)
    for row in matches:
        lines.append(f"- {row.get('path')}:{row.get('line')} {row.get('content')}")
    return "\n".join(lines)


# ── 4. get_system_status ──────────────────────────────────────


def _handle_get_system_status(*, project_root: Path) -> str:
    """Collect system status from multiple sources."""
    sections: List[str] = []

    # A. Brainstem posture
    posture_file = project_root / "scratch" / "runtime" / "event_bus_runtime_posture_ws28_029.json"
    if posture_file.exists():
        try:
            posture_data = json.loads(posture_file.read_text(encoding="utf-8"))
            sections.append("## 脑干 Posture 状态")
            sections.append(f"- 事件总数: {posture_data.get('events_total', 'N/A')}")
            sections.append(f"- 错误数: {posture_data.get('errors_total', 'N/A')}")
            sections.append(f"- 最近事件: {posture_data.get('latest_event_type', 'N/A')}")
            sections.append(f"- 更新时间: {posture_data.get('updated_at', 'N/A')}")
        except Exception as exc:
            sections.append(f"## 脑干 Posture: 读取失败 ({exc})")
    else:
        sections.append("## 脑干 Posture: 未初始化（posture 文件不存在）")

    # B. Killswitch state
    ks_file = project_root / "scratch" / "runtime" / "killswitch_guard_state_ws28_028.json"
    if ks_file.exists():
        try:
            ks_data = json.loads(ks_file.read_text(encoding="utf-8"))
            active = ks_data.get("active", False)
            sections.append(f"\n## Killswitch: {'🔴 激活' if active else '🟢 正常'}")
        except Exception:
            sections.append("\n## Killswitch: 状态未知")
    else:
        sections.append("\n## Killswitch: 未配置")

    # C. Agent sessions (if session store exists)
    session_dir = project_root / "scratch" / "runtime" / "sessions"
    if session_dir.exists():
        session_count = sum(1 for _ in session_dir.glob("*.json"))
        sections.append(f"\n## Agent 会话: {session_count} 个活跃会话文件")
    else:
        sections.append("\n## Agent 会话: 无活跃会话")

    # D. Git status (brief)
    try:
        git_result = subprocess.run(
            ["git", "status", "--short"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if git_result.returncode == 0:
            changes = git_result.stdout.strip()
            if changes:
                change_lines = changes.splitlines()
                sections.append(
                    f"\n## Git 状态: {len(change_lines)} 个变更文件"
                )
                # Show at most 10 lines
                for line in change_lines[:10]:
                    sections.append(f"  {line}")
                if len(change_lines) > 10:
                    sections.append(f"  ... 还有 {len(change_lines) - 10} 个")
            else:
                sections.append("\n## Git 状态: 工作目录干净")
    except Exception:
        sections.append("\n## Git 状态: 无法获取")

    # E. Memory stats
    memory_root = project_root / "memory"
    if memory_root.exists():
        episodic_count = sum(1 for _ in (memory_root / "episodic").glob("exp_*.md")) if (memory_root / "episodic").exists() else 0
        domain_count = sum(1 for _ in (memory_root / "domain").glob("*.md")) if (memory_root / "domain").exists() else 0
        working_count = sum(1 for _ in (memory_root / "working").iterdir()) if (memory_root / "working").exists() else 0
        sections.append(
            f"\n## 记忆系统: {episodic_count} 经验 / {domain_count} 领域 / {working_count} 工作会话"
        )
    else:
        sections.append("\n## 记忆系统: 未初始化")

    return "\n".join(sections)


# ── 5. memory_search ──────────────────────────────────────────


def _handle_search_memory(
    args: Dict[str, Any],
    *,
    project_root: Path,
) -> str:
    """Search across L1 index, episodic archive, and the Shell L2 quintuple graph."""
    query = str(args.get("query", "")).strip()
    if not query:
        raise ValueError("memory_search: 缺少 query 参数")

    tags = args.get("tags") or []
    top_k = int(args.get("top_k", 5))
    results: List[str] = [f"## 搜索: {query}"]

    # A. L1 Index (tag-based)
    try:
        from agents.memory.l1_memory import L1MemoryManager
        mgr = L1MemoryManager(memory_root=str(project_root / "memory"))
        if tags:
            matches = mgr.scan_index(tags=tags)
            if matches:
                results.append(f"\n### L1 标签匹配 (tags={tags})")
                for m in matches[:top_k]:
                    results.append(f"- {m}")
        # Also search by keyword in index entries (best effort).
        keyword_matches = [
            entry
            for entry in mgr.scan_index(top_k=max(top_k * 8, 40))
            if query.lower() in str(entry).lower()
        ]
        if keyword_matches:
            results.append("\n### L1 关键词匹配")
            for m in keyword_matches[:top_k]:
                results.append(f"- {m}")
    except Exception as exc:
        results.append(f"\n### L1 Index: 搜索失败 ({exc})")

    # B. Episodic archive (narrative similarity)
    try:
        from agents.memory.episodic_memory import EpisodicMemoryArchive
        archive = EpisodicMemoryArchive()
        hits = archive.search(query, top_k=top_k)
        if hits:
            results.append(f"\n### 经验档案 ({len(hits)} 条)")
            for hit in hits[:top_k]:
                results.append(
                    f"- [{hit.record.source_tool}] {hit.record.narrative_summary[:100]} "
                    f"(score={hit.score:.2f})"
                )
    except Exception as exc:
        results.append(f"\n### 经验档案: 搜索失败 ({exc})")

    # C. Shell L2 quintuple graph
    try:
        from summer_memory.quintuple_graph import get_all_quintuples, query_graph_by_keywords

        quintuple_hits = list(query_graph_by_keywords([query]))
        if not quintuple_hits:
            lowered_query = query.lower()
            for row in get_all_quintuples():
                row_text = " ".join(str(part or "") for part in row).lower()
                if lowered_query and lowered_query in row_text:
                    quintuple_hits.append(tuple(row))

        if quintuple_hits:
            results.append(f"\n### Shell L2 五元组图谱 ({len(quintuple_hits[:top_k])} 条)")
            for row in quintuple_hits[:top_k]:
                if isinstance(row, (list, tuple)) and len(row) >= 5:
                    results.append(f"- {row[0]}({row[1]}) —[{row[2]}]→ {row[3]}({row[4]})")
    except Exception as exc:
        results.append(f"\n### Shell L2 五元组图谱: 搜索失败 ({exc})")

    if len(results) == 1:
        results.append("\n未找到相关记忆。")

    return "\n".join(results)


# ── 6. list_tasks ─────────────────────────────────────────────


def _handle_list_tasks(
    args: Dict[str, Any],
    *,
    project_root: Path,
) -> str:
    """List tasks from the TaskBoard."""
    status_filter = str(args.get("status_filter", "all")).strip().lower()
    status_alias = {
        "completed": "done",
        "in_progress": "in_progress",
        "pending": "pending",
        "blocked": "blocked",
        "done": "done",
        "failed": "failed",
    }
    results: List[str] = ["## 当前任务列表"]

    board: Optional[Any] = None
    try:
        from agents.runtime.task_board import TaskBoardEngine

        board = TaskBoardEngine(
            boards_dir=str(project_root / "memory" / "working" / "boards"),
            db_path=str(project_root / "scratch" / "runtime" / "task_boards.db"),
        )
        resolved_status = status_alias.get(status_filter, "")
        if status_filter == "all":
            tasks = board.query_tasks()
        elif resolved_status:
            tasks = board.query_tasks(status=resolved_status)
        else:
            tasks = []

        if status_filter != "all" and not resolved_status:
            results.append(f"\n无效状态过滤器: {status_filter}")

        if not tasks:
            results.append(f"\n无{'匹配' if status_filter != 'all' else '活跃'}任务。")
        else:
            results.append(f"\n共 {len(tasks)} 个任务 (filter={status_filter}):\n")
            for t in tasks[:20]:
                task_id = t.get("task_id", "?")
                status = t.get("status", "unknown")
                title = t.get("title", t.get("description", ""))[:60]
                assignee = t.get("assigned_to", "")
                results.append(
                    f"- [{status}] {task_id}: {title}"
                    + (f" → {assignee}" if assignee else "")
                )
    except Exception as exc:
        results.append(f"\nTaskBoard 不可用: {exc}")
    finally:
        if board is not None:
            try:
                board.close()
            except Exception:
                pass

    return "\n".join(results)


# ── 7. search_web ─────────────────────────────────────────────


def _handle_search_web(args: Dict[str, Any]) -> str:
    """Web search via the online_search MCP service (SearXNG backend)."""
    query = str(args.get("query", "")).strip()
    if not query:
        raise ValueError("search_web: 缺少 query 参数")

    import asyncio
    import concurrent.futures

    def _run_async_blocking(async_fn: Any, *fn_args: Any, timeout: float = 30.0) -> Any:
        """Run coroutine without mutating the process-global default event loop."""

        def _runner() -> Any:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(async_fn(*fn_args))
            finally:
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception:
                    pass
                loop.close()

        try:
            running_loop = asyncio.get_running_loop()
            if running_loop and running_loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="shell-web-search") as pool:
                    future = pool.submit(_runner)
                    return future.result(timeout=timeout)
        except RuntimeError:
            pass

        return _runner()

    try:
        from mcpserver.mcp_manager import get_mcp_manager

        manager = get_mcp_manager()
        tool_call = {
            "tool_name": "search_web",
            "query": query,
        }
        result = _run_async_blocking(manager.unified_call, "online_search", tool_call, timeout=30.0)

        if result:
            import json as _json
            try:
                parsed = _json.loads(result) if isinstance(result, str) else result
                if isinstance(parsed, dict) and parsed.get("status") == "ok":
                    data = parsed.get("data", {})
                    results_list = data.get("results", [])
                    lines = [f"## 搜索: {query}", f"共 {len(results_list)} 条结果\n"]
                    for i, r in enumerate(results_list, 1):
                        title = r.get("title", "")
                        url = r.get("url", "")
                        content = r.get("content", "")[:200]
                        lines.append(f"{i}. **{title}**\n   {url}\n   {content}\n")
                    return "\n".join(lines)
                elif isinstance(parsed, dict) and parsed.get("status") == "error":
                    return f"## 搜索: {query}\n\n⚠️ 搜索失败: {parsed.get('message', '未知错误')}"
            except Exception:
                pass
            # Return raw result if parsing fails
            return str(result)[:3000]
        return f"## 搜索: {query}\n\n搜索服务无返回。"
    except ImportError:
        return (
            f"## 搜索: {query}\n\n"
            "⚠️ MCP 服务未加载（mcpserver 未初始化）。\n"
            "请确保 MCP Server 已启动。"
        )
    except Exception as exc:
        return f"## 搜索: {query}\n\n⚠️ 搜索失败: {exc}"


__all__ = [
    "TOOL_DEF_LIST_TASKS",
    "TOOL_DEF_MEMORY_GREP",
    "TOOL_DEF_MEMORY_LIST",
    "TOOL_DEF_READ_FILE",
    "TOOL_DEF_SEARCH_MEMORY",
    "TOOL_DEF_SEARCH_WEB",
    "TOOL_DEF_SYSTEM_STATUS",
    "get_shell_tool_definitions",
    "handle_shell_tool",
    "is_shell_tool_supported",
    "normalize_shell_tool_name",
]
