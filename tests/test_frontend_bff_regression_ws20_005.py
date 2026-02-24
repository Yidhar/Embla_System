from __future__ import annotations

import base64
import json
from typing import Any, Dict

from fastapi.testclient import TestClient

import apiserver.agentic_tool_loop as tool_loop
from apiserver.api_server import (
    API_CONTRACT_VERSION,
    API_DEFAULT_VERSION,
    _build_api_contract_snapshot,
    _build_mcp_runtime_snapshot,
    _build_mcp_task_snapshot,
    app,
)


def _decode_sse_payload(chunk: str) -> Dict[str, Any]:
    assert chunk.startswith("data: ")
    encoded = chunk[6:].strip()
    payload = json.loads(base64.b64decode(encoded).decode("utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_ws20_005_contract_snapshot_and_headers_regression() -> None:
    snapshot = _build_api_contract_snapshot()
    assert snapshot["api_version"] == API_DEFAULT_VERSION
    assert snapshot["contract_version"] == API_CONTRACT_VERSION
    assert "/chat" in snapshot["deprecations"]

    with TestClient(app) as client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.headers.get("X-NagaAgent-Api-Version") == API_DEFAULT_VERSION
    assert resp.headers.get("X-NagaAgent-Contract-Version") == API_CONTRACT_VERSION
    assert "/v1/health" in resp.headers.get("Link", "")


def test_ws20_005_sse_envelope_and_tool_result_regression() -> None:
    chunk = tool_loop._format_sse_event("round_start", {"round": 1})
    payload = _decode_sse_payload(chunk)
    assert payload["type"] == "round_start"
    assert payload["schema_version"] == "ws20-002-v1"
    assert isinstance(payload.get("event_ts"), int)

    summaries = tool_loop._summarize_results_for_frontend(
        [
            {
                "status": "error",
                "service_name": "native",
                "tool_name": "run_cmd",
                "result": "permission denied",
            }
        ],
        200,
    )
    assert len(summaries) == 1
    assert summaries[0]["status"] == "error"
    assert "preview" in summaries[0]
    assert "permission denied" in summaries[0]["preview"]


def test_ws20_005_mcp_runtime_snapshot_and_filter_regression() -> None:
    runtime = _build_mcp_runtime_snapshot(
        registry_status={
            "registered_services": 2,
            "cached_manifests": 2,
            "service_names": ["weather-time", "game-guide"],
        },
        external_services=["codex-cli", "weather-time"],
    )
    assert runtime["tasks"]["total"] == 3
    assert runtime["registry"]["external_service_names"] == ["codex-cli"]

    all_tasks = _build_mcp_task_snapshot(snapshot=runtime)
    registered = _build_mcp_task_snapshot("registered", snapshot=runtime)
    configured = _build_mcp_task_snapshot("configured", snapshot=runtime)
    assert all_tasks["total"] == 3
    assert registered["total"] == 2
    assert configured["total"] == 1


def test_ws20_005_error_schema_regression_for_invalid_calls_and_results() -> None:
    _, native_errors = tool_loop._validate_native_call_schema(
        "call_err_1",
        {"tool_name": "run_cmd"},
    )
    assert any("E_SCHEMA_INPUT_INVALID" in err for err in native_errors)

    normalized = tool_loop._enforce_tool_result_schema(
        result={"service_name": "native", "tool_name": "run_cmd"},
        call={"agentType": "native", "tool_name": "run_cmd"},
        call_id="call_err_2",
        default_service_name="native",
        default_tool_name="run_cmd",
    )
    assert normalized["status"] == "error"
    assert normalized["service_name"] == "native"
    assert "E_SCHEMA_OUTPUT_INVALID" in str(normalized.get("result", ""))
    assert normalized["error_code"] == "E_SCHEMA_OUTPUT_INVALID"
