"""Core MCP registry facade.

Rewritten to use the standard MCP protocol client (agents.runtime.mcp_client)
instead of the deprecated custom mcpserver.mcp_registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


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
    """Core namespace facade for MCP registry operations.

    Uses agent.runtime.mcp_client.MCPClientPool as backend.
    """

    def _get_pool(self) -> Any:
        try:
            from agents.runtime.mcp_client import get_mcp_pool
            return get_mcp_pool()
        except ImportError:
            return None

    def register_all(self) -> List[str]:
        """No-op: standard MCP servers auto-register on connect."""
        return []

    def auto_register(self) -> None:
        """No-op: standard MCP servers auto-register on connect."""
        pass

    def services(self) -> List[str]:
        pool = self._get_pool()
        if not pool:
            return []
        return list(pool.connections.keys())

    def service_info(self, service_name: str) -> Dict[str, Any]:
        pool = self._get_pool()
        if not pool:
            return {}
        conn = pool.connections.get(service_name)
        if not conn:
            return {}
        return {
            "name": service_name,
            "connected": conn.connected,
            "tools": [t.name for t in conn.tools],
            "error": conn.error,
        }

    def all_service_info(self) -> Dict[str, Any]:
        pool = self._get_pool()
        if not pool:
            return {}
        return pool.get_status()

    def available_tools(self) -> Dict[str, Any]:
        pool = self._get_pool()
        if not pool:
            return {}
        tools = pool.get_all_tools()
        return {
            "total_tools": len(tools),
            "tools": [{"name": t.name, "server": t.server_name, "description": t.description} for t in tools],
        }

    def snapshot(self) -> MCPRegistrySnapshot:
        pool = self._get_pool()
        if not pool:
            return MCPRegistrySnapshot(
                registered_services=0, cached_manifests=0, service_names=[],
            )
        names = sorted(pool.connections.keys())
        return MCPRegistrySnapshot(
            registered_services=len(names),
            cached_manifests=0,
            service_names=names,
        )


# Backward-compatible placeholders
MCP_REGISTRY: Dict[str, Any] = {}
MANIFEST_CACHE: Dict[str, Any] = {}


def auto_register_mcp() -> None:
    """Deprecated no-op. Standard MCP uses mcp_servers.json config."""
    pass


def scan_and_register_mcp_agents(*_args: Any, **_kwargs: Any) -> List[str]:
    """Deprecated no-op. Standard MCP auto-discovers tools via tools/list."""
    return []


def get_registered_services() -> List[str]:
    facade = MCPRegistryFacade()
    return facade.services()


def get_service_info(service_name: str) -> Dict[str, Any]:
    facade = MCPRegistryFacade()
    return facade.service_info(service_name)


def get_all_services_info() -> Dict[str, Any]:
    facade = MCPRegistryFacade()
    return facade.all_service_info()


def get_available_tools() -> Dict[str, Any]:
    facade = MCPRegistryFacade()
    return facade.available_tools()


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
