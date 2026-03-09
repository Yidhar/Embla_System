"""Custom tool sandbox, validation, persistence, and execution.

Dev agent can create custom Python tools via ``create_tool`` meta-tool.
Tools are:
  - validated via AST scanning for forbidden nodes/names
  - executed in a sandboxed ``exec()`` with restricted builtins
  - persisted to ``memory/custom_tools/*.json``
  - auto-loaded on session startup into the ToolRegistry
"""

from __future__ import annotations

import ast
import json
import logging
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# ── Sandbox Configuration ─────────────────────────────────────

SANDBOX_ALLOWED_BUILTINS = {
    "len": len,
    "range": range,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "sorted": sorted,
    "min": min,
    "max": max,
    "sum": sum,
    "enumerate": enumerate,
    "zip": zip,
    "map": map,
    "filter": filter,
    "any": any,
    "all": all,
    "isinstance": isinstance,
    "round": round,
    "abs": abs,
    "print": print,
    "True": True,
    "False": False,
    "None": None,
    "type": type,
    "repr": repr,
    "hasattr": hasattr,
    "chr": chr,
    "ord": ord,
}

SANDBOX_FORBIDDEN_AST_NODES = (
    ast.Import,
    ast.ImportFrom,
    ast.Global,
    ast.Nonlocal,
)

SANDBOX_FORBIDDEN_NAMES = frozenset({
    "__import__",
    "eval",
    "exec",
    "compile",
    "open",
    "globals",
    "locals",
    "getattr",
    "setattr",
    "delattr",
    "__builtins__",
    "breakpoint",
    "exit",
    "quit",
    "input",
    "__subclasses__",
})

_DEFAULT_TIMEOUT_S = 5
_MAX_CODE_LENGTH = 10_000
_TOOL_NAME_PATTERN = r"^[a-z][a-z0-9_]{1,30}$"
_CUSTOM_TOOLS_DIR = "custom_tools"


# ── AST Validation ────────────────────────────────────────────

def validate_tool_code(code: str) -> Tuple[bool, List[str]]:
    """Validate custom tool code via AST scanning.

    Returns (ok, errors).
    """
    errors: List[str] = []

    if not code or not code.strip():
        return False, ["E_EMPTY_CODE"]

    if len(code) > _MAX_CODE_LENGTH:
        return False, [f"E_CODE_TOO_LONG: max {_MAX_CODE_LENGTH} chars"]

    # Parse AST
    try:
        tree = ast.parse(code, filename="<custom_tool>", mode="exec")
    except SyntaxError as exc:
        return False, [f"E_SYNTAX_ERROR: {exc}"]

    # Walk AST for forbidden nodes
    for node in ast.walk(tree):
        if isinstance(node, SANDBOX_FORBIDDEN_AST_NODES):
            node_type = type(node).__name__
            lineno = getattr(node, "lineno", "?")
            errors.append(f"E_FORBIDDEN_NODE: {node_type} at line {lineno}")

        # Check for forbidden names in identifiers
        if isinstance(node, ast.Name) and node.id in SANDBOX_FORBIDDEN_NAMES:
            errors.append(f"E_FORBIDDEN_NAME: '{node.id}' at line {node.lineno}")
        if isinstance(node, ast.Attribute) and node.attr in SANDBOX_FORBIDDEN_NAMES:
            errors.append(f"E_FORBIDDEN_ATTR: '.{node.attr}' at line {node.lineno}")

    # Check that run(args) is defined
    has_run_func = False
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            has_run_func = True
            break

    if not has_run_func:
        errors.append("E_MISSING_RUN: code must define 'def run(args): ...'")

    return len(errors) == 0, errors


# ── Sandboxed Execution ───────────────────────────────────────

class _SandboxTimeout(Exception):
    pass


def sandbox_exec(
    code: str,
    args: Dict[str, Any],
    *,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
) -> Dict[str, Any]:
    """Execute custom tool code in a restricted sandbox.

    The code must define ``run(args) -> dict``.
    Returns the result dict or an error dict.
    """
    sandbox_globals: Dict[str, Any] = {"__builtins__": dict(SANDBOX_ALLOWED_BUILTINS)}
    result_holder: Dict[str, Any] = {}
    error_holder: Dict[str, Any] = {}

    def _target() -> None:
        try:
            exec(code, sandbox_globals)  # noqa: S102
            run_func = sandbox_globals.get("run")
            if not callable(run_func):
                error_holder["error"] = "E_RUN_NOT_CALLABLE"
                return
            result = run_func(args)
            if isinstance(result, dict):
                result_holder.update(result)
            else:
                result_holder["result"] = result
        except _SandboxTimeout:
            error_holder["error"] = "E_TIMEOUT"
        except Exception as exc:
            error_holder["error"] = f"E_RUNTIME: {type(exc).__name__}: {exc}"

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout=timeout_s)

    if thread.is_alive():
        return {"status": "error", "code": "E_TIMEOUT",
                "error": f"execution exceeded {timeout_s}s timeout"}

    if error_holder:
        return {"status": "error", "code": error_holder.get("error", "E_UNKNOWN"),
                "error": error_holder.get("error", "")}

    return {"status": "ok", **result_holder}


# ── Persistence ───────────────────────────────────────────────

def _resolve_custom_tools_dir(memory_root: Optional[str] = None) -> Path:
    if memory_root:
        return Path(memory_root) / _CUSTOM_TOOLS_DIR
    return Path("memory") / _CUSTOM_TOOLS_DIR


def save_custom_tool(
    spec: Dict[str, Any],
    *,
    memory_root: Optional[str] = None,
) -> Path:
    """Save a custom tool spec to disk. Returns the saved file path."""
    tools_dir = _resolve_custom_tools_dir(memory_root)
    tools_dir.mkdir(parents=True, exist_ok=True)
    name = spec["name"]
    file_path = tools_dir / f"{name}.json"
    file_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return file_path


def load_custom_tools(
    memory_root: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Load all custom tool specs from disk."""
    tools_dir = _resolve_custom_tools_dir(memory_root)
    if not tools_dir.is_dir():
        return []
    specs: List[Dict[str, Any]] = []
    for file_path in sorted(tools_dir.glob("*.json")):
        try:
            spec = json.loads(file_path.read_text(encoding="utf-8"))
            if isinstance(spec, dict) and spec.get("name") and spec.get("code"):
                specs.append(spec)
        except Exception as exc:
            logger.warning("Failed to load custom tool %s: %s", file_path, exc)
    return specs


def delete_custom_tool(
    name: str,
    *,
    memory_root: Optional[str] = None,
) -> bool:
    """Delete a custom tool spec from disk."""
    tools_dir = _resolve_custom_tools_dir(memory_root)
    file_path = tools_dir / f"{name}.json"
    if file_path.is_file():
        file_path.unlink()
        return True
    return False


# ── Schema Provider ───────────────────────────────────────────

# Module-level store for loaded custom tools (populated by register function)
_LOADED_CUSTOM_TOOLS: Dict[str, Dict[str, Any]] = {}


def get_custom_tool_definitions(
    tool_names: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Return OpenAI-style schemas for the requested custom tools."""
    if tool_names is None:
        names = list(_LOADED_CUSTOM_TOOLS.keys())
    else:
        names = list(tool_names)

    definitions: List[Dict[str, Any]] = []
    for name in names:
        spec = _LOADED_CUSTOM_TOOLS.get(name)
        if not spec:
            continue
        definitions.append({
            "name": spec["name"],
            "description": spec.get("description", f"Custom tool: {name}"),
            "parameters": spec.get("params_schema", {"type": "object", "properties": {}}),
        })
    return definitions


# ── Custom Tool Call Handler ──────────────────────────────────

def handle_custom_tool_call(
    name: str,
    args: Dict[str, Any],
    *,
    memory_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a custom tool by name with the given arguments."""
    spec = _LOADED_CUSTOM_TOOLS.get(name)
    if not spec:
        # Try loading from disk
        tools = load_custom_tools(memory_root=memory_root)
        for t in tools:
            if t["name"] == name:
                spec = t
                break
    if not spec:
        return {"status": "error", "code": "E_TOOL_NOT_FOUND",
                "error": f"custom tool '{name}' not found"}

    code = spec.get("code", "")
    ok, errors = validate_tool_code(code)
    if not ok:
        return {"status": "error", "code": "E_VALIDATION_FAILED",
                "errors": errors}

    result = sandbox_exec(code, args)
    result["tool_name"] = name
    return result


# ── Registration Helper ──────────────────────────────────────

def register_custom_tools_into_registry(
    registry: Any,
    *,
    memory_root: Optional[str] = None,
) -> List[str]:
    """Load custom tools from disk and register them as a 'custom' domain.

    Returns the list of custom tool names registered.
    """
    specs = load_custom_tools(memory_root=memory_root)
    _LOADED_CUSTOM_TOOLS.clear()
    tool_names: List[str] = []
    all_keywords: List[str] = []

    for spec in specs:
        name = spec["name"]
        _LOADED_CUSTOM_TOOLS[name] = spec
        tool_names.append(name)
        all_keywords.extend(spec.get("keywords", []))

    if tool_names:
        registry.register_domain(
            "custom",
            "agent-created custom tools",
            list(set(all_keywords)) or ["custom", "agent", "tool"],
            tool_names,
            get_custom_tool_definitions,
        )

    return tool_names


__all__ = [
    "delete_custom_tool",
    "get_custom_tool_definitions",
    "handle_custom_tool_call",
    "load_custom_tools",
    "register_custom_tools_into_registry",
    "sandbox_exec",
    "save_custom_tool",
    "validate_tool_code",
]
