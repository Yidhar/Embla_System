"""Tests for standard MCP client (agents/runtime/mcp_client.py).

Covers:
- Config loading
- MCPToolInfo and schema conversion
- MCPClientPool (without actual server connections)
- ToolRegistry integration for MCP
- Dynamic mcp_* domain access in ToolActivationState
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from agents.runtime.mcp_client import (
    MCPClientPool,
    MCPConnection,
    MCPServerConfig,
    MCPToolInfo,
    _mcp_tool_to_schema,
    get_mcp_tool_definitions,
    load_mcp_config,
    register_mcp_into_registry,
    set_mcp_pool,
)

from agents.runtime.tool_discovery import (
    ToolActivationState,
    ToolRegistry,
)


# ── Config Loading ────────────────────────────────────────────


class TestConfigLoading:
    def test_load_empty_config(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        ) as f:
            json.dump({"mcpServers": {}}, f)
            f.flush()
            configs = load_mcp_config(f.name)
        assert configs == []

    def test_load_valid_config(self) -> None:
        data = {
            "mcpServers": {
                "filesystem": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
                    "env": {"NODE_ENV": "production"},
                },
                "github": {
                    "command": "uvx",
                    "args": ["mcp-server-github"],
                    "enabled": False,
                },
            }
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        ) as f:
            json.dump(data, f)
            f.flush()
            configs = load_mcp_config(f.name)

        assert len(configs) == 2
        fs_cfg = next(c for c in configs if c.name == "filesystem")
        assert fs_cfg.command == "npx"
        assert fs_cfg.args == ["-y", "@modelcontextprotocol/server-filesystem", "."]
        assert fs_cfg.env == {"NODE_ENV": "production"}
        assert fs_cfg.enabled is True

        gh_cfg = next(c for c in configs if c.name == "github")
        assert gh_cfg.enabled is False

    def test_load_missing_file(self) -> None:
        configs = load_mcp_config("/nonexistent/config.json")
        assert configs == []

    def test_load_missing_command(self) -> None:
        data = {"mcpServers": {"bad": {"args": ["a"]}}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        ) as f:
            json.dump(data, f)
            f.flush()
            configs = load_mcp_config(f.name)
        assert configs == []


# ── Schema Conversion ────────────────────────────────────────


class TestSchemaConversion:
    def test_mcp_tool_to_schema(self) -> None:
        tool = MCPToolInfo(
            server_name="test",
            name="read_file",
            description="Read a file",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        )
        schema = _mcp_tool_to_schema(tool)
        assert schema["name"] == "read_file"
        assert schema["description"] == "Read a file"
        assert schema["parameters"]["properties"]["path"]["type"] == "string"

    def test_empty_schema(self) -> None:
        tool = MCPToolInfo(server_name="test", name="no_args", description="")
        schema = _mcp_tool_to_schema(tool)
        assert schema["name"] == "no_args"
        assert "MCP tool" in schema["description"]
        assert schema["parameters"] == {"type": "object", "properties": {}}


# ── MCPClientPool (unit, no real connection) ──────────────────


class TestMCPClientPool:
    def test_load_config(self) -> None:
        data = {"mcpServers": {"demo": {"command": "echo", "args": ["hello"]}}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        ) as f:
            json.dump(data, f)
            f.flush()
            pool = MCPClientPool()
            count = pool.load_config(f.name)
        assert count == 1
        assert pool.configs[0].name == "demo"

    def test_find_server_for_tool_empty(self) -> None:
        pool = MCPClientPool()
        assert pool.find_server_for_tool("nonexistent") is None

    def test_get_status_empty(self) -> None:
        pool = MCPClientPool()
        status = pool.get_status()
        assert status["total_servers"] == 0
        assert status["connected"] == 0
        assert status["total_tools"] == 0

    def test_get_all_tools_empty(self) -> None:
        pool = MCPClientPool()
        assert pool.get_all_tools() == []


# ── ToolRegistry Integration ─────────────────────────────────


class TestMCPRegistryIntegration:
    def test_register_connected_server(self) -> None:
        """Simulate a connected MCP server and verify registry integration."""
        pool = MCPClientPool()
        conn = MCPConnection(
            config=MCPServerConfig(name="test_server", command="echo"),
            connected=True,
            tools=[
                MCPToolInfo(
                    server_name="test_server",
                    name="list_files",
                    description="List files in a directory",
                ),
                MCPToolInfo(
                    server_name="test_server",
                    name="read_file",
                    description="Read file contents",
                ),
            ],
        )
        pool.connections["test_server"] = conn
        pool._tool_index = {"list_files": "test_server", "read_file": "test_server"}

        # Set as global pool for schema provider
        set_mcp_pool(pool)

        registry = ToolRegistry()
        domains = register_mcp_into_registry(registry, pool)
        assert "mcp_test_server" in domains
        assert "list_files" in registry.all_tool_names()
        assert "read_file" in registry.all_tool_names()

        # Schema provider works
        schemas = registry.get_schemas(["list_files"])
        assert len(schemas) == 1
        assert schemas[0]["name"] == "list_files"

    def test_mcp_domain_searchable(self) -> None:
        pool = MCPClientPool()
        conn = MCPConnection(
            config=MCPServerConfig(name="search_srv", command="echo"),
            connected=True,
            tools=[
                MCPToolInfo(
                    server_name="search_srv",
                    name="web_search",
                    description="Search the web using keywords",
                ),
            ],
        )
        pool.connections["search_srv"] = conn
        pool._tool_index = {"web_search": "search_srv"}
        set_mcp_pool(pool)

        registry = ToolRegistry()
        register_mcp_into_registry(registry, pool)
        results = registry.bm25_search("search web keywords")
        assert "web_search" in results


# ── Dynamic mcp_* Domain Access ──────────────────────────────


class TestDynamicMCPDomainAccess:
    def test_all_roles_access_mcp_domains(self) -> None:
        """All roles should access dynamically registered mcp_* domains."""
        pool = MCPClientPool()
        conn = MCPConnection(
            config=MCPServerConfig(name="dynamic", command="echo"),
            connected=True,
            tools=[
                MCPToolInfo(server_name="dynamic", name="dyn_tool", description="dynamic tool"),
            ],
        )
        pool.connections["dynamic"] = conn
        set_mcp_pool(pool)

        registry = ToolRegistry()
        register_mcp_into_registry(registry, pool)

        for role in ("shell", "core", "expert", "dev", "review"):
            state = ToolActivationState(role=role, registry=registry)
            domains = state.allowed_domains()
            assert "mcp_dynamic" in domains, f"role '{role}' cannot access mcp_dynamic"

    def test_mcp_tools_activatable(self) -> None:
        pool = MCPClientPool()
        conn = MCPConnection(
            config=MCPServerConfig(name="act_test", command="echo"),
            connected=True,
            tools=[
                MCPToolInfo(server_name="act_test", name="act_tool", description="activatable"),
            ],
        )
        pool.connections["act_test"] = conn
        pool._tool_index = {"act_tool": "act_test"}
        set_mcp_pool(pool)

        registry = ToolRegistry()
        register_mcp_into_registry(registry, pool)

        state = ToolActivationState(role="shell", registry=registry)
        activated, denied = state.activate(["act_tool"])
        assert "act_tool" in activated
        assert denied == []
