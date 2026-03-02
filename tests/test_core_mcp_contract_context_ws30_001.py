from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

from core.mcp import (
    MCPCallInput,
    MCPExecutionContext,
    NativeMCPHost,
    extract_worker_execution_context,
    validate_worker_execution_context,
)


class _StubMCPManager:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def unified_call(self, service_name: str, tool_call: Dict[str, Any]) -> str:
        self.calls.append({"service_name": service_name, "tool_call": dict(tool_call or {})})
        return json.dumps({"status": "success", "result": {"ok": True}}, ensure_ascii=False)

    def get_available_services(self) -> List[str]:
        return ["demo"]

    def get_available_services_filtered(self) -> Dict[str, Any]:
        return {"demo": {"source": "builtin"}}


def test_mcp_call_input_payload_maps_governance_context_fields() -> None:
    request = MCPCallInput(
        service_name="demo",
        tool_name="ping",
        arguments={"message": "hello"},
        execution_context=MCPExecutionContext(
            call_id="call_001",
            trace_id="trace_001",
            workflow_id="wf_001",
            session_id="sess_001",
            fencing_epoch=7,
            budget_remaining=123.5,
            timeout_ms=15000,
        ),
    )
    payload = request.to_tool_call_payload()
    assert payload["tool_name"] == "ping"
    assert payload["_tool_call_id"] == "call_001"
    assert payload["_trace_id"] == "trace_001"
    assert payload["_workflow_id"] == "wf_001"
    assert payload["_session_id"] == "sess_001"
    assert payload["_fencing_epoch"] == 7
    assert payload["fencing_epoch"] == 7
    assert payload["_budget_remaining"] == 123.5
    assert payload["budget_remaining"] == 123.5
    assert payload["mcp_tool_timeout_ms"] == 15000


def test_native_mcp_host_call_contract_propagates_context_to_payload() -> None:
    manager = _StubMCPManager()
    host = NativeMCPHost(manager=manager)
    request = MCPCallInput(
        service_name="demo",
        tool_name="ping",
        arguments={"message": "hello"},
        execution_context=MCPExecutionContext(
            call_id="call_002",
            trace_id="trace_002",
            fencing_epoch=11,
            budget_remaining=55.0,
        ),
    )
    response = asyncio.run(host.call_contract(request))

    assert response.status == "success"
    assert response.result == {"ok": True}
    assert response.execution_context.fencing_epoch == 11
    assert len(manager.calls) == 1
    call = manager.calls[0]
    assert call["service_name"] == "demo"
    assert call["tool_call"]["_fencing_epoch"] == 11
    assert call["tool_call"]["_budget_remaining"] == 55.0
    assert call["tool_call"]["_tool_call_id"] == "call_002"


def test_extract_and_validate_worker_execution_context() -> None:
    payload = {
        "_tool_call_id": "call_003",
        "_trace_id": "trace_003",
        "_workflow_id": "wf_003",
        "_session_id": "sess_003",
        "_fencing_epoch": 9,
        "_budget_remaining": "42.75",
        "mcp_tool_timeout_ms": "18000",
    }
    context = extract_worker_execution_context(payload)
    report = validate_worker_execution_context(context)
    assert report["valid"] is True
    assert context.call_id == "call_003"
    assert context.trace_id == "trace_003"
    assert context.fencing_epoch == 9
    assert context.budget_remaining == 42.75
    assert context.timeout_ms == 18000
