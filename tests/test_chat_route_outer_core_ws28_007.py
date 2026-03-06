from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import apiserver.api_server as api_server
import pytest


def test_api_server_legacy_pre_route_helpers_not_eagerly_bound() -> None:
    # Runtime chat_stream is dispatch_to_core_only; pre-route helpers should
    # not be eagerly imported into api_server globals.
    assert "_resolve_chat_stream_route" not in api_server.__dict__
    assert "_apply_chat_route_quality_guard" not in api_server.__dict__
    assert "_apply_path_b_clarify_budget" not in api_server.__dict__
    assert "_apply_chat_route_router_arbiter_guard" not in api_server.__dict__


def test_chat_route_prompt_event_payload_prefers_gateway_compose_metrics() -> None:
    payload = api_server._build_chat_route_prompt_event_payload(
        {
            "path": "path-a",
            "risk_level": "read_only",
            "_slice_selected": ["outer_shell_base", "outer_memory_recall", "outer_route_contract"],
            "_slice_dropped": ["outer_write_tool_contract"],
            "_slice_selected_count": 3,
            "_slice_dropped_count": 1,
            "_slice_dropped_conflict_count": 1,
            "_slice_selected_layers": ["L0_DNA", "L1_5_EPISODIC_MEMORY", "L2_ROLE"],
            "_slice_selected_layer_counts": {"L0_DNA": 1, "L1_5_EPISODIC_MEMORY": 1, "L2_ROLE": 1},
            "_slice_recovery_hit": True,
            "_slice_prefix_hash": "abc123",
            "_slice_tail_hash": "tail456",
            "_slice_prefix_cache_hit": True,
            "_slice_block1_cache_hit": True,
            "_slice_block2_cache_hit": True,
            "_slice_token_budget_before": 2800,
            "_slice_token_budget_after": 1920,
            "_slice_model_tier": "secondary",
            "_slice_model_id": "gpt-4.1-mini",
            "router_decision": {
                "delegation_intent": "read_only_exploration",
                "prompt_profile": "outer_readonly_general",
                "injection_mode": "minimal",
                "selected_model_tier": "primary",
            },
        }
    )

    assert payload["selected_slice_count"] == 3
    assert payload["dropped_slice_count"] == 1
    assert payload["dropped_conflict_count"] == 1
    assert payload["selected_layer_counts"] == {"L0_DNA": 1, "L1_5_EPISODIC_MEMORY": 1, "L2_ROLE": 1}
    assert payload["recovery_hit"] is True
    assert payload["prefix_cache_hit"] is True
    assert payload["block1_cache_hit"] is True
    assert payload["block2_cache_hit"] is True
    assert payload["token_budget_before"] == 2800
    assert payload["token_budget_after"] == 1920
    assert payload["model_tier"] == "secondary"
    assert payload["model_id"] == "gpt-4.1-mini"


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


def test_resolve_stream_protocol_is_strict() -> None:
    assert api_server._resolve_stream_protocol(None) == "sse_json_v1"
    assert api_server._resolve_stream_protocol("") == "sse_json_v1"
    assert api_server._resolve_stream_protocol("sse_json_v1") == "sse_json_v1"
    with pytest.raises(ValueError):
        api_server._resolve_stream_protocol("json")
    with pytest.raises(ValueError):
        api_server._resolve_stream_protocol("legacy")
    with pytest.raises(ValueError):
        api_server._resolve_stream_protocol("protobuf_v9")


def test_build_stream_response_headers_sets_protocol_header_only() -> None:
    headers = api_server._build_stream_response_headers(protocol="sse_json_v1")
    assert headers["X-Embla-Stream-Protocol"] == "sse_json_v1"
    assert "Deprecation" not in headers
    assert "Sunset" not in headers


def test_chat_stream_rejects_legacy_stream_protocol_as_unsupported() -> None:
    request = api_server.ChatRequest(message="hello", stream=True, stream_protocol="legacy")
    with pytest.raises(api_server.HTTPException) as exc:
        asyncio.run(api_server.chat_stream(request))
    assert exc.value.status_code == 400
    assert isinstance(exc.value.detail, dict)
    assert exc.value.detail.get("error") == "unsupported_stream_protocol"


def test_chat_stream_rejects_unknown_stream_protocol() -> None:
    request = api_server.ChatRequest(message="hello", stream=True, stream_protocol="protobuf_v9")
    with pytest.raises(api_server.HTTPException) as exc:
        asyncio.run(api_server.chat_stream(request))
    assert exc.value.status_code == 400
    assert isinstance(exc.value.detail, dict)
    assert exc.value.detail.get("error") == "unsupported_stream_protocol"


def test_chat_stream_dispatch_to_core_triggers_real_core_pipeline(monkeypatch) -> None:
    class _FakeLLMService:
        def __init__(self) -> None:
            self.calls = 0

        def stream_chat_with_context(self, messages, temperature, model_override=None, tools=None, tool_choice="auto"):
            del messages, temperature, model_override, tools, tool_choice
            self.calls += 1

            async def _gen():
                if self.calls == 1:
                    yield (
                        'data: {"type":"tool_calls","text":[{"id":"call_1","name":"dispatch_to_core",'
                        '"arguments":{"goal":"修复后端bug","intent_type":"development","target_repo":"external"}}]}\n\n'
                    )
                yield "data: [DONE]\n\n"

            return _gen()

    fake_llm = _FakeLLMService()
    pipeline_calls = []
    deferred_emits = []

    async def _fake_run_multi_agent_pipeline(**kwargs):
        pipeline_calls.append(dict(kwargs))
        assert str(kwargs.get("forced_path") or "") == "path-c"
        yield {
            "type": "child_spawn_deferred",
            "pipeline_id": "pipe-test-001",
            "agent_id": "review-child-001",
            "source": "spawn",
            "role": "review",
            "reason": "spawn_deferred_role",
        }
        yield {
            "type": "execution_receipt",
            "agent_state": {
                "task_completed": True,
                "final_answer": "core pipeline finished",
            },
        }
        yield {
            "type": "pipeline_end",
            "reason": "completed",
        }

    async def _collect_payloads(response):
        rows = []
        async for chunk in response.body_iterator:
            text = chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk)
            for line in text.splitlines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:].strip()
                if not raw or raw == "[DONE]":
                    continue
                rows.append(json.loads(raw))
        return rows

    monkeypatch.setattr(api_server, "get_llm_service", lambda: fake_llm)
    monkeypatch.setattr(api_server, "run_multi_agent_pipeline", _fake_run_multi_agent_pipeline)
    monkeypatch.setattr(
        api_server,
        "_emit_core_child_spawn_deferred_event",
        lambda **kwargs: deferred_emits.append(dict(kwargs)),
    )

    async def _no_memory(_question: str, *, limit: int = 5):
        del limit
        return []

    monkeypatch.setattr(api_server, "_recall_memory_lines", _no_memory)

    req = api_server.ChatRequest(
        message="请修复一个后端 bug 并提交",
        stream=True,
        session_id="dispatch-only-route-session",
        stream_protocol="sse_json_v1",
        temporary=True,
    )
    response = asyncio.run(api_server.chat_stream(req))
    payloads = asyncio.run(_collect_payloads(response))

    tool_results = [item for item in payloads if item.get("type") == "tool_result"]
    assert any(item.get("tool_name") == "dispatch_to_core" for item in tool_results)

    route_events = [item for item in payloads if item.get("type") == "route_decision"]
    assert len(route_events) >= 2
    assert route_events[0].get("routing_mode") == "dispatch_to_core_only"
    assert any(
        item.get("routing_mode") == "dispatch_to_core_tool" and item.get("handoff_source") == "dispatch_to_core"
        for item in route_events
    )

    assert len(pipeline_calls) == 1
    assert str(pipeline_calls[0].get("forced_path") or "") == "path-c"
    assert len(deferred_emits) == 1
    assert str(deferred_emits[0]["chunk_data"].get("agent_id") or "") == "review-child-001"
    assert str(deferred_emits[0]["chunk_data"].get("reason") or "") == "spawn_deferred_role"

    bridge_payload = api_server._build_chat_route_bridge_payload("dispatch-only-route-session", limit=20)
    assert bridge_payload["outer_session_id"] == "dispatch-only-route-session"
    assert str(bridge_payload["core_session_id"]).endswith("__core")
    assert bridge_payload["execution_session_id"] == bridge_payload["core_session_id"]
    assert bridge_payload["core_session_exists"] is True
    assert isinstance(bridge_payload["recent_route_events"], list)
    assert len(bridge_payload["recent_route_events"]) >= 1
    assert any(str(item.get("path") or "") == "path-c" for item in bridge_payload["recent_route_events"])
    assert any(
        str(item.get("core_session_id") or "") == str(bridge_payload["core_session_id"])
        for item in bridge_payload["recent_route_events"]
    )

    fallback_content_rows = [
        item for item in payloads if item.get("type") == "content" and item.get("source") == "execution_receipt_fallback"
    ]
    assert fallback_content_rows
    assert fallback_content_rows[-1].get("text") == "core pipeline finished"

    api_server.message_manager.delete_session("dispatch-only-route-session")
    api_server.message_manager.delete_session("dispatch-only-route-session__core")


def test_extract_agentic_execution_receipt_text_prefers_final_answer() -> None:
    payload = {
        "type": "execution_receipt",
        "agent_state": {
            "completion_summary": "summary-text",
            "final_answer": "final-answer-text",
        },
    }
    assert api_server._extract_agentic_execution_receipt_text(payload) == "final-answer-text"


def test_extract_agentic_execution_receipt_text_falls_back_to_summary_and_deliverables() -> None:
    summary_payload = {
        "type": "execution_receipt",
        "agent_state": {
            "completion_summary": "summary-only",
        },
    }
    assert api_server._extract_agentic_execution_receipt_text(summary_payload) == "summary-only"

    deliverables_payload = {
        "type": "execution_receipt",
        "agent_state": {
            "deliverables": ["artifact/a.txt", "artifact/b.txt"],
        },
    }
    assert api_server._extract_agentic_execution_receipt_text(deliverables_payload) == "artifact/a.txt\nartifact/b.txt"


def test_extract_agentic_execution_receipt_text_ignores_non_receipt_payload() -> None:
    payload = {"type": "content", "text": "hello"}
    assert api_server._extract_agentic_execution_receipt_text(payload) == ""


def test_build_shell_system_prompt_with_gateway_updates_slice_metadata() -> None:
    route_meta = {
        "path": "path-a",
        "risk_level": "read_only",
        "router_decision": {
            "task_type": "research",
            "prompt_profile": "outer_readonly_research",
            "injection_mode": "minimal",
            "delegation_intent": "read_only_exploration",
            "trace_id": "trace-shell-gw",
        },
    }
    prompt = api_server._build_shell_system_prompt_with_gateway(
        route_meta=route_meta,
        base_system_prompt="SHELL_BASE_PROMPT",
        memory_lines=["- 记忆A", "- 记忆B"],
    )

    assert "SHELL_BASE_PROMPT" in prompt
    assert "PromptRouteDecision" in prompt
    assert "Route policy: Outer Direct Read-Only" in prompt
    assert "## 相关记忆" in prompt
    assert route_meta.get("_slice_selected_count", 0) >= 2
    assert "outer_shell_base" in route_meta.get("_slice_selected", [])
    assert str(route_meta.get("_slice_prefix_hash") or "").strip()


def test_build_shell_system_prompt_with_gateway_falls_back_when_gateway_missing(monkeypatch) -> None:
    route_meta = {
        "path": "path-b",
        "risk_level": "unknown",
        "router_decision": {
            "task_type": "general",
            "prompt_profile": "outer_general",
            "injection_mode": "standard",
            "delegation_intent": "general_assistance",
        },
    }
    original_gateway = api_server._CHAT_LLM_GATEWAY
    monkeypatch.setattr(api_server, "_CHAT_LLM_GATEWAY", None)
    try:
        prompt = api_server._build_shell_system_prompt_with_gateway(
            route_meta=route_meta,
            base_system_prompt="FALLBACK_BASE",
            memory_lines=["- memory line"],
        )
    finally:
        monkeypatch.setattr(api_server, "_CHAT_LLM_GATEWAY", original_gateway)

    assert "FALLBACK_BASE" in prompt
    assert "PromptRouteDecision" in prompt
    assert "Route policy: Outer Clarify" in prompt
    assert "## 相关记忆" in prompt
