"""Native runtime tool definitions with proper descriptions.

These tools are the execution-layer primitives that Dev/Review agents
use to interact with the project workspace, filesystem, and git.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Sequence

_NATIVE_TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    # ── native_read ───────────────────────────────────────────
    {
        "name": "read_file",
        "description": "Read the contents of a file at the given path.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "file path relative to workspace root"},
                "mode": {"type": "string", "enum": ["line_range", "grep", "jsonpath"]},
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_files",
        "description": "List files and directories under a given path.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "glob": {"type": "string"},
            },
        },
    },
    {
        "name": "get_cwd",
        "description": "Get the current working directory of the workspace.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "file_ast_skeleton",
        "description": "Parse a source file and return its AST skeleton (classes, functions, imports).",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "file_ast_chunk_read",
        "description": "Read a specific AST chunk (function/class body) from a source file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "target_path": {"type": "string", "description": "dotted path to AST node"},
            },
            "required": ["path", "target_path"],
        },
    },
    {
        "name": "artifact_reader",
        "description": "Read a previously stored artifact by its ID.",
        "parameters": {
            "type": "object",
            "properties": {"artifact_id": {"type": "string"}},
            "required": ["artifact_id"],
        },
    },
    # ── native_write ──────────────────────────────────────────
    {
        "name": "write_file",
        "description": "Write content to a file. Supports overwrite and append modes.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "mode": {"type": "string", "enum": ["overwrite", "append"]},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "workspace_txn_apply",
        "description": "Apply a batch of file changes as an atomic workspace transaction.",
        "parameters": {
            "type": "object",
            "properties": {
                "changes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                            "mode": {"type": "string", "enum": ["overwrite", "append"]},
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            "required": ["changes"],
        },
    },
    # ── native_exec ───────────────────────────────────────────
    {
        "name": "run_cmd",
        "description": "Run a shell command in the workspace and return stdout/stderr.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 1200},
            },
            "required": ["command"],
        },
    },
    {
        "name": "os_bash",
        "description": "Execute a bash command (Linux/macOS) or PowerShell (Windows).",
        "parameters": {
            "type": "object",
            "properties": {
                "cmd": {"type": "string"},
                "cwd": {"type": "string"},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 1200},
            },
            "required": ["cmd"],
        },
    },
    {
        "name": "python_repl",
        "description": "Execute Python code in a sandboxed REPL and return the result.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "sandbox": {"type": "string", "enum": ["restricted", "docker"]},
            },
            "required": ["code"],
        },
    },
    # ── native_search ─────────────────────────────────────────
    {
        "name": "search_keyword",
        "description": "Search for a keyword or regex pattern across project files.",
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string"},
                "search_path": {"type": "string"},
                "case_sensitive": {"type": "boolean"},
                "use_regex": {"type": "boolean"},
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "query_docs",
        "description": "Query project documentation or knowledge base.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    # ── native_git ────────────────────────────────────────────
    {
        "name": "git_status",
        "description": "Show the working tree status (modified, staged, untracked files).",
        "parameters": {
            "type": "object",
            "properties": {
                "short": {"type": "boolean"},
                "branch": {"type": "boolean"},
                "porcelain": {"type": "boolean"},
            },
        },
    },
    {
        "name": "git_diff",
        "description": "Show changes between commits, working tree, and staging area.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "ref": {"type": "string"},
                "base_ref": {"type": "string"},
            },
        },
    },
    {
        "name": "git_log",
        "description": "Show commit history with optional filtering.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "since": {"type": "string"},
                "pretty": {"type": "string"},
            },
        },
    },
    {
        "name": "git_show",
        "description": "Show contents of a specific commit or object.",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["ref"],
        },
    },
    {
        "name": "git_blame",
        "description": "Show line-by-line authorship of a file.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "git_grep",
        "description": "Search through tracked files in the git repository.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "git_changed_files",
        "description": "List files changed between two refs or in the working tree.",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {"type": "string"},
                "base_ref": {"type": "string"},
            },
        },
    },
    {
        "name": "git_checkout_file",
        "description": "Restore a file from a specific commit or HEAD.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "ref": {"type": "string"},
            },
            "required": ["path"],
        },
    },
    # ── native_control ────────────────────────────────────────
    {
        "name": "sleep_and_watch",
        "description": "Pause execution and watch a log file for changes.",
        "parameters": {
            "type": "object",
            "properties": {
                "log_file": {"type": "string"},
                "timeout_seconds": {"type": "integer"},
            },
        },
    },
    {
        "name": "killswitch_plan",
        "description": "Emergency stop: freeze the current execution plan.",
        "parameters": {"type": "object", "properties": {}},
    },
]

_NATIVE_TOOL_DEF_BY_NAME = {d["name"]: d for d in _NATIVE_TOOL_DEFINITIONS}


def is_native_tool(name: str) -> bool:
    return name in _NATIVE_TOOL_DEF_BY_NAME


def get_native_tool_definitions(tool_names: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Return full schemas for the requested native tools (or all if None)."""
    if tool_names is None:
        return deepcopy(_NATIVE_TOOL_DEFINITIONS)
    return [deepcopy(_NATIVE_TOOL_DEF_BY_NAME[n]) for n in tool_names if n in _NATIVE_TOOL_DEF_BY_NAME]


__all__ = [
    "get_native_tool_definitions",
    "is_native_tool",
]
