from __future__ import annotations

import base64
import json
from typing import Any, Dict

import apiserver.agentic_tool_loop as tool_loop


def _decode_sse_payload(chunk: str) -> Dict[str, Any]:
    assert chunk.startswith("data: ")
    encoded = chunk[6:].strip()
    decoded = base64.b64decode(encoded).decode("utf-8")
    payload = json.loads(decoded)
    assert isinstance(payload, dict)
    return payload


def test_sse_event_envelope_includes_protocol_metadata() -> None:
    chunk = tool_loop._format_sse_event("round_start", {"round": 1})
    payload = _decode_sse_payload(chunk)

    assert payload["type"] == "round_start"
    assert payload["schema_version"] == "ws20-002-v1"
    assert isinstance(payload.get("event_ts"), int)
    assert payload["round"] == 1


def test_tool_call_descriptions_are_normalized() -> None:
    calls = [
        {
            "agentType": "native",
            "tool_name": "write_file",
            "_tool_call_id": "call_ws20_1",
            "_risk_level": "write_repo",
            "_execution_scope": "local",
            "_requires_global_mutex": False,
        }
    ]

    desc = tool_loop._build_tool_call_descriptions(calls)
    assert len(desc) == 1
    row = desc[0]
    assert row["agentType"] == "native"
    assert row["service_name"] == ""
    assert row["tool_name"] == "write_file"
    assert row["call_id"] == "call_ws20_1"
    assert row["risk_level"] == "write_repo"
    assert row["execution_scope"] == "local"
    assert row["requires_global_mutex"] is False


def test_tool_result_summary_always_contains_preview() -> None:
    results = [
        {
            "status": "success",
            "service_name": "native",
            "tool_name": "read_file",
            "result": "line1\nline2\nline3",
        }
    ]

    summaries = tool_loop._summarize_results_for_frontend(results, 500)
    assert len(summaries) == 1
    summary = summaries[0]
    assert "preview" in summary
    assert "line1" in summary["preview"]
