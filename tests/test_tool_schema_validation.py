from __future__ import annotations

import asyncio

import apiserver.agentic_tool_loop as tool_loop
from apiserver.agentic_tool_loop import _convert_structured_tool_calls


def test_native_input_schema_rejects_missing_run_cmd_command() -> None:
    calls = [
        {
            "id": "schema_call_1",
            "name": "native_call",
            "arguments": {"tool_name": "run_cmd"},
        }
    ]

    actionable_calls, validation_errors = _convert_structured_tool_calls(
        calls,
        session_id="schema_sess_1",
        trace_id="schema_trace_1",
    )

    assert actionable_calls == []
    assert validation_errors
    assert "[E_SCHEMA_INPUT_INVALID]" in validation_errors[0]
    assert "run_cmd 缺少 command/cmd" in validation_errors[0]


def test_native_input_schema_normalizes_alias_tool_name() -> None:
    calls = [
        {
            "id": "schema_call_2",
            "name": "native_call",
            "arguments": {"tool_name": "exec", "command": "echo hello"},
        }
    ]

    actionable_calls, validation_errors = _convert_structured_tool_calls(
        calls,
        session_id="schema_sess_2",
        trace_id="schema_trace_2",
    )

    assert validation_errors == []
    assert len(actionable_calls) == 1
    assert actionable_calls[0]["tool_name"] == "run_cmd"


def test_native_input_schema_accepts_artifact_reader_forensic_ref() -> None:
    calls = [
        {
            "id": "schema_call_3",
            "name": "native_call",
            "arguments": {
                "tool_name": "artifact_reader",
                "forensic_artifact_ref": "artifact_abc123",
                "mode": "jsonpath",
                "query": "$..trace_id",
            },
        }
    ]

    actionable_calls, validation_errors = _convert_structured_tool_calls(
        calls,
        session_id="schema_sess_3",
        trace_id="schema_trace_3",
    )

    assert validation_errors == []
    assert len(actionable_calls) == 1
    assert actionable_calls[0]["tool_name"] == "artifact_reader"
    assert actionable_calls[0]["forensic_artifact_ref"] == "artifact_abc123"


def test_output_schema_rejects_result_without_status(monkeypatch) -> None:
    async def _invalid_result(_: dict, __: str) -> dict:
        return {
            "service_name": "native",
            "tool_name": "run_cmd",
            "result": "ok",
        }

    monkeypatch.setattr(tool_loop, "_execute_single_tool_call", _invalid_result)
    call = {
        "agentType": "native",
        "tool_name": "run_cmd",
        "command": "echo hi",
        "_tool_call_id": "schema_output_1",
        "_trace_id": "trace_output_1",
    }

    result = asyncio.run(
        tool_loop._execute_tool_call_with_retry(
            call,
            "schema-output-session",
            semaphore=asyncio.Semaphore(1),
            retry_failed=False,
            max_retries=0,
            retry_backoff_seconds=0.0,
        )
    )

    assert result["status"] == "error"
    assert result["error_code"] == "E_SCHEMA_OUTPUT_INVALID"
    assert "missing status" in result["result"]


def test_output_schema_rejects_non_dict_result(monkeypatch) -> None:
    async def _invalid_result(_: dict, __: str) -> str:
        return "unexpected-string"

    monkeypatch.setattr(tool_loop, "_execute_single_tool_call", _invalid_result)
    call = {
        "agentType": "native",
        "tool_name": "run_cmd",
        "command": "echo hi",
        "_tool_call_id": "schema_output_2",
        "_trace_id": "trace_output_2",
    }

    result = asyncio.run(
        tool_loop._execute_tool_call_with_retry(
            call,
            "schema-output-session-2",
            semaphore=asyncio.Semaphore(1),
            retry_failed=False,
            max_retries=0,
            retry_backoff_seconds=0.0,
        )
    )

    assert result["status"] == "error"
    assert result["error_code"] == "E_SCHEMA_OUTPUT_INVALID"
    assert "payload must be object" in result["result"]
