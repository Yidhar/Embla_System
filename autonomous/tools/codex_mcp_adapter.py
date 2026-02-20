"""Codex MCP fallback integration for verification stage."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class CodexMcpVerifier:
    """Call codex-mcp-server through local MCP manager if available."""

    service_name: str = "codex-cli"
    tool_name: str = "ask-codex"
    sandbox_mode: str = "read-only"
    approval_policy: str = "on-failure"

    async def ask(self, prompt: str, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        context = context or {}
        payload = {
            "tool_name": self.tool_name,
            "message": prompt,
            "sandboxMode": self.sandbox_mode,
            "approvalPolicy": self.approval_policy,
            **context,
        }
        try:
            from mcpserver.mcp_manager import get_mcp_manager

            manager = get_mcp_manager()
            raw = await manager.unified_call(self.service_name, payload)
        except Exception as exc:
            return {
                "status": "error",
                "message": f"codex mcp call failed: {exc}",
                "raw": "",
            }

        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        return {"status": "ok", "message": "non-json response", "raw": raw}
