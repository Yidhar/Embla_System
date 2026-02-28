"""Pydantic contracts for MCP calls under the core namespace."""

from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, ConfigDict, Field


class MCPCallInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    service_name: str = ""
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class MCPCallOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    service_name: str
    tool_name: str
    result: Any = None
    error_code: str = ""


__all__ = ["MCPCallInput", "MCPCallOutput"]
