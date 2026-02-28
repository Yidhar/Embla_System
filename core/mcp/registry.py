"""Compatibility wrapper for current MCP registry functions."""

from __future__ import annotations

from mcpserver.mcp_registry import (
    MCP_REGISTRY,
    MANIFEST_CACHE,
    auto_register_mcp,
    get_all_services_info,
    get_available_tools,
    get_registered_services,
    get_service_info,
    scan_and_register_mcp_agents,
)

__all__ = [
    "MCP_REGISTRY",
    "MANIFEST_CACHE",
    "auto_register_mcp",
    "get_all_services_info",
    "get_available_tools",
    "get_registered_services",
    "get_service_info",
    "scan_and_register_mcp_agents",
]
