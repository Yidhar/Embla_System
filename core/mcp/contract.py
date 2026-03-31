"""Pydantic contracts for MCP calls under the core namespace."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MCPExecutionContext(BaseModel):
    """Governance/runtime context that should travel with each MCP call."""

    model_config = ConfigDict(extra="allow")

    call_id: str = ""
    trace_id: str = ""
    workflow_id: str = ""
    session_id: str = ""
    caller_role: str = ""
    idempotency_key: str = ""
    timeout_ms: Optional[int] = None
    fencing_epoch: Optional[int] = None
    budget_remaining: Optional[float] = None

    @field_validator("timeout_ms")
    @classmethod
    def _normalize_timeout_ms(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        parsed = int(value)
        return parsed if parsed > 0 else None

    @field_validator("fencing_epoch")
    @classmethod
    def _normalize_fencing_epoch(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        parsed = int(value)
        return parsed if parsed > 0 else None

    @field_validator("budget_remaining")
    @classmethod
    def _normalize_budget_remaining(cls, value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        parsed = float(value)
        return parsed if parsed >= 0 else 0.0

    def to_payload_fields(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if self.call_id:
            payload["_tool_call_id"] = str(self.call_id)
        if self.trace_id:
            payload["_trace_id"] = str(self.trace_id)
        if self.workflow_id:
            payload["_workflow_id"] = str(self.workflow_id)
        if self.session_id:
            payload["_session_id"] = str(self.session_id)
        if self.caller_role:
            payload["_caller_role"] = str(self.caller_role)
        if self.idempotency_key:
            payload["idempotency_key"] = str(self.idempotency_key)
        if self.timeout_ms is not None:
            payload["mcp_tool_timeout_ms"] = int(self.timeout_ms)
        if self.fencing_epoch is not None:
            payload["_fencing_epoch"] = int(self.fencing_epoch)
            payload["fencing_epoch"] = int(self.fencing_epoch)
        if self.budget_remaining is not None:
            payload["_budget_remaining"] = float(self.budget_remaining)
            payload["budget_remaining"] = float(self.budget_remaining)
        return payload


class MCPCallInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    service_name: str = ""
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    execution_context: MCPExecutionContext = Field(default_factory=MCPExecutionContext)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_tool_call_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "service_name": str(self.service_name or ""),
            "tool_name": str(self.tool_name or ""),
            "arguments": dict(self.arguments or {}),
        }
        if isinstance(self.metadata, dict) and self.metadata:
            payload["_metadata"] = dict(self.metadata)
        payload.update(self.execution_context.to_payload_fields())
        return payload


class MCPCallOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    service_name: str
    tool_name: str
    result: Any = None
    error_code: str = ""
    raw_result: Any = None
    execution_context: MCPExecutionContext = Field(default_factory=MCPExecutionContext)


__all__ = ["MCPCallInput", "MCPCallOutput", "MCPExecutionContext"]
