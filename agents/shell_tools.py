"""Shell Agent read-only tool definitions and handlers.

Canonical Shell tools:
  1. memory_read      — read project files (path + optional line range)
  2. memory_list      — list L1 memory files by scope
  3. memory_grep      — grep L1 memory files by keyword/regex
  4. memory_search    — unified L1 index + episodic archive + Shell L2 quintuple search
  5. get_system_status — runtime posture + agent stats + git status
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

from core.event_bus.runtime_views import build_topic_event_posture_summary

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
        "Get the current system status including runtime posture, "
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

_SYSTEM_STATUS_RUNTIME_POSTURE_EVENTS_LIMIT = 200


def _status_label(value: Any) -> str:
    text = str(value or "").strip()
    return text or "unknown"


def _format_seconds(value: Any) -> str:
    if isinstance(value, bool):
        return "N/A"
    if isinstance(value, (int, float)):
        return f"{float(value):.1f}s"
    return "N/A"


def _load_runtime_posture_payload(*, project_root: Path) -> Dict[str, Any]:
    try:
        from apiserver.routes_ops import _ops_build_runtime_posture_payload

        payload = _ops_build_runtime_posture_payload(
            events_limit=_SYSTEM_STATUS_RUNTIME_POSTURE_EVENTS_LIMIT,
            repo_root=project_root,
        )
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        logger.debug("get_system_status runtime posture load failed: %s", exc, exc_info=True)
        return {}


def _build_runtime_posture_lines(*, project_root: Path) -> List[str]:
    payload = _load_runtime_posture_payload(project_root=project_root)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    route_quality = summary.get("route_quality") if isinstance(summary.get("route_quality"), dict) else {}
    runtime_lease = summary.get("runtime_lease") if isinstance(summary.get("runtime_lease"), dict) else {}
    lock_status = summary.get("lock_status") if isinstance(summary.get("lock_status"), dict) else {}

    event_posture = build_topic_event_posture_summary(project_root)

    lines: List[str] = []
    if payload:
        lines.append("## Runtime Posture")
        overall_status = _status_label(summary.get("overall_status") or payload.get("severity"))
        lines.append(f"- 总体状态: {overall_status}")
        reason_code = str(payload.get("reason_code") or "").strip()
        reason_text = str(payload.get("reason_text") or "").strip()
        if reason_code or reason_text:
            if reason_code and reason_text:
                lines.append(f"- 原因: {reason_code} — {reason_text}")
            else:
                lines.append(f"- 原因: {reason_code or reason_text}")
        generated_at = str(payload.get("generated_at") or "").strip()
        if generated_at:
            lines.append(f"- 生成时间: {generated_at}")

        control_plane_mode = str(summary.get("control_plane_mode") or "").strip() or "unknown"
        control_plane_status = _status_label(summary.get("control_plane_mode_status"))
        lines.append(f"- 控制面: {control_plane_mode} ({control_plane_status})")

        lease_status = _status_label(runtime_lease.get("status"))
        lease_state = str(runtime_lease.get("state") or lock_status.get("state") or "").strip() or "unknown"
        lease_owner = str(runtime_lease.get("owner_id") or lock_status.get("owner_id") or "").strip() or "N/A"
        lease_remaining = _format_seconds(runtime_lease.get("value"))
        lines.append(
            f"- 租约: {lease_status} / state={lease_state} / owner={lease_owner} / remaining={lease_remaining}"
        )

        lines.append(
            "- 守护链: "
            f"brainstem={_status_label(summary.get('brainstem_control_plane_status'))}, "
            f"watchdog={_status_label(summary.get('watchdog_daemon_status'))}, "
            f"process_guard={_status_label(summary.get('process_guard_status'))}"
        )
        lines.append(
            "- 安全链: "
            f"killswitch={_status_label(summary.get('killswitch_guard_status'))}, "
            f"budget={_status_label(summary.get('budget_guard_status'))}, "
            f"immutable_dna={_status_label(summary.get('immutable_dna_status'))}, "
            f"audit={_status_label(summary.get('audit_ledger_status'))}"
        )
        lines.append(
            "- 执行链: "
            f"os_sandbox={_status_label(summary.get('os_sandbox_runtime_status'))}, "
            f"boxlite={_status_label(summary.get('boxlite_runtime_status'))}"
        )
        lines.append(
            "- 编排质量: "
            f"route_quality={_status_label(route_quality.get('status'))}, "
            f"execution_bridge={_status_label(summary.get('execution_bridge_governance_status'))}, "
            f"agentic_loop={_status_label(summary.get('agentic_loop_completion_status'))}, "
            f"core_spawn={_status_label(summary.get('core_child_spawn_deferred_status'))}, "
            f"vision={_status_label(summary.get('vision_multimodal_status'))}"
        )
        dispatch_to_core_rate = route_quality.get("dispatch_to_core_rate")
        if isinstance(dispatch_to_core_rate, (int, float)):
            lines.append(f"- Shell→Core 升级率: {float(dispatch_to_core_rate):.3f}")

    if str(event_posture.get("status") or "") == "ok":
        if not lines:
            lines.append("## Runtime Posture")
        lines.append(
            "- 事件面: "
            f"total={int(event_posture.get('total_events') or 0)}, "
            f"warnings={int(event_posture.get('warning_events') or 0)}, "
            f"errors={int(event_posture.get('error_events') or 0)}, "
            f"latest={event_posture.get('last_event_type') or 'N/A'}, "
            f"updated_at={event_posture.get('last_event_timestamp') or event_posture.get('generated_at') or 'N/A'}"
        )
        return lines

    if not lines:
        reason_text = str(event_posture.get("reason_text") or "").strip()
        if reason_text:
            return [f"## Runtime Posture: 未初始化（{reason_text}）"]
        return ["## Runtime Posture: 未初始化（事件数据库不存在）"]

    return lines


def _handle_get_system_status(*, project_root: Path) -> str:
    """Collect system status from multiple sources."""
    sections: List[str] = []

    # A. Runtime posture
    sections.extend(_build_runtime_posture_lines(project_root=project_root))

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
        from agents.runtime.mcp_client import get_mcp_pool

        pool = get_mcp_pool()
        if not pool:
            return (
                f"## 搜索: {query}\n\n"
                "⚠️ MCP 客户端池未初始化。\n"
                "请确保 MCP Server 已配置在 mcp_servers.json 中。"
            )
        result = _run_async_blocking(pool.call_tool, "online_search", "search_web", {"query": query}, timeout=30.0)

        if result:
            import json as _json
            try:
                parsed = result if isinstance(result, dict) else _json.loads(result)
                status = parsed.get("status", "")
                if status == "ok":
                    data = parsed.get("result", "")
                    lines = [f"## 搜索: {query}", f"\n{data}"]
                    return "\n".join(lines)
                elif status == "error":
                    return f"## 搜索: {query}\n\n⚠️ 搜索失败: {parsed.get('error', '未知错误')}"
            except Exception:
                pass
            # Return raw result if parsing fails
            return str(result)[:3000]
        return f"## 搜索: {query}\n\n搜索服务无返回。"
    except ImportError:
        return (
            f"## 搜索: {query}\n\n"
            "⚠️ MCP 客户端未加载。\n"
            "请确保 agents.runtime.mcp_client 可用。"
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
