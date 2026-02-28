"""Core MCP namespace wrappers."""

from .contract import MCPCallInput, MCPCallOutput
from .host import MCPManager, get_mcp_manager
from .isolated_worker import (
    IsolatedWorkerRuntime,
    IsolatedWorkerRuntimeSnapshot,
    PluginWorkerProxy,
    PluginWorkerSpec,
)

__all__ = [
    "MCPCallInput",
    "MCPCallOutput",
    "MCPManager",
    "get_mcp_manager",
    "PluginWorkerProxy",
    "PluginWorkerSpec",
    "IsolatedWorkerRuntime",
    "IsolatedWorkerRuntimeSnapshot",
]
