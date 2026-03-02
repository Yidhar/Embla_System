"""Core MCP namespace wrappers."""

from .contract import MCPCallInput, MCPCallOutput, MCPExecutionContext
from .host import MCPHostSnapshot, MCPManager, NativeMCPHost, get_mcp_manager
from .isolated_worker import (
    IsolatedWorkerRuntime,
    IsolatedWorkerRuntimeSnapshot,
    MCPWorkerExecutionContext,
    PluginWorkerProxy,
    PluginWorkerSpec,
    extract_worker_execution_context,
    validate_worker_execution_context,
)
from .registry import MCPRegistryFacade, MCPRegistrySnapshot

__all__ = [
    "MCPCallInput",
    "MCPCallOutput",
    "MCPExecutionContext",
    "MCPHostSnapshot",
    "MCPManager",
    "NativeMCPHost",
    "get_mcp_manager",
    "PluginWorkerProxy",
    "PluginWorkerSpec",
    "IsolatedWorkerRuntime",
    "IsolatedWorkerRuntimeSnapshot",
    "MCPWorkerExecutionContext",
    "extract_worker_execution_context",
    "validate_worker_execution_context",
    "MCPRegistryFacade",
    "MCPRegistrySnapshot",
]
