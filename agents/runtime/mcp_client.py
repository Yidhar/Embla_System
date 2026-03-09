"""Standard MCP protocol client with connection pooling and ToolRegistry integration.

Replaces the custom ``mcpserver/`` implementation with the official MCP Python SDK.
Supports stdio transport: each configured MCP server is spawned as a subprocess,
tools are discovered via ``tools/list``, and calls are proxied via ``tools/call``.

Configuration is loaded from ``mcp_servers.json`` in the project root.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "mcp_servers.json"


# ── Data Types ────────────────────────────────────────────────


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""

    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class MCPToolInfo:
    """Discovered tool from an MCP server."""

    server_name: str
    name: str
    description: str
    input_schema: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPConnection:
    """Active connection to an MCP server."""

    config: MCPServerConfig
    session: Any = None  # mcp.ClientSession
    tools: List[MCPToolInfo] = field(default_factory=list)
    connected: bool = False
    error: Optional[str] = None
    # Context managers to keep alive
    _stdio_cm: Any = None
    _session_cm: Any = None


# ── Config Loading ────────────────────────────────────────────


def load_mcp_config(
    config_path: Optional[str] = None,
) -> List[MCPServerConfig]:
    """Load MCP server configurations from JSON file.

    Expected format::

        {
          "mcpServers": {
            "server_name": {
              "command": "npx",
              "args": ["-y", "@modelcontextprotocol/server-xxx"],
              "env": {"API_KEY": "xxx"},
              "enabled": true
            }
          }
        }
    """
    path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
    if not path.is_file():
        logger.debug("MCP config not found at %s, no servers configured", path)
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to parse MCP config %s: %s", path, exc)
        return []

    servers_dict = data.get("mcpServers") or {}
    configs: List[MCPServerConfig] = []
    for name, spec in servers_dict.items():
        if not isinstance(spec, dict):
            continue
        command = str(spec.get("command") or "").strip()
        if not command:
            logger.warning("MCP server '%s' missing 'command', skipping", name)
            continue
        configs.append(MCPServerConfig(
            name=str(name).strip(),
            command=command,
            args=[str(a) for a in (spec.get("args") or [])],
            env={str(k): str(v) for k, v in (spec.get("env") or {}).items()},
            enabled=bool(spec.get("enabled", True)),
        ))

    return configs


# ── MCP Tool Schema Conversion ────────────────────────────────


def _mcp_tool_to_schema(tool_info: MCPToolInfo) -> Dict[str, Any]:
    """Convert an MCPToolInfo to OpenAI-style tool schema dict."""
    return {
        "name": tool_info.name,
        "description": tool_info.description or f"MCP tool: {tool_info.name}",
        "parameters": tool_info.input_schema or {"type": "object", "properties": {}},
    }


# ── MCPClientPool ─────────────────────────────────────────────


class MCPClientPool:
    """Manages connections to multiple MCP servers.

    Lifecycle::

        pool = MCPClientPool()
        pool.load_config()
        await pool.connect_all()
        # ... use pool.call_tool(server, tool, args) ...
        await pool.close_all()
    """

    def __init__(self) -> None:
        self.configs: List[MCPServerConfig] = []
        self.connections: Dict[str, MCPConnection] = {}
        self._tool_index: Dict[str, str] = {}  # tool_name → server_name

    def load_config(self, config_path: Optional[str] = None) -> int:
        """Load server configs. Returns number of enabled servers."""
        self.configs = load_mcp_config(config_path)
        return sum(1 for c in self.configs if c.enabled)

    async def connect_all(self) -> Dict[str, bool]:
        """Connect to all enabled MCP servers.

        Returns a dict of server_name → success.
        """
        results: Dict[str, bool] = {}
        for cfg in self.configs:
            if not cfg.enabled:
                continue
            success = await self._connect_one(cfg)
            results[cfg.name] = success
        return results

    async def _connect_one(self, cfg: MCPServerConfig) -> bool:
        """Connect to a single MCP server via stdio transport."""
        conn = MCPConnection(config=cfg)

        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            # Build environment: inherit current env + merge server-specific env
            server_env = dict(os.environ)
            server_env.update(cfg.env)

            server_params = StdioServerParameters(
                command=cfg.command,
                args=cfg.args,
                env=server_env,
            )

            # Enter stdio_client context
            stdio_cm = stdio_client(server_params)
            read_stream, write_stream = await stdio_cm.__aenter__()
            conn._stdio_cm = stdio_cm

            # Enter ClientSession context
            session_cm = ClientSession(read_stream, write_stream)
            session = await session_cm.__aenter__()
            conn._session_cm = session_cm
            conn.session = session

            # Initialize the MCP handshake
            await session.initialize()

            # Discover tools
            tools_response = await session.list_tools()
            for tool in tools_response.tools:
                tool_info = MCPToolInfo(
                    server_name=cfg.name,
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema if hasattr(tool, "inputSchema") else {},
                )
                conn.tools.append(tool_info)
                self._tool_index[tool.name] = cfg.name

            conn.connected = True
            self.connections[cfg.name] = conn
            logger.info(
                "✅ MCP server '%s' connected: %d tools discovered",
                cfg.name, len(conn.tools),
            )
            return True

        except Exception as exc:
            conn.error = str(exc)
            conn.connected = False
            self.connections[cfg.name] = conn
            logger.warning(
                "❌ MCP server '%s' failed to connect: %s", cfg.name, exc,
            )
            return False

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Call a tool on a specific MCP server."""
        conn = self.connections.get(server_name)
        if not conn or not conn.connected or not conn.session:
            return {
                "status": "error",
                "code": "E_SERVER_NOT_CONNECTED",
                "error": f"MCP server '{server_name}' is not connected",
            }

        try:
            result = await conn.session.call_tool(tool_name, arguments)
            # Extract content from MCP result
            content_parts: List[str] = []
            for block in result.content:
                if hasattr(block, "text"):
                    content_parts.append(block.text)
                elif hasattr(block, "data"):
                    content_parts.append(f"[binary data: {len(block.data)} bytes]")
                else:
                    content_parts.append(str(block))

            return {
                "status": "ok",
                "server": server_name,
                "tool": tool_name,
                "result": "\n".join(content_parts),
                "isError": getattr(result, "isError", False),
            }
        except Exception as exc:
            logger.warning(
                "MCP tool call failed: server=%s tool=%s error=%s",
                server_name, tool_name, exc,
            )
            return {
                "status": "error",
                "code": "E_CALL_FAILED",
                "error": str(exc),
                "server": server_name,
                "tool": tool_name,
            }

    def find_server_for_tool(self, tool_name: str) -> Optional[str]:
        """Find which server provides a given tool."""
        return self._tool_index.get(tool_name)

    def get_all_tools(self) -> List[MCPToolInfo]:
        """Get all discovered tools across all connected servers."""
        tools: List[MCPToolInfo] = []
        for conn in self.connections.values():
            if conn.connected:
                tools.extend(conn.tools)
        return tools

    def get_server_tools(self, server_name: str) -> List[MCPToolInfo]:
        """Get tools for a specific server."""
        conn = self.connections.get(server_name)
        if not conn or not conn.connected:
            return []
        return list(conn.tools)

    def get_status(self) -> Dict[str, Any]:
        """Get status of all servers."""
        servers: List[Dict[str, Any]] = []
        for name, conn in self.connections.items():
            servers.append({
                "name": name,
                "connected": conn.connected,
                "tools_count": len(conn.tools),
                "error": conn.error,
            })
        return {
            "total_servers": len(self.connections),
            "connected": sum(1 for c in self.connections.values() if c.connected),
            "total_tools": sum(len(c.tools) for c in self.connections.values() if c.connected),
            "servers": servers,
        }

    async def close_all(self) -> None:
        """Close all MCP server connections."""
        for name, conn in self.connections.items():
            try:
                if conn._session_cm:
                    await conn._session_cm.__aexit__(None, None, None)
                if conn._stdio_cm:
                    await conn._stdio_cm.__aexit__(None, None, None)
                conn.connected = False
                logger.info("MCP server '%s' disconnected", name)
            except Exception as exc:
                logger.warning("Error closing MCP server '%s': %s", name, exc)
        self.connections.clear()
        self._tool_index.clear()


# ── ToolRegistry Integration ──────────────────────────────────

# Module-level pool instance
_POOL: Optional[MCPClientPool] = None


def get_mcp_pool() -> Optional[MCPClientPool]:
    """Get the global MCP client pool (may be None if not initialized)."""
    return _POOL


def set_mcp_pool(pool: MCPClientPool) -> None:
    """Set the global MCP client pool."""
    global _POOL
    _POOL = pool


def get_mcp_tool_definitions(
    tool_names: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Schema provider for ToolRegistry — returns OpenAI-style tool schemas."""
    pool = _POOL
    if not pool:
        return []

    all_tools = pool.get_all_tools()
    if tool_names is not None:
        names_set = set(tool_names)
        all_tools = [t for t in all_tools if t.name in names_set]

    return [_mcp_tool_to_schema(t) for t in all_tools]


def register_mcp_into_registry(
    registry: Any,
    pool: Optional[MCPClientPool] = None,
) -> List[str]:
    """Register each connected MCP server as a domain in the ToolRegistry.

    Domain name pattern: ``mcp_{server_name}``
    """
    p = pool or _POOL
    if not p:
        return []

    registered: List[str] = []
    for server_name, conn in p.connections.items():
        if not conn.connected or not conn.tools:
            continue
        domain_name = f"mcp_{server_name}"
        tool_names = [t.name for t in conn.tools]
        keywords = list(set(
            word
            for t in conn.tools
            for word in (t.description.lower().split() + [t.name])
            if len(word) > 2
        ))[:30]

        registry.register_domain(
            domain_name,
            f"MCP server: {server_name}",
            keywords or [server_name, "mcp"],
            tool_names,
            get_mcp_tool_definitions,
        )
        registered.append(domain_name)
        logger.info(
            "Registered MCP domain '%s' with %d tools",
            domain_name, len(tool_names),
        )

    return registered


__all__ = [
    "MCPClientPool",
    "MCPConnection",
    "MCPServerConfig",
    "MCPToolInfo",
    "get_mcp_pool",
    "get_mcp_tool_definitions",
    "load_mcp_config",
    "register_mcp_into_registry",
    "set_mcp_pool",
]
