from __future__ import annotations

import base64
import json

import apiserver.api_server as api_server


def test_chat_route_core_path_selected_for_coding_intent() -> None:
    route = api_server._resolve_chat_stream_route(
        "请修复 apiserver/api_server.py 并补充回归测试",
        session_id="sess-core",
    )

    assert route["path"] == "path-c"
    assert route["core_escalation"] is True

    decision = route["router_decision"]
    assert decision["delegation_intent"] == "core_execution"
    assert decision["prompt_profile"] in {"core_exec_dev", "core_exec_general", "core_exec_ops"}


def test_chat_route_outer_path_selected_for_readonly_summary() -> None:
    route = api_server._resolve_chat_stream_route(
        "你好，帮我总结一下当前运行态势",
        session_id="sess-outer",
    )

    assert route["path"] == "path-a"
    assert route["outer_readonly_hit"] is True

    decision = route["router_decision"]
    assert decision["delegation_intent"] == "read_only_exploration"
    assert decision["prompt_profile"].startswith("outer_")


def test_chat_route_path_b_selected_for_followup_ambiguous_message() -> None:
    route = api_server._resolve_chat_stream_route("继续", session_id="sess-followup")

    assert route["path"] == "path-b"
    assert route["outer_readonly_hit"] is False
    assert route["core_escalation"] is False

    decision = route["router_decision"]
    assert decision["delegation_intent"] == "general_assistance"


def test_chat_route_followup_with_recent_coding_context_escalates_to_core(monkeypatch) -> None:
    monkeypatch.setattr(
        api_server.message_manager,
        "get_recent_messages",
        lambda _session_id, count=10: [{"role": "user", "content": "请修复 bug 并补测试"}],
    )
    route = api_server._resolve_chat_stream_route("继续", session_id="sess-followup-coding")

    assert route["path"] == "path-c"
    assert route["core_escalation"] is True
    assert route["router_decision"]["delegation_intent"] == "core_execution"


def test_chat_route_prompt_event_payload_keeps_outer_core_observability_fields() -> None:
    outer_route = api_server._resolve_chat_stream_route("请总结最近异常", session_id="sess-obs-a")
    core_route = api_server._resolve_chat_stream_route("请修复 bug 并提交补丁", session_id="sess-obs-c")

    outer_payload = api_server._build_chat_route_prompt_event_payload(outer_route)
    core_payload = api_server._build_chat_route_prompt_event_payload(core_route)

    assert outer_payload["trigger"] == "path-a"
    assert outer_payload["outer_readonly_hit"] is True
    assert outer_payload["core_escalation"] is False

    assert core_payload["trigger"] == "path-c"
    assert core_payload["outer_readonly_hit"] is False
    assert core_payload["core_escalation"] is True


def test_route_decision_sse_chunk_is_base64_json() -> None:
    chunk = api_server._format_sse_payload_chunk({"type": "route_decision", "path": "path-a"})
    assert chunk.startswith("data: ")
    payload_text = chunk[len("data: ") :].strip()
    decoded = json.loads(base64.b64decode(payload_text).decode("utf-8"))

    assert decoded["type"] == "route_decision"
    assert decoded["path"] == "path-a"
