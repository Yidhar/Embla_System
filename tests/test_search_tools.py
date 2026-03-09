"""Tests for general-purpose progressive tool discovery + custom tools.

Covers:
- ToolRegistry: multi-source registration, BM25 search
- ToolActivationState: role-based activation, domain access
- Meta-tools: search_tools, activate_domain, list_domains, list_active_tools, create_tool
- Error codes
- Native + memory tool coverage
- Custom tools: validation, sandbox, persistence, discovery, execution
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from agents.runtime.tool_discovery import (
    META_TOOL_NAMES,
    ROLE_DOMAIN_ACCESS,
    ROLE_CREATE_TOOL_ACCESS,
    ToolActivationState,
    ToolRegistry,
    build_default_registry,
    get_meta_tool_definitions,
    handle_meta_tool,
)

from agents.runtime.custom_tools import (
    validate_tool_code,
    sandbox_exec,
    save_custom_tool,
    load_custom_tools,
    handle_custom_tool_call,
    register_custom_tools_into_registry,
    _LOADED_CUSTOM_TOOLS,
)


# ── ToolRegistry ──────────────────────────────────────────────


class TestToolRegistry:
    def test_build_default_has_memory_domains(self) -> None:
        reg = build_default_registry()
        assert "memory_read" in reg.domain_names
        assert "memory_write" in reg.domain_names

    def test_build_default_has_native_domains(self) -> None:
        reg = build_default_registry()
        assert "native_read" in reg.domain_names
        assert "native_exec" in reg.domain_names

    def test_all_tool_names_count(self) -> None:
        reg = build_default_registry()
        all_tools = reg.all_tool_names()
        assert len(all_tools) >= 37  # 14 memory + 23 native (+ any custom)

    def test_get_schemas_returns_schemas(self) -> None:
        reg = build_default_registry()
        schemas = reg.get_schemas(["memory_read", "read_file"])
        assert len(schemas) == 2

    def test_bm25_search_finds_tools(self) -> None:
        reg = build_default_registry()
        results = reg.bm25_search("git diff blame")
        assert any("git" in name for name in results)

    def test_bm25_search_empty_query(self) -> None:
        reg = build_default_registry()
        assert reg.bm25_search("") == []


# ── search_tools ──────────────────────────────────────────────


class TestSearchTools:
    def test_search_memory_edit(self) -> None:
        reg = build_default_registry()
        state = ToolActivationState(role="dev", registry=reg)
        r = handle_meta_tool("search_tools", {"query": "edit file patch"}, state=state)
        assert r["status"] == "ok"
        assert r["count"] > 0

    def test_search_git_tools(self) -> None:
        reg = build_default_registry()
        state = ToolActivationState(role="dev", registry=reg)
        r = handle_meta_tool("search_tools", {"query": "git diff log"}, state=state)
        assert any("git" in t for t in r["matched_tools"])

    def test_search_auto_activates(self) -> None:
        reg = build_default_registry()
        state = ToolActivationState(role="dev", registry=reg)
        handle_meta_tool("search_tools", {"query": "read file"}, state=state)
        assert len(state.active_tools) > 0

    def test_search_empty_query_error(self) -> None:
        reg = build_default_registry()
        state = ToolActivationState(role="dev", registry=reg)
        r = handle_meta_tool("search_tools", {"query": ""}, state=state)
        assert r["code"] == "E_EMPTY_QUERY"

    def test_search_no_match(self) -> None:
        reg = build_default_registry()
        state = ToolActivationState(role="dev", registry=reg)
        r = handle_meta_tool("search_tools", {"query": "xyzzyplugh"}, state=state)
        assert r["code"] == "NO_MATCH"

    def test_search_respects_shell_role(self) -> None:
        reg = build_default_registry()
        state = ToolActivationState(role="shell", registry=reg)
        r = handle_meta_tool("search_tools", {"query": "write file run cmd"}, state=state)
        write_tools = {"memory_write", "write_file", "run_cmd", "os_bash"}
        for tool in r.get("matched_tools", []):
            assert tool not in write_tools


# ── activate_domain ───────────────────────────────────────────


class TestActivateDomain:
    def test_activate_memory_read(self) -> None:
        reg = build_default_registry()
        state = ToolActivationState(role="dev", registry=reg)
        r = handle_meta_tool("activate_domain", {"domain": "memory_read"}, state=state)
        assert set(r["activated"]) == {"memory_read", "memory_list"}

    def test_activate_native_git(self) -> None:
        reg = build_default_registry()
        state = ToolActivationState(role="dev", registry=reg)
        r = handle_meta_tool("activate_domain", {"domain": "native_git"}, state=state)
        assert r["count"] == 8

    def test_activate_denied_for_shell(self) -> None:
        reg = build_default_registry()
        state = ToolActivationState(role="shell", registry=reg)
        r = handle_meta_tool("activate_domain", {"domain": "native_exec"}, state=state)
        assert r["code"] == "E_DOMAIN_DENIED"

    def test_activate_invalid_domain(self) -> None:
        reg = build_default_registry()
        state = ToolActivationState(role="dev", registry=reg)
        r = handle_meta_tool("activate_domain", {"domain": "nonexistent"}, state=state)
        assert r["code"] == "E_DOMAIN_NOT_FOUND"


# ── list_domains ──────────────────────────────────────────────


class TestListDomains:
    def test_lists_all_domains(self) -> None:
        reg = build_default_registry()
        state = ToolActivationState(role="dev", registry=reg)
        r = handle_meta_tool("list_domains", {}, state=state)
        domain_names = {d["domain"] for d in r["domains"]}
        assert "memory_read" in domain_names
        assert "native_git" in domain_names

    def test_shows_accessibility(self) -> None:
        reg = build_default_registry()
        state = ToolActivationState(role="shell", registry=reg)
        r = handle_meta_tool("list_domains", {}, state=state)
        for d in r["domains"]:
            if d["domain"] in ("native_exec", "native_control", "memory_write"):
                assert d["accessible"] is False

    def test_shows_activation_count(self) -> None:
        reg = build_default_registry()
        state = ToolActivationState(role="dev", registry=reg)
        handle_meta_tool("activate_domain", {"domain": "memory_read"}, state=state)
        r = handle_meta_tool("list_domains", {}, state=state)
        for d in r["domains"]:
            if d["domain"] == "memory_read":
                assert d["active"] == 2


# ── list_active_tools ────────────────────────────────────────


class TestListActiveTools:
    def test_empty_initially(self) -> None:
        reg = build_default_registry()
        state = ToolActivationState(role="dev", registry=reg)
        r = handle_meta_tool("list_active_tools", {}, state=state)
        assert r["count"] == 0

    def test_shows_activated_tools(self) -> None:
        reg = build_default_registry()
        state = ToolActivationState(role="dev", registry=reg)
        handle_meta_tool("activate_domain", {"domain": "native_exec"}, state=state)
        r = handle_meta_tool("list_active_tools", {}, state=state)
        assert r["count"] == 3


# ── ToolActivationState ──────────────────────────────────────


class TestToolActivationState:
    def test_allowed_domains_dev_includes_custom(self) -> None:
        reg = build_default_registry()
        state = ToolActivationState(role="dev", registry=reg)
        assert "custom" in state.allowed_domains()

    def test_allowed_domains_shell_includes_custom(self) -> None:
        reg = build_default_registry()
        state = ToolActivationState(role="shell", registry=reg)
        assert "custom" in state.allowed_domains()

    def test_activate_denied_tools(self) -> None:
        reg = build_default_registry()
        state = ToolActivationState(role="shell", registry=reg)
        activated, denied = state.activate(["memory_read", "memory_write"])
        assert activated == ["memory_read"]
        assert denied == ["memory_write"]


# ── Meta-tool definitions ─────────────────────────────────────


class TestMetaToolDefinitions:
    def test_count(self) -> None:
        assert len(META_TOOL_NAMES) == 5

    def test_names(self) -> None:
        assert META_TOOL_NAMES == {
            "search_tools", "activate_domain",
            "list_domains", "list_active_tools", "create_tool",
        }

    def test_only_dev_can_create(self) -> None:
        assert ROLE_CREATE_TOOL_ACCESS == {"dev"}


# ── Error codes ──────────────────────────────────────────────


class TestErrorCodes:
    def test_unknown_meta_tool(self) -> None:
        r = handle_meta_tool("nonexistent", {})
        assert r["code"] == "E_UNKNOWN_META_TOOL"

    def test_no_registry(self) -> None:
        state = ToolActivationState(role="dev")
        r = handle_meta_tool("search_tools", {"query": "test"}, state=state)
        assert r["code"] == "E_NO_REGISTRY"


# ── Constants ─────────────────────────────────────────────────


class TestConstants:
    def test_all_roles_have_custom(self) -> None:
        for role, domains in ROLE_DOMAIN_ACCESS.items():
            assert "custom" in domains, f"role '{role}' missing 'custom' domain"


# ═══════════════════════════════════════════════════════════════
# Custom Tools
# ═══════════════════════════════════════════════════════════════


class TestValidateToolCode:
    def test_valid_code(self) -> None:
        code = 'def run(args):\n    return {"result": args.get("x", 0) * 2}'
        ok, errors = validate_tool_code(code)
        assert ok is True
        assert errors == []

    def test_forbidden_import(self) -> None:
        code = "import os\ndef run(args):\n    return {}"
        ok, errors = validate_tool_code(code)
        assert ok is False
        assert any("E_FORBIDDEN_NODE" in e for e in errors)

    def test_forbidden_from_import(self) -> None:
        code = "from pathlib import Path\ndef run(args):\n    return {}"
        ok, errors = validate_tool_code(code)
        assert ok is False
        assert any("E_FORBIDDEN_NODE" in e for e in errors)

    def test_forbidden_name_eval(self) -> None:
        code = "def run(args):\n    return eval('1+1')"
        ok, errors = validate_tool_code(code)
        assert ok is False
        assert any("E_FORBIDDEN_NAME" in e for e in errors)

    def test_forbidden_name_open(self) -> None:
        code = "def run(args):\n    f = open('x')\n    return {}"
        ok, errors = validate_tool_code(code)
        assert ok is False
        assert any("E_FORBIDDEN_NAME" in e for e in errors)

    def test_missing_run(self) -> None:
        code = "def helper(x):\n    return x * 2"
        ok, errors = validate_tool_code(code)
        assert ok is False
        assert any("E_MISSING_RUN" in e for e in errors)

    def test_empty_code(self) -> None:
        ok, errors = validate_tool_code("")
        assert ok is False
        assert errors == ["E_EMPTY_CODE"]

    def test_syntax_error(self) -> None:
        code = "def run(args:\n    return {}"
        ok, errors = validate_tool_code(code)
        assert ok is False
        assert any("E_SYNTAX_ERROR" in e for e in errors)


class TestSandboxExec:
    def test_basic_exec(self) -> None:
        code = 'def run(args):\n    return {"doubled": args.get("x", 0) * 2}'
        r = sandbox_exec(code, {"x": 5})
        assert r["status"] == "ok"
        assert r["doubled"] == 10

    def test_no_run_function(self) -> None:
        code = "x = 42"
        r = sandbox_exec(code, {})
        assert r["status"] == "error"
        assert "E_RUN_NOT_CALLABLE" in r.get("code", "")

    def test_runtime_error(self) -> None:
        code = "def run(args):\n    return 1 / 0"
        r = sandbox_exec(code, {})
        assert r["status"] == "error"
        assert "ZeroDivisionError" in r.get("error", "")

    def test_builtin_access(self) -> None:
        code = 'def run(args):\n    return {"length": len([1, 2, 3])}'
        r = sandbox_exec(code, {})
        assert r["status"] == "ok"
        assert r["length"] == 3

    def test_forbidden_builtin_blocked(self) -> None:
        # __import__ should not be available in sandbox
        code = 'def run(args):\n    os = __import__("os")\n    return {}'
        r = sandbox_exec(code, {})
        assert r["status"] == "error"


class TestCustomToolPersistence:
    def setup_method(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()

    def teardown_method(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        _LOADED_CUSTOM_TOOLS.clear()

    def test_save_and_load(self) -> None:
        spec = {
            "name": "test_add",
            "description": "Add two numbers",
            "code": 'def run(args):\n    return {"sum": args["a"] + args["b"]}',
            "keywords": ["add", "math"],
        }
        save_custom_tool(spec, memory_root=self.tmp_dir)
        loaded = load_custom_tools(memory_root=self.tmp_dir)
        assert len(loaded) == 1
        assert loaded[0]["name"] == "test_add"

    def test_load_empty_dir(self) -> None:
        loaded = load_custom_tools(memory_root=self.tmp_dir)
        assert loaded == []


class TestCreateToolMetaTool:
    def setup_method(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()
        _LOADED_CUSTOM_TOOLS.clear()

    def teardown_method(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        _LOADED_CUSTOM_TOOLS.clear()

    def test_dev_creates_tool(self) -> None:
        reg = build_default_registry()
        state = ToolActivationState(role="dev", registry=reg)
        r = handle_meta_tool("create_tool", {
            "name": "my_adder",
            "description": "Add x and y",
            "code": 'def run(args):\n    return {"sum": args.get("x", 0) + args.get("y", 0)}',
            "keywords": ["add", "math"],
            "_memory_root": self.tmp_dir,
        }, state=state)
        assert r["status"] == "ok"
        assert r["tool_name"] == "my_adder"
        assert "my_adder" in state.active_tools

    def test_non_dev_denied(self) -> None:
        reg = build_default_registry()
        state = ToolActivationState(role="shell", registry=reg)
        r = handle_meta_tool("create_tool", {
            "name": "test",
            "description": "test",
            "code": "def run(args):\n    return {}",
        }, state=state)
        assert r["code"] == "E_CREATE_DENIED"

    def test_invalid_name_rejected(self) -> None:
        reg = build_default_registry()
        state = ToolActivationState(role="dev", registry=reg)
        r = handle_meta_tool("create_tool", {
            "name": "Bad-Name!",
            "description": "test",
            "code": "def run(args):\n    return {}",
        }, state=state)
        assert r["code"] == "E_INVALID_NAME"

    def test_invalid_code_rejected(self) -> None:
        reg = build_default_registry()
        state = ToolActivationState(role="dev", registry=reg)
        r = handle_meta_tool("create_tool", {
            "name": "bad_tool",
            "description": "test",
            "code": "import os\ndef run(args):\n    return {}",
            "_memory_root": self.tmp_dir,
        }, state=state)
        assert r["code"] == "E_VALIDATION_FAILED"

    def test_persisted_to_disk(self) -> None:
        reg = build_default_registry()
        state = ToolActivationState(role="dev", registry=reg)
        handle_meta_tool("create_tool", {
            "name": "disk_test",
            "description": "persisted",
            "code": "def run(args):\n    return {}",
            "_memory_root": self.tmp_dir,
        }, state=state)
        loaded = load_custom_tools(memory_root=self.tmp_dir)
        assert len(loaded) == 1
        assert loaded[0]["name"] == "disk_test"


class TestCustomToolExecution:
    def setup_method(self) -> None:
        _LOADED_CUSTOM_TOOLS.clear()
        _LOADED_CUSTOM_TOOLS["my_mul"] = {
            "name": "my_mul",
            "description": "multiply",
            "code": 'def run(args):\n    return {"product": args.get("a", 0) * args.get("b", 0)}',
        }

    def teardown_method(self) -> None:
        _LOADED_CUSTOM_TOOLS.clear()

    def test_call_custom_tool(self) -> None:
        r = handle_custom_tool_call("my_mul", {"a": 3, "b": 7})
        assert r["status"] == "ok"
        assert r["product"] == 21

    def test_call_nonexistent(self) -> None:
        r = handle_custom_tool_call("no_such_tool", {})
        assert r["code"] == "E_TOOL_NOT_FOUND"


class TestCustomToolDiscovery:
    def setup_method(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()
        _LOADED_CUSTOM_TOOLS.clear()
        # Save a tool to disk so register_custom_tools_into_registry can find it
        spec = {
            "name": "csv_parser",
            "description": "parse CSV files and return stats",
            "code": "def run(args):\n    return {}",
            "keywords": ["csv", "parse", "statistics"],
        }
        save_custom_tool(spec, memory_root=self.tmp_dir)

    def teardown_method(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        _LOADED_CUSTOM_TOOLS.clear()

    def test_custom_tool_in_registry(self) -> None:
        reg = ToolRegistry()
        register_custom_tools_into_registry(reg, memory_root=self.tmp_dir)
        assert "custom" in reg.domain_names
        assert "csv_parser" in reg.all_tool_names()

    def test_custom_tool_searchable(self) -> None:
        reg = ToolRegistry()
        register_custom_tools_into_registry(reg, memory_root=self.tmp_dir)
        results = reg.bm25_search("csv parse")
        assert "csv_parser" in results
