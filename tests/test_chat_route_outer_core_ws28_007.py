from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import apiserver.api_server as api_server
import pytest
from autonomous.router_arbiter_guard import RouterArbiterGuard


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


def test_chat_route_readonly_request_with_code_reference_stays_outer_path() -> None:
    route = api_server._resolve_chat_stream_route(
        "请解释 apiserver/api_server.py 里的路由守卫逻辑，不要改代码",
        session_id="sess-outer-readonly-code",
    )

    assert route["path"] == "path-a"
    assert route["outer_readonly_hit"] is True
    assert route["core_escalation"] is False
    assert route["router_decision"]["delegation_intent"] == "read_only_exploration"


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


def test_build_path_model_override_resolves_outer_and_core_targets(monkeypatch) -> None:
    fake_cfg = SimpleNamespace(
        api=SimpleNamespace(
            routing=SimpleNamespace(
                outer=SimpleNamespace(
                    api_key="outer-key",
                    base_url="https://outer.example/v1",
                    model="gpt-4.1-mini",
                    provider="openai_compatible",
                    protocol="",
                    reasoning_effort="low",
                ),
                core=SimpleNamespace(
                    api_key="core-key",
                    base_url="https://core.example/v1",
                    model="gpt-5.2",
                    provider="openai",
                    protocol="openai_chat_completions",
                    reasoning_effort="high",
                ),
            )
        )
    )
    monkeypatch.setattr(api_server, "get_config", lambda: fake_cfg)

    outer = api_server._build_path_model_override("path-a")
    core = api_server._build_path_model_override("path-c")

    assert outer == {
        "api_key": "outer-key",
        "api_base": "https://outer.example/v1",
        "model": "gpt-4.1-mini",
        "provider": "openai_compatible",
        "reasoning_effort": "low",
    }
    assert core == {
        "api_key": "core-key",
        "api_base": "https://core.example/v1",
        "model": "gpt-5.2",
        "provider": "openai",
        "protocol": "openai_chat_completions",
        "reasoning_effort": "high",
    }


def test_merge_model_override_prioritizes_high_priority_values() -> None:
    base = {"model": "gpt-4.1-mini", "api_base": "https://outer.example/v1", "provider": "openai_compatible"}
    high = {"model": "gpt-5.2", "api_key": "core-key"}

    merged = api_server._merge_model_override(base, high)

    assert merged == {
        "model": "gpt-5.2",
        "api_base": "https://outer.example/v1",
        "provider": "openai_compatible",
        "api_key": "core-key",
    }


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


def test_chat_route_router_arbiter_escalates_ping_pong_and_freezes_to_core(monkeypatch) -> None:
    session = {"messages": []}
    monkeypatch.setattr(api_server.message_manager, "get_session", lambda _sid: session)
    monkeypatch.setattr(api_server, "_CHAT_ROUTE_ARBITER_GUARD", RouterArbiterGuard(max_delegate_turns=2))

    first = api_server._apply_chat_route_router_arbiter_guard(
        {
            "path": "path-a",
            "outer_readonly_hit": True,
            "core_escalation": False,
            "router_decision": {"delegation_intent": "read_only_exploration"},
        },
        session_id="sess-arbiter-a",
    )
    assert first["path"] == "path-a"
    assert first["router_arbiter_status"] == "ok"

    second = api_server._apply_chat_route_router_arbiter_guard(
        {
            "path": "path-c",
            "outer_readonly_hit": False,
            "core_escalation": True,
            "router_decision": {"delegation_intent": "core_execution"},
        },
        session_id="sess-arbiter-a",
    )
    assert second["path"] == "path-c"
    assert second["router_arbiter_status"] == "warning"
    assert second["router_arbiter_delegate_turns"] == 1
    assert second["router_arbiter_escalated"] is False

    third = api_server._apply_chat_route_router_arbiter_guard(
        {
            "path": "path-a",
            "outer_readonly_hit": True,
            "core_escalation": False,
            "router_decision": {"delegation_intent": "read_only_exploration"},
        },
        session_id="sess-arbiter-a",
    )
    assert third["path"] == "path-c"
    assert third["core_escalation"] is True
    assert third["router_arbiter_status"] == "critical"
    assert third["router_arbiter_applied"] is True
    assert third["router_arbiter_action"] == "freeze_to_core"
    assert "ROUTER_ARBITER_PING_PONG_FREEZE_CORE" in third["router_arbiter_reason_codes"]
    assert third["router_arbiter_delegate_turns"] == 2
    assert third["router_arbiter_escalated"] is True


def test_route_prompt_event_payload_contains_router_arbiter_fields() -> None:
    payload = api_server._build_chat_route_prompt_event_payload(
        {
            "path": "path-c",
            "risk_level": "write_repo",
            "outer_readonly_hit": False,
            "core_escalation": True,
            "router_arbiter_status": "critical",
            "router_arbiter_applied": True,
            "router_arbiter_action": "freeze_to_core",
            "router_arbiter_reason": "router_arbiter_ping_pong_freeze_core",
            "router_arbiter_reason_codes": ["ROUTER_ARBITER_PING_PONG_FREEZE_CORE"],
            "router_arbiter_path_before": "path-a",
            "router_arbiter_path_after": "path-c",
            "router_arbiter_delegate_turns": 3,
            "router_arbiter_max_delegate_turns": 3,
            "router_arbiter_conflict_ticket": "chat_route_ping_pong::path-a|path-c",
            "router_arbiter_freeze": True,
            "router_arbiter_hitl": True,
            "router_arbiter_escalated": True,
            "router_decision": {
                "delegation_intent": "core_execution",
                "prompt_profile": "core_exec_general",
                "injection_mode": "normal",
            },
        }
    )

    assert payload["router_arbiter_status"] == "critical"
    assert payload["router_arbiter_applied"] is True
    assert payload["router_arbiter_action"] == "freeze_to_core"
    assert payload["router_arbiter_delegate_turns"] == 3
    assert payload["router_arbiter_conflict_ticket"] == "chat_route_ping_pong::path-a|path-c"
    assert payload["router_arbiter_escalated"] is True


def test_emit_chat_route_arbiter_event_emits_critical_row() -> None:
    class _CaptureStore:
        def __init__(self) -> None:
            self.rows = []

        def emit(self, event_type, payload, source=""):
            self.rows.append({"event_type": event_type, "payload": dict(payload), "source": source})

    original_store = api_server._CHAT_ROUTE_EVENT_STORE
    capture = _CaptureStore()
    api_server._CHAT_ROUTE_EVENT_STORE = capture
    try:
        route_meta = {
            "path": "path-c",
            "risk_level": "write_repo",
            "router_arbiter_status": "critical",
            "router_arbiter_applied": True,
            "router_arbiter_action": "freeze_to_core",
            "router_arbiter_reason": "router_arbiter_ping_pong_freeze_core",
            "router_arbiter_reason_codes": ["ROUTER_ARBITER_PING_PONG_FREEZE_CORE"],
            "router_arbiter_path_before": "path-a",
            "router_arbiter_path_after": "path-c",
            "router_arbiter_delegate_turns": 3,
            "router_arbiter_max_delegate_turns": 3,
            "router_arbiter_conflict_ticket": "chat_route_ping_pong::path-a|path-c",
            "router_arbiter_freeze": True,
            "router_arbiter_hitl": True,
            "router_arbiter_escalated": True,
            "outer_session_id": "outer-a",
            "core_session_id": "outer-a__core",
            "execution_session_id": "outer-a__core",
            "router_decision": {"trace_id": "trace-a", "task_id": "task-a"},
        }
        api_server._emit_chat_route_arbiter_event(route_meta, session_id="outer-a")
        assert len(capture.rows) == 1
        row = capture.rows[0]
        assert row["event_type"] == "RouteArbiterGuardEscalatedCritical"
        assert row["payload"]["router_arbiter_delegate_turns"] == 3
        assert row["payload"]["router_arbiter_escalated"] is True
    finally:
        api_server._CHAT_ROUTE_EVENT_STORE = original_store


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


def test_route_decision_sse_chunk_json_protocol() -> None:
    payload = {"type": "route_decision", "path": "path-c", "risk_level": "write_repo"}
    chunk = api_server._format_stream_payload_chunk(payload, protocol="sse_json_v1")
    assert chunk.startswith("data: ")
    payload_text = chunk[len("data: ") :].strip()
    decoded = json.loads(payload_text)
    assert decoded == payload


def test_resolve_stream_protocol_aliases() -> None:
    assert api_server._resolve_stream_protocol(None) == "sse_json_v1"
    assert api_server._resolve_stream_protocol("") == "sse_json_v1"
    assert api_server._resolve_stream_protocol("sse_json_v1") == "sse_json_v1"
    assert api_server._resolve_stream_protocol("json") == "sse_json_v1"
    assert api_server._resolve_stream_protocol("structured") == "sse_json_v1"


def test_legacy_stream_protocol_requests_are_detected() -> None:
    assert api_server._is_legacy_stream_protocol_requested("sse_base64")
    assert api_server._is_legacy_stream_protocol_requested("legacy")
    assert api_server._is_legacy_stream_protocol_requested("compat")
    assert not api_server._is_legacy_stream_protocol_requested("sse_json_v1")


def test_supported_stream_protocol_validation() -> None:
    assert api_server._is_supported_stream_protocol_requested(None)
    assert api_server._is_supported_stream_protocol_requested("")
    assert api_server._is_supported_stream_protocol_requested("sse_json_v1")
    assert api_server._is_supported_stream_protocol_requested("json")
    assert api_server._is_supported_stream_protocol_requested("legacy")
    assert not api_server._is_supported_stream_protocol_requested("protobuf_v9")


def test_build_stream_response_headers_sets_protocol_header_only() -> None:
    headers = api_server._build_stream_response_headers(protocol="sse_json_v1")
    assert headers["X-Embla-Stream-Protocol"] == "sse_json_v1"
    assert "Deprecation" not in headers
    assert "Sunset" not in headers


def test_chat_stream_rejects_legacy_stream_protocol() -> None:
    request = api_server.ChatRequest(message="hello", stream=True, stream_protocol="legacy")
    with pytest.raises(api_server.HTTPException) as exc:
        asyncio.run(api_server.chat_stream(request))
    assert exc.value.status_code == 410
    assert isinstance(exc.value.detail, dict)
    assert exc.value.detail.get("error") == "legacy_stream_protocol_decommissioned"


def test_chat_stream_rejects_unknown_stream_protocol() -> None:
    request = api_server.ChatRequest(message="hello", stream=True, stream_protocol="protobuf_v9")
    with pytest.raises(api_server.HTTPException) as exc:
        asyncio.run(api_server.chat_stream(request))
    assert exc.value.status_code == 400
    assert isinstance(exc.value.detail, dict)
    assert exc.value.detail.get("error") == "unsupported_stream_protocol"
