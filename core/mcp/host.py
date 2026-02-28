"""Core MCP host facade with a stable call/list API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from mcpserver.mcp_manager import MCPManager, get_mcp_manager


@dataclass(frozen=True)
class MCPHostSnapshot:
    total_services: int
    service_names: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_services": int(self.total_services),
            "service_names": list(self.service_names),
        }


class NativeMCPHost:
    """Core namespace host for MCP dispatch."""

    def __init__(self, *, manager: MCPManager | None = None) -> None:
        self.manager = manager or get_mcp_manager()

    async def call(self, *, service_name: str, tool_call: Dict[str, Any]) -> str:
        return await self.manager.unified_call(service_name=service_name, tool_call=dict(tool_call or {}))

    def list_services(self) -> List[str]:
        return list(self.manager.get_available_services())

    def list_services_filtered(self) -> Dict[str, Any]:
        payload = self.manager.get_available_services_filtered()
        return dict(payload if isinstance(payload, dict) else {})

    def snapshot(self) -> MCPHostSnapshot:
        services = self.list_services()
        return MCPHostSnapshot(total_services=len(services), service_names=sorted(services))


__all__ = ["MCPHostSnapshot", "MCPManager", "NativeMCPHost", "get_mcp_manager"]

