"""L1 memory tool schemas + handlers.

These tools expose the filesystem-backed Layer-1 memory store using precise,
optimistic-lock editing primitives.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Sequence

from agents.memory.l1_memory import L1MemoryConflictError, L1MemoryManager
from agents.runtime.tool_profiles import MEMORY_TOOL_NAMES, normalize_memory_tool_name

_MEMORY_TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "memory_read",
        "description": "Read a memory markdown file, optionally by line range.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
        },
    },
    {
        "name": "memory_write",
        "description": "Create or overwrite a memory markdown file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "overwrite": {"type": "boolean"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "memory_list",
        "description": "List memory files by scope.",
        "parameters": {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["all", "working", "episodic", "domain", "deprecated"]},
                "pattern": {"type": "string"},
                "recursive": {"type": "boolean"},
                "include_deprecated": {"type": "boolean"},
            },
        },
    },
    {
        "name": "memory_delete",
        "description": "Soft-delete a memory file by archiving it into `.deprecated/`.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "memory_grep",
        "description": "Search matching lines across memory markdown files.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "scope": {"type": "string", "enum": ["all", "working", "episodic", "domain", "deprecated"]},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 200},
                "use_regex": {"type": "boolean"},
                "case_sensitive": {"type": "boolean"},
                "include_deprecated": {"type": "boolean"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "memory_search",
        "description": "Keyword search over L1 memory files and indices.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "scope": {"type": "string", "enum": ["all", "working", "episodic", "domain", "deprecated"]},
                "tags": {"type": "array", "items": {"type": "string"}},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 100},
                "include_deprecated": {"type": "boolean"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_index",
        "description": "Rebuild episodic/domain memory indices.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "memory_patch",
        "description": "Apply optimistic-lock line edits to a memory file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "start_line": {"type": "integer", "minimum": 1},
                            "end_line": {"type": "integer", "minimum": 1},
                            "old_content": {"type": "string"},
                            "new_content": {"type": "string"},
                        },
                        "required": ["start_line", "end_line", "old_content", "new_content"],
                    },
                },
            },
            "required": ["path", "edits"],
        },
    },
    {
        "name": "memory_insert",
        "description": "Insert new content before or after a given line.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "line": {"type": "integer", "minimum": 1},
                "content": {"type": "string"},
                "position": {"type": "string", "enum": ["before", "after"]},
            },
            "required": ["path", "line", "content"],
        },
    },
    {
        "name": "memory_append",
        "description": "Append content to a memory file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "memory_replace",
        "description": "Replace literal or regex matches inside a memory file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
                "pattern": {"type": "string"},
                "use_regex": {"type": "boolean"},
                "count": {"type": "integer", "minimum": 0},
                "expected_count": {"type": "integer", "minimum": 0},
            },
            "required": ["path", "new_text"],
        },
    },
    {
        "name": "memory_deprecate",
        "description": "Mark a memory file as deprecated without deleting it.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "reason": {"type": "string"},
                "replacement_path": {"type": "string"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "memory_tag",
        "description": "Add or replace markdown tags for a memory file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "mode": {"type": "string", "enum": ["append", "replace"]},
            },
            "required": ["path", "tags"],
        },
    },
    {
        "name": "memory_link",
        "description": "Append a markdown link under a related-links section.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "target": {"type": "string"},
                "label": {"type": "string"},
                "section_title": {"type": "string"},
            },
            "required": ["path", "target"],
        },
    },
]
_MEMORY_TOOL_DEF_BY_NAME = {item["name"]: item for item in _MEMORY_TOOL_DEFINITIONS}


def is_memory_tool(tool_name: str) -> bool:
    return normalize_memory_tool_name(tool_name) in MEMORY_TOOL_NAMES


def get_memory_tool_definitions(tool_names: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Return full schemas only for the requested memory tools."""
    if tool_names is None:
        names = [item["name"] for item in _MEMORY_TOOL_DEFINITIONS]
    else:
        names = [normalize_memory_tool_name(name) for name in tool_names]
    definitions: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for name in names:
        if name in seen or name not in _MEMORY_TOOL_DEF_BY_NAME:
            continue
        seen.add(name)
        definitions.append(deepcopy(_MEMORY_TOOL_DEF_BY_NAME[name]))
    return definitions


def handle_memory_tool(
    tool_name: str,
    arguments: Dict[str, Any],
    *,
    manager: Optional[L1MemoryManager] = None,
    memory_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute one L1 memory tool call."""
    normalized_name = normalize_memory_tool_name(tool_name)
    if normalized_name not in MEMORY_TOOL_NAMES:
        return {"status": "error", "error": f"unknown_memory_tool:{tool_name}", "tool_name": normalized_name}

    mgr = manager or L1MemoryManager(memory_root=memory_root)
    args = arguments if isinstance(arguments, dict) else {}
    try:
        if normalized_name == "memory_read":
            path = str(args.get("path") or "").strip()
            content = mgr.read_memory_file(path)
            lines = content.splitlines()
            start_line = int(args.get("start_line") or 0)
            end_line = int(args.get("end_line") or 0)
            if start_line > 0 or end_line > 0:
                start_idx = max(start_line or 1, 1) - 1
                end_idx = min(end_line or len(lines), len(lines))
                content = "\n".join(lines[start_idx:end_idx])
            return {"status": "success", "tool_name": normalized_name, "path": path, "content": content}
        if normalized_name == "memory_write":
            written = mgr.write_memory_file(
                str(args.get("path") or "").strip(),
                str(args.get("content") or ""),
                overwrite=bool(args.get("overwrite", True)),
            )
            return {"status": "success", "tool_name": normalized_name, "path": mgr._to_relative_path(written)}
        if normalized_name == "memory_list":
            items = mgr.list_memory(
                scope=str(args.get("scope") or "all"),
                pattern=str(args.get("pattern") or "*.md"),
                recursive=bool(args.get("recursive", True)),
                include_deprecated=bool(args.get("include_deprecated", False)),
            )
            return {"status": "success", "tool_name": normalized_name, "items": items, "count": len(items)}
        if normalized_name == "memory_delete":
            result = mgr.delete_memory_file(str(args.get("path") or "").strip())
            result.update({"status": "success", "tool_name": normalized_name})
            return result
        if normalized_name == "memory_grep":
            matches = mgr.grep_memory(
                str(args.get("pattern") or ""),
                scope=str(args.get("scope") or "all"),
                top_k=int(args.get("top_k") or 20),
                use_regex=bool(args.get("use_regex", False)),
                case_sensitive=bool(args.get("case_sensitive", False)),
                include_deprecated=bool(args.get("include_deprecated", False)),
            )
            return {"status": "success", "tool_name": normalized_name, "matches": matches, "count": len(matches)}
        if normalized_name == "memory_search":
            hits = mgr.search_memory(
                str(args.get("query") or ""),
                scope=str(args.get("scope") or "all"),
                top_k=int(args.get("top_k") or 5),
                tags=args.get("tags") if isinstance(args.get("tags"), list) else None,
                include_deprecated=bool(args.get("include_deprecated", False)),
            )
            return {"status": "success", "tool_name": normalized_name, "hits": hits, "count": len(hits)}
        if normalized_name == "memory_index":
            stats = mgr.rebuild_all_indices()
            return {"status": "success", "tool_name": normalized_name, "stats": stats}
        if normalized_name == "memory_patch":
            result = mgr.patch_memory_file(
                str(args.get("path") or "").strip(),
                args.get("edits") if isinstance(args.get("edits"), list) else [],
            )
            result.update({"status": "success", "tool_name": normalized_name})
            return result
        if normalized_name == "memory_insert":
            result = mgr.insert_memory_content(
                str(args.get("path") or "").strip(),
                line=int(args.get("line") or 0),
                content=str(args.get("content") or ""),
                position=str(args.get("position") or "after"),
            )
            result.update({"status": "success", "tool_name": normalized_name})
            return result
        if normalized_name == "memory_append":
            result = mgr.append_memory_content(
                str(args.get("path") or "").strip(),
                str(args.get("content") or ""),
            )
            result.update({"status": "success", "tool_name": normalized_name})
            return result
        if normalized_name == "memory_replace":
            result = mgr.replace_memory_content(
                str(args.get("path") or "").strip(),
                old_text=str(args.get("old_text") or ""),
                new_text=str(args.get("new_text") or ""),
                pattern=str(args.get("pattern") or ""),
                use_regex=bool(args.get("use_regex", False)),
                count=args.get("count"),
                expected_count=args.get("expected_count"),
            )
            result.update({"status": "success", "tool_name": normalized_name})
            return result
        if normalized_name == "memory_deprecate":
            result = mgr.deprecate_memory_file(
                str(args.get("path") or "").strip(),
                reason=str(args.get("reason") or ""),
                replacement_path=str(args.get("replacement_path") or ""),
            )
            result.update({"status": "success", "tool_name": normalized_name})
            return result
        if normalized_name == "memory_tag":
            result = mgr.tag_memory_file(
                str(args.get("path") or "").strip(),
                tags=args.get("tags") if isinstance(args.get("tags"), list) else [],
                mode=str(args.get("mode") or "append"),
            )
            result.update({"status": "success", "tool_name": normalized_name})
            return result
        if normalized_name == "memory_link":
            result = mgr.link_memory_file(
                str(args.get("path") or "").strip(),
                target=str(args.get("target") or "").strip(),
                label=str(args.get("label") or "").strip(),
                section_title=str(args.get("section_title") or "## 相关链接"),
            )
            result.update({"status": "success", "tool_name": normalized_name})
            return result
    except L1MemoryConflictError as exc:
        return {"status": "conflict", "tool_name": normalized_name, "error": str(exc)}
    except Exception as exc:
        return {"status": "error", "tool_name": normalized_name, "error": str(exc)}

    return {"status": "error", "tool_name": normalized_name, "error": f"unhandled_memory_tool:{normalized_name}"}


__all__ = [
    "get_memory_tool_definitions",
    "handle_memory_tool",
    "is_memory_tool",
]
