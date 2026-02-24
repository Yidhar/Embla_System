from __future__ import annotations

from apiserver.agentic_tool_loop import _convert_structured_tool_calls


def test_convert_structured_tool_calls_injects_context_metadata() -> None:
    structured_calls = [
        {
            "id": "call_native_1",
            "name": "native_call",
            "arguments": {
                "tool_name": "write_file",
                "path": "docs/a.txt",
                "content": "hello",
            },
        },
        {
            "id": "call_mcp_1",
            "name": "mcp_call",
            "arguments": {
                "tool_name": "ask-codex",
                "message": "explain current plan",
            },
        },
        {
            "id": "call_live2d_1",
            "name": "live2d_action",
            "arguments": {"action": "happy"},
        },
    ]

    actionable_calls, live2d_calls, validation_errors = _convert_structured_tool_calls(
        structured_calls,
        session_id="sess_meta_1",
        trace_id="trace_meta_1",
    )

    assert validation_errors == []
    assert len(actionable_calls) == 2
    assert len(live2d_calls) == 1

    for call in [*actionable_calls, *live2d_calls]:
        assert call["_trace_id"] == "trace_meta_1"
        assert call["_session_id"] == "sess_meta_1"
        assert call.get("_risk_level")
        assert call.get("_execution_scope")
        assert isinstance(call.get("_requires_global_mutex"), bool)
        assert "_fencing_epoch" in call

    native_call = next(call for call in actionable_calls if call.get("agentType") == "native")
    mcp_call = next(call for call in actionable_calls if call.get("agentType") == "mcp")
    live2d_call = live2d_calls[0]

    assert native_call["_tool_call_id"] == "call_native_1"
    assert native_call["_risk_level"] == "write_repo"
    assert native_call["_execution_scope"] == "local"
    assert native_call["_requires_global_mutex"] is False

    assert mcp_call["_tool_call_id"] == "call_mcp_1"
    assert mcp_call["prompt"] == "explain current plan"
    assert mcp_call["service_name"] == "codex-cli"

    assert live2d_call["_tool_call_id"] == "call_live2d_1"
    assert live2d_call["tool_name"] == "live2d_action"


def test_convert_structured_tool_calls_generates_trace_when_missing() -> None:
    structured_calls = [
        {
            "name": "native_call",
            "arguments": {
                "tool_name": "run_cmd",
                "command": "npm install",
            },
        }
    ]

    actionable_calls, live2d_calls, validation_errors = _convert_structured_tool_calls(
        structured_calls,
        session_id="sess_meta_2",
        trace_id=None,
    )

    assert validation_errors == []
    assert live2d_calls == []
    assert len(actionable_calls) == 1

    dispatched = actionable_calls[0]
    assert dispatched["_tool_call_id"] == "tool_call_1"
    assert dispatched["_trace_id"].startswith("trace_")
    assert dispatched["_session_id"] == "sess_meta_2"
    assert dispatched["_requires_global_mutex"] is True
    assert dispatched["_execution_scope"] == "global"

    # 原始结构化调用也应携带同一追踪信息，便于统一审计。
    assert structured_calls[0]["_tool_call_id"] == "tool_call_1"
    assert structured_calls[0]["_trace_id"] == dispatched["_trace_id"]
    assert structured_calls[0]["_session_id"] == "sess_meta_2"


def test_convert_structured_tool_calls_keeps_metadata_on_validation_error() -> None:
    structured_calls = [
        {"id": "bad_call", "name": "native_call", "arguments": "not-a-dict"},
    ]

    actionable_calls, live2d_calls, validation_errors = _convert_structured_tool_calls(
        structured_calls,
        session_id="sess_meta_3",
        trace_id="trace_meta_3",
    )

    assert actionable_calls == []
    assert live2d_calls == []
    assert validation_errors
    assert "arguments必须是对象" in validation_errors[0]

    failed_call = structured_calls[0]
    assert failed_call["_tool_call_id"] == "bad_call"
    assert failed_call["_trace_id"] == "trace_meta_3"
    assert failed_call["_session_id"] == "sess_meta_3"

