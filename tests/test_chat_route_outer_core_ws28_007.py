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


def test_path_b_clarify_budget_first_round_keeps_path_b(monkeypatch) -> None:
    session = {"messages": []}
    monkeypatch.setattr(api_server.message_manager, "get_session", lambda _sid: session)

    route_meta = {
        "path": "path-b",
        "outer_readonly_hit": False,
        "core_escalation": False,
        "router_decision": {
            "delegation_intent": "general_assistance",
            "prompt_profile": "outer_general",
            "injection_mode": "normal",
        },
    }
    updated = api_server._apply_path_b_clarify_budget(route_meta, session_id="sess-budget-a")

    assert updated["path"] == "path-b"
    assert updated["path_b_budget_escalated"] is False
    assert updated["path_b_clarify_turns"] == 1
    assert session[api_server._CHAT_ROUTE_STATE_KEY]["path_b_clarify_turns"] == 1


def test_path_b_clarify_budget_second_round_escalates_to_core(monkeypatch) -> None:
    session = {
        "messages": [],
        api_server._CHAT_ROUTE_STATE_KEY: {"path_b_clarify_turns": 1},
    }
    monkeypatch.setattr(api_server.message_manager, "get_session", lambda _sid: session)

    route_meta = {
        "path": "path-b",
        "outer_readonly_hit": False,
        "core_escalation": False,
        "router_decision": {
            "delegation_intent": "general_assistance",
            "prompt_profile": "outer_general",
            "injection_mode": "minimal",
        },
    }
    updated = api_server._apply_path_b_clarify_budget(route_meta, session_id="sess-budget-b")

    assert updated["path"] == "path-c"
    assert updated["core_escalation"] is True
    assert updated["path_b_budget_escalated"] is True
    assert updated["path_b_budget_reason"] == "clarify_budget_exceeded_auto_escalate_core"
    assert updated["router_decision"]["delegation_intent"] == "core_execution"
    assert updated["router_decision"]["prompt_profile"] == "core_exec_general"
    assert session[api_server._CHAT_ROUTE_STATE_KEY]["path_b_clarify_turns"] == 0


def test_non_path_b_route_resets_clarify_budget(monkeypatch) -> None:
    session = {
        "messages": [],
        api_server._CHAT_ROUTE_STATE_KEY: {"path_b_clarify_turns": 1},
    }
    monkeypatch.setattr(api_server.message_manager, "get_session", lambda _sid: session)

    route_meta = {
        "path": "path-a",
        "outer_readonly_hit": True,
        "core_escalation": False,
        "router_decision": {"delegation_intent": "read_only_exploration"},
    }
    updated = api_server._apply_path_b_clarify_budget(route_meta, session_id="sess-budget-c")

    assert updated["path"] == "path-a"
    assert updated["path_b_clarify_turns"] == 0
    assert session[api_server._CHAT_ROUTE_STATE_KEY]["path_b_clarify_turns"] == 0


def test_outer_core_session_bridge_creates_core_session_for_path_c() -> None:
    outer_session_id = api_server.message_manager.create_session(temporary=True)
    try:
        route_meta = {
            "path": "path-c",
            "outer_readonly_hit": False,
            "core_escalation": True,
            "router_decision": {"delegation_intent": "core_execution"},
        }
        updated = api_server._apply_outer_core_session_bridge(route_meta, outer_session_id=outer_session_id)
        assert updated["outer_session_id"] == outer_session_id
        assert updated["execution_session_id"].endswith("__core")
        assert updated["core_session_id"] == updated["execution_session_id"]
        assert updated["core_session_created"] is True
        assert api_server.message_manager.get_session(updated["core_session_id"]) is not None
    finally:
        api_server.message_manager.delete_session(outer_session_id)
        core_id = f"{outer_session_id}__core"
        api_server.message_manager.delete_session(core_id)


def test_outer_core_session_bridge_reuses_existing_core_session() -> None:
    outer_session_id = api_server.message_manager.create_session(temporary=True)
    try:
        first = api_server._apply_outer_core_session_bridge(
            {"path": "path-c", "router_decision": {"delegation_intent": "core_execution"}},
            outer_session_id=outer_session_id,
        )
        second = api_server._apply_outer_core_session_bridge(
            {"path": "path-c", "router_decision": {"delegation_intent": "core_execution"}},
            outer_session_id=outer_session_id,
        )
        assert first["core_session_id"] == second["core_session_id"]
        assert first["core_session_created"] is True
        assert second["core_session_created"] is False
    finally:
        api_server.message_manager.delete_session(outer_session_id)
        core_id = f"{outer_session_id}__core"
        api_server.message_manager.delete_session(core_id)


def test_outer_core_session_bridge_keeps_outer_for_non_core_path() -> None:
    outer_session_id = api_server.message_manager.create_session(temporary=True)
    try:
        updated = api_server._apply_outer_core_session_bridge(
            {"path": "path-a", "router_decision": {"delegation_intent": "read_only_exploration"}},
            outer_session_id=outer_session_id,
        )
        assert updated["execution_session_id"] == outer_session_id
        assert updated["core_session_created"] is False
    finally:
        api_server.message_manager.delete_session(outer_session_id)


def test_route_decision_sse_chunk_is_base64_json() -> None:
    chunk = api_server._format_sse_payload_chunk({"type": "route_decision", "path": "path-a"})
    assert chunk.startswith("data: ")
    payload_text = chunk[len("data: ") :].strip()
    decoded = json.loads(base64.b64decode(payload_text).decode("utf-8"))

    assert decoded["type"] == "route_decision"
    assert decoded["path"] == "path-a"
