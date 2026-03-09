"""Core MCP host facade with a stable call/list API.

Rewritten to use the standard MCP protocol client (agents.runtime.mcp_client)
instead of the deprecated custom mcpserver implementation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.mcp.contract import MCPCallInput, MCPCallOutput


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
    """Core namespace host for MCP dispatch via standard protocol."""

    def __init__(self, *, pool: Optional[Any] = None) -> None:
        if pool is not None:
            self._pool = pool
        else:
            from agents.runtime.mcp_client import get_mcp_pool
            self._pool = get_mcp_pool()

    async def call(self, *, service_name: str, tool_call: Dict[str, Any]) -> str:
        if not self._pool:
            return json.dumps({"status": "error", "error": "MCP pool not initialized"})
        tool_name = str(tool_call.get("tool_name", "")).strip()
        args = {k: v for k, v in tool_call.items() if k not in ("tool_name", "service_name", "_tool_call_id")}
        result = await self._pool.call_tool(service_name, tool_name, args)
        return json.dumps(result, ensure_ascii=False, default=str)

    async def call_contract(self, request: MCPCallInput) -> MCPCallOutput:
        payload = request.to_tool_call_payload()
        service_name = str(request.service_name or payload.get("service_name") or "").strip()
        raw_result = await self.call(service_name=service_name, tool_call=payload)
        parsed = self._parse_raw_result(raw_result)

        status = str(parsed.get("status") or "").strip().lower() if isinstance(parsed, dict) else ""
        if not status:
            status = "error" if isinstance(parsed, dict) and parsed.get("error") else "success"

        error_code = ""
        if isinstance(parsed, dict):
            error_code = str(
                parsed.get("error_code")
                or parsed.get("code")
                or parsed.get("error")
                or ""
            ).strip()

        result: Any
        if isinstance(parsed, dict) and "result" in parsed:
            result = parsed.get("result")
        else:
            result = parsed

        return MCPCallOutput(
            status=status,
            service_name=service_name,
            tool_name=str(request.tool_name or ""),
            result=result,
            error_code=error_code,
            raw_result=parsed,
            execution_context=request.execution_context,
        )

    def list_services(self) -> List[str]:
        if not self._pool:
            return []
        return list(self._pool.connections.keys())

    def list_services_filtered(self) -> Dict[str, Any]:
        if not self._pool:
            return {}
        status = self._pool.get_status()
        return dict(status) if isinstance(status, dict) else {}

    def snapshot(self) -> MCPHostSnapshot:
        services = self.list_services()
        return MCPHostSnapshot(total_services=len(services), service_names=sorted(services))

    @staticmethod
    def _parse_raw_result(raw_result: Any) -> Any:
        if isinstance(raw_result, (dict, list)):
            return raw_result
        if not isinstance(raw_result, str):
            return raw_result
        text = raw_result.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            return parsed
        except json.JSONDecodeError:
            return {"status": "success", "result": text}


# Backward-compatible exports (type stubs only)
MCPManager = type("MCPManager", (), {})


def get_mcp_manager() -> Any:
    """Deprecated: returns None. Use agents.runtime.mcp_client.get_mcp_pool() instead."""
    return None


__all__ = ["MCPHostSnapshot", "MCPManager", "NativeMCPHost", "get_mcp_manager"]
