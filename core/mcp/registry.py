"""Core MCP registry facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

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


@dataclass(frozen=True)
class MCPRegistrySnapshot:
    registered_services: int
    cached_manifests: int
    service_names: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "registered_services": int(self.registered_services),
            "cached_manifests": int(self.cached_manifests),
            "service_names": list(self.service_names),
        }


class MCPRegistryFacade:
    """Core namespace facade for MCP registry operations."""

    def register_all(self) -> List[str]:
        registered = scan_and_register_mcp_agents()
        return list(registered if isinstance(registered, list) else [])

    def auto_register(self) -> None:
        auto_register_mcp()

    def services(self) -> List[str]:
        services = get_registered_services()
        return list(services if isinstance(services, list) else [])

    def service_info(self, service_name: str) -> Dict[str, Any]:
        info = get_service_info(service_name)
        return dict(info if isinstance(info, dict) else {})

    def all_service_info(self) -> Dict[str, Any]:
        payload = get_all_services_info()
        return dict(payload if isinstance(payload, dict) else {})

    def available_tools(self) -> Dict[str, Any]:
        payload = get_available_tools()
        return dict(payload if isinstance(payload, dict) else {})

    def snapshot(self) -> MCPRegistrySnapshot:
        names = sorted(str(name) for name in MCP_REGISTRY.keys())
        return MCPRegistrySnapshot(
            registered_services=len(names),
            cached_manifests=len(MANIFEST_CACHE),
            service_names=names,
        )


__all__ = [
    "MCP_REGISTRY",
    "MANIFEST_CACHE",
    "MCPRegistryFacade",
    "MCPRegistrySnapshot",
    "auto_register_mcp",
    "get_all_services_info",
    "get_available_tools",
    "get_registered_services",
    "get_service_info",
    "scan_and_register_mcp_agents",
]

