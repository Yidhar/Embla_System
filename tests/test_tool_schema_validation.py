from __future__ import annotations

import asyncio

import apiserver.agentic_tool_loop as tool_loop
from apiserver.agentic_tool_loop import _convert_structured_tool_calls
from system.policy_firewall import PolicyFirewall


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


def test_native_run_cmd_prunes_bloated_arguments_before_firewall() -> None:
    calls = [
        {
            "id": "schema_call_run_cmd_prune_1",
            "name": "native_call",
            "arguments": {
                "tool_name": "run_cmd",
                "command": "echo run_cmd_prune_smoke",
                "cwd": ".",
                "timeout_seconds": 60,
                "max_output_chars": 8000,
                "artifact_priority": "normal",
                # Bloated unknown keys from generic schema payload
                "artifact_id": "",
                "mode": "preview",
                "max_count": 1,
                "max_results": 1,
                "max_chars": 200,
                "sandbox": "restricted",
                "worktree": False,
                "start_line": 1,
                "end_line": 1,
            },
        }
    ]

    actionable_calls, validation_errors = _convert_structured_tool_calls(
        calls,
        session_id="schema_sess_run_cmd_prune_1",
        trace_id="schema_trace_run_cmd_prune_1",
    )

    assert validation_errors == []
    assert len(actionable_calls) == 1
    call = actionable_calls[0]
    assert call["tool_name"] == "run_cmd"
    assert call["command"] == "echo run_cmd_prune_smoke"
    assert call["cwd"] == "."
    assert call["timeout_seconds"] == 60
    assert call["max_output_chars"] == 8000
    assert call["artifact_priority"] == "normal"

    for dropped_key in (
        "artifact_id",
        "mode",
        "max_count",
        "max_results",
        "max_chars",
        "sandbox",
        "worktree",
        "start_line",
        "end_line",
    ):
        assert dropped_key not in call
        assert dropped_key in call["_dropped_input_args"]

    decision = PolicyFirewall().validate_native_call("run_cmd", call)
    assert decision.allowed is True


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


def test_structured_tool_calls_payload_rejects_stringified_json_payload() -> None:
    payload = '[{"id":"call_1","name":"native_call","arguments":{"tool_name":"read_file","path":"README.md"}}]'
    parsed = tool_loop._parse_structured_tool_calls_payload(payload)
    assert parsed == []


def test_mcp_call_rejects_flattened_arguments() -> None:
    calls = [
        {
            "id": "schema_call_mcp_1",
            "name": "mcp_call",
            "arguments": {
                "tool_name": "ping",
                "message": "hello",
            },
        }
    ]

    actionable_calls, validation_errors = _convert_structured_tool_calls(
        calls,
        session_id="schema_sess_mcp_1",
        trace_id="schema_trace_mcp_1",
    )

    assert actionable_calls == []
    assert validation_errors
    assert "仅支持结构化 arguments 对象" in validation_errors[0]


def test_submit_result_tool_accepts_boolean_task_completed() -> None:
    calls = [
        {
            "id": "schema_call_submit_1",
            "name": "SubmitResult_Tool",
            "arguments": {
                "task_completed": True,
                "final_answer": "已完成",
                "deliverables": ["patch", "test_report"],
            },
        }
    ]

    actionable_calls, validation_errors = _convert_structured_tool_calls(
        calls,
        session_id="schema_submit_session_1",
        trace_id="schema_submit_trace_1",
    )

    assert validation_errors == []
    assert len(actionable_calls) == 1
    call = actionable_calls[0]
    assert call["agentType"] == "internal"
    assert call["tool_name"] == "submit_result"
    assert call["task_completed"] is True
    assert call["_session_id"] == "schema_submit_session_1"
    assert call["_trace_id"] == "schema_submit_trace_1"


def test_submit_result_tool_rejects_non_boolean_task_completed() -> None:
    calls = [
        {
            "id": "schema_call_submit_2",
            "name": "SubmitResult_Tool",
            "arguments": {
                "task_completed": "true",
            },
        }
    ]

    actionable_calls, validation_errors = _convert_structured_tool_calls(
        calls,
        session_id="schema_submit_session_2",
        trace_id="schema_submit_trace_2",
    )

    assert actionable_calls == []
    assert validation_errors
    assert "task_completed 必须是 boolean" in validation_errors[0]
