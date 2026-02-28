"""Core MCP namespace wrappers."""

from .contract import MCPCallInput, MCPCallOutput
from .host import MCPHostSnapshot, MCPManager, NativeMCPHost, get_mcp_manager
from .isolated_worker import (
    IsolatedWorkerRuntime,
    IsolatedWorkerRuntimeSnapshot,
    PluginWorkerProxy,
    PluginWorkerSpec,
)
from .registry import MCPRegistryFacade, MCPRegistrySnapshot

__all__ = [
    "MCPCallInput",
    "MCPCallOutput",
    "MCPHostSnapshot",
    "MCPManager",
    "NativeMCPHost",
    "get_mcp_manager",
    "PluginWorkerProxy",
    "PluginWorkerSpec",
    "IsolatedWorkerRuntime",
    "IsolatedWorkerRuntimeSnapshot",
    "MCPRegistryFacade",
    "MCPRegistrySnapshot",
]
