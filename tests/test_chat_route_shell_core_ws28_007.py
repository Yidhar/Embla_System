from __future__ import annotations

import asyncio
import json
import tempfile
from types import SimpleNamespace

import apiserver.api_server as api_server
import apiserver.core_job_manager as core_job_manager_module
from agents.runtime.agent_session import AgentSessionStore, AgentStatus
from agents.runtime.mailbox import AgentMailbox
from agents.runtime.task_board import TaskBoardEngine, TaskItem, TaskStatus
from apiserver import routes_chat
import pytest


def test_api_server_legacy_pre_route_helpers_not_eagerly_bound() -> None:
    # Runtime chat_stream is dispatch_to_core_only; pre-route helpers should
    # not be eagerly imported into api_server globals.
    assert "_resolve_chat_stream_route" not in api_server.__dict__
    assert "_apply_chat_route_quality_guard" not in api_server.__dict__
    assert "_apply_shell_clarify_budget" not in api_server.__dict__
    assert "_apply_chat_route_router_arbiter_guard" not in api_server.__dict__


def test_chat_route_prompt_event_payload_prefers_gateway_compose_metrics() -> None:
    payload = api_server._build_chat_route_prompt_event_payload(
        {
            "route_semantic": "shell_readonly",
            "risk_level": "read_only",
            "_slice_selected": ["shell_base", "shell_memory_recall", "shell_route_contract"],
            "_slice_dropped": ["shell_write_tool_contract"],
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
                "prompt_profile": "shell_readonly_general",
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


def test_chat_route_prompt_event_payload_treats_empty_tail_as_block1_only_cache_hit() -> None:
    payload = api_server._build_chat_route_prompt_event_payload(
        {
            "route_semantic": "shell_readonly",
            "_slice_prefix_hash": "abc123",
            "_slice_tail_hash": "",
            "_slice_prefix_cache_hit": True,
            "_slice_block1_cache_hit": True,
            "_slice_block2_cache_hit": False,
            "router_decision": {},
        }
    )

    assert payload["tail_hash"] == ""
    assert payload["block1_cache_hit"] is True
    assert payload["block2_cache_hit"] is False


def test_enrich_child_tool_result_metadata_uses_session_fallback_metadata() -> None:
    store = AgentSessionStore(db_path=":memory:")
    try:
        store.create(
            role="dev",
            session_id="agent-fallback-meta",
            metadata={
                "execution_backend": "native",
                "box_fallback_reason": "boxlite_kvm_inaccessible:Permission denied",
                "execution_root": "/tmp/embla-worktree",
            },
        )

        enriched = api_server._enrich_child_tool_result_metadata(
            {
                "tool_call": {"tool_name": "read_file"},
                "result": "ok",
                "status": "success",
                "service_name": "native",
                "tool_name": "read_file",
            },
            child_session_id="agent-fallback-meta",
            session_store=store,
        )

        assert enriched["execution_backend"] == "native"
        assert enriched["box_fallback_reason"] == "boxlite_kvm_inaccessible:Permission denied"
        assert enriched["execution_root"] == "/tmp/embla-worktree"
    finally:
        store.close()


def test_enrich_child_tool_result_metadata_prefers_explicit_payload_values() -> None:
    enriched = api_server._enrich_child_tool_result_metadata(
        {
            "tool_call": {"tool_name": "read_file", "_execution_backend": "boxlite", "_execution_root": "/workspace"},
            "result": "ok",
            "status": "success",
            "service_name": "boxlite",
            "tool_name": "read_file",
            "execution_backend": "native",
            "box_fallback_reason": "fallback_from_boxlite",
            "execution_root": "/host/worktree",
        },
        child_session_id="missing-session",
        session_store=None,
    )

    assert enriched["execution_backend"] == "native"
    assert enriched["box_fallback_reason"] == "fallback_from_boxlite"
    assert enriched["execution_root"] == "/host/worktree"


def test_format_sse_payload_chunk_json_sanitizes_non_json_values() -> None:
    class _NonJson:
        pass

    rendered = routes_chat._format_sse_payload_chunk_json(
        {"type": "review_loop_event", "opaque": _NonJson(), "items": [_NonJson()]}
    )

    assert rendered.startswith("data: ")
    payload = json.loads(rendered[len("data: ") :].strip())
    assert payload["opaque"] == "<non-json:_NonJson>"
    assert payload["items"] == ["<non-json:_NonJson>"]


def test_build_route_model_override_resolves_shell_and_core_targets(monkeypatch) -> None:
    fake_cfg = SimpleNamespace(
        api=SimpleNamespace(
            routing=SimpleNamespace(
                shell=SimpleNamespace(
                    api_key="shell-key",
                    base_url="https://shell.example/v1",
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

    shell = api_server._build_route_model_override("shell_readonly")
    core = api_server._build_route_model_override("core_execution")

    assert shell == {
        "api_key": "shell-key",
        "api_base": "https://shell.example/v1",
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
    base = {"model": "gpt-4.1-mini", "api_base": "https://shell.example/v1", "provider": "openai_compatible"}
    high = {"model": "gpt-5.2", "api_key": "core-key"}

    merged = api_server._merge_model_override(base, high)

    assert merged == {
        "model": "gpt-5.2",
        "api_base": "https://shell.example/v1",
        "provider": "openai_compatible",
        "api_key": "core-key",
    }


def test_route_prompt_event_payload_contains_router_arbiter_fields() -> None:
    payload = api_server._build_chat_route_prompt_event_payload(
        {
            "route_semantic": "core_execution",
            "risk_level": "write_repo",
            "shell_readonly_hit": False,
            "core_execution_hit": True,
            "router_arbiter_status": "critical",
            "router_arbiter_applied": True,
            "router_arbiter_action": "freeze_to_core",
            "router_arbiter_reason": "router_arbiter_ping_pong_freeze_core",
            "router_arbiter_reason_codes": ["ROUTER_ARBITER_PING_PONG_FREEZE_CORE"],
            "router_arbiter_route_semantic_before": "shell_readonly",
            "router_arbiter_route_semantic_after": "core_execution",
            "router_arbiter_delegate_turns": 3,
            "router_arbiter_max_delegate_turns": 3,
            "router_arbiter_conflict_ticket": "chat_route_ping_pong::shell_readonly|core_execution",
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
    assert payload["router_arbiter_conflict_ticket"] == "chat_route_ping_pong::shell_readonly|core_execution"
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
            "route_semantic": "core_execution",
            "risk_level": "write_repo",
            "router_arbiter_status": "critical",
            "router_arbiter_applied": True,
            "router_arbiter_action": "freeze_to_core",
            "router_arbiter_reason": "router_arbiter_ping_pong_freeze_core",
            "router_arbiter_reason_codes": ["ROUTER_ARBITER_PING_PONG_FREEZE_CORE"],
            "router_arbiter_route_semantic_before": "shell_readonly",
            "router_arbiter_route_semantic_after": "core_execution",
            "router_arbiter_delegate_turns": 3,
            "router_arbiter_max_delegate_turns": 3,
            "router_arbiter_conflict_ticket": "chat_route_ping_pong::shell_readonly|core_execution",
            "router_arbiter_freeze": True,
            "router_arbiter_hitl": True,
            "router_arbiter_escalated": True,
            "shell_session_id": "shell-a",
            "run_context_id": "shell-a__core",
            "core_execution_session_id": "shell-a__core",
            "router_decision": {"trace_id": "trace-a", "task_id": "task-a"},
        }
        api_server._emit_chat_route_arbiter_event(route_meta, session_id="shell-a")
        assert len(capture.rows) == 1
        row = capture.rows[0]
        assert row["event_type"] == "RouteArbiterGuardEscalatedCritical"
        assert row["payload"]["router_arbiter_delegate_turns"] == 3
        assert row["payload"]["router_arbiter_escalated"] is True
    finally:
        api_server._CHAT_ROUTE_EVENT_STORE = original_store


def test_shell_core_session_state_sets_long_lived_core_runtime_for_core_execution() -> None:
    shell_session_id = api_server.message_manager.create_session(temporary=True)
    try:
        route_meta = {
            "route_semantic": "core_execution",
            "shell_readonly_hit": False,
            "core_execution_hit": True,
            "router_decision": {"delegation_intent": "core_execution"},
        }
        updated = api_server._apply_shell_core_session_state(route_meta, shell_session_id=shell_session_id)
        assert updated["shell_session_id"] == shell_session_id
        assert updated["core_runtime_id"] == "core-main"
        assert updated["core_job_id"] == ""
        assert updated["run_context_id"] == ""
        assert updated["run_context_created"] is False
        assert updated["dispatch_to_core"] is True
        assert updated["active_agent"] == "core"
        assert updated["handoff_tool"] == "dispatch_to_core"
    finally:
        api_server.message_manager.delete_session(shell_session_id)


def test_register_core_job_submission_updates_latest_core_job_state() -> None:
    shell_session_id = api_server.message_manager.create_session(temporary=True)
    try:
        route_meta = api_server._apply_shell_core_session_state(
            {"route_semantic": "core_execution", "router_decision": {"delegation_intent": "core_execution"}},
            shell_session_id=shell_session_id,
        )
        updated = api_server._register_core_job_submission(
            shell_session_id,
            core_runtime_id="core-main",
            core_job_id="corejob_001",
            core_execution_session_id=f"{shell_session_id}__core",
            route_meta=route_meta,
        )
        assert updated["core_runtime_id"] == "core-main"
        assert updated["core_job_id"] == "corejob_001"
        assert updated["run_context_id"] == f"{shell_session_id}__core"
        assert updated["run_context_created"] is True

        session = api_server.message_manager.get_session(shell_session_id)
        assert isinstance(session, dict)
        state = session[api_server._CHAT_ROUTE_STATE_KEY]
        assert state["active_core_job_id"] == "corejob_001"
        assert state["last_core_job_id"] == "corejob_001"
        assert state["run_context_id"] == f"{shell_session_id}__core"
    finally:
        api_server.message_manager.delete_session(shell_session_id)


def test_shell_core_session_state_overrides_stale_shell_semantic_fields() -> None:
    shell_session_id = api_server.message_manager.create_session(temporary=True)
    try:
        updated = api_server._apply_shell_core_session_state(
            {
                "route_semantic": "core_execution",
                "dispatch_to_core": False,
                "active_agent": "shell",
                "handoff_tool": "",
                "router_decision": {"delegation_intent": "core_execution"},
            },
            shell_session_id=shell_session_id,
        )
        assert updated["route_semantic"] == "core_execution"
        assert updated["dispatch_to_core"] is True
        assert updated["active_agent"] == "core"
        assert updated["handoff_tool"] == "dispatch_to_core"
    finally:
        api_server.message_manager.delete_session(shell_session_id)


def test_shell_core_session_state_keeps_shell_for_non_core_execution_route() -> None:
    shell_session_id = api_server.message_manager.create_session(temporary=True)
    try:
        updated = api_server._apply_shell_core_session_state(
            {"route_semantic": "shell_readonly", "router_decision": {"delegation_intent": "read_only_exploration"}},
            shell_session_id=shell_session_id,
        )
        assert updated["shell_session_id"] == shell_session_id
        assert updated["run_context_id"] == ""
        assert updated["run_context_created"] is False
    finally:
        api_server.message_manager.delete_session(shell_session_id)


def test_route_decision_sse_chunk_json_protocol() -> None:
    payload = {"type": "route_decision", "route_semantic": "core_execution", "risk_level": "write_repo"}
    chunk = api_server._format_stream_payload_chunk(payload, protocol="sse_json_v1")
    assert chunk.startswith("data: ")
    payload_text = chunk[len("data: ") :].strip()
    decoded = json.loads(payload_text)
    assert decoded == payload


def test_shell_readonly_prompt_hints_allow_readonly_tools() -> None:
    prompt_hints = api_server._build_chat_route_prompt_hints(
        {
            "route_semantic": "shell_readonly",
            "dispatch_to_core": False,
            "router_decision": {"delegation_intent": "read_only_exploration"},
            "_shell_available_tool_names": ["memory_read", "get_system_status", "dispatch_to_core"],
            "_shell_available_tool_count": 3,
        }
    )

    assert "Do not call tools" not in prompt_hints
    assert "read-only Shell tools" in prompt_hints
    assert "dispatch_to_core" in prompt_hints
    assert "current_turn_tool_count=3" in prompt_hints
    assert "memory_read, get_system_status, dispatch_to_core" in prompt_hints
    assert "Use native tool calling only." in prompt_hints
    assert "<assistant to=tool>" in prompt_hints


def test_select_shell_tool_choice_prefers_explicit_single_tool() -> None:
    choice = api_server._select_shell_tool_choice(
        "请先列出工具，再只调用 get_system_status",
        ["memory_read", "get_system_status", "dispatch_to_core"],
    )

    assert isinstance(choice, dict)
    assert choice["type"] == "function"
    assert choice["function"]["name"] == "get_system_status"


def test_select_shell_tool_choice_defaults_to_auto_without_unique_match() -> None:
    choice = api_server._select_shell_tool_choice(
        "请总结当前系统状态",
        ["memory_read", "get_system_status", "dispatch_to_core"],
    )
    assert choice == "auto"


def test_select_shell_tool_choice_ignores_negated_single_tool_mentions() -> None:
    choice = api_server._select_shell_tool_choice(
        "请列出当前工具，并说明哪个工具用于升级到 Core。禁止调用 dispatch_to_core。",
        ["memory_read", "get_system_status", "dispatch_to_core"],
    )
    assert choice == "auto"


def test_route_prompt_hints_include_guard_lines_from_prompt_blocks() -> None:
    prompt_hints = api_server._build_chat_route_prompt_hints(
        {
            "route_semantic": "core_execution",
            "dispatch_to_core": True,
            "route_quality_guard_applied": True,
            "route_quality_guard_status": "warning",
            "route_quality_guard_action": "freeze_to_core",
            "router_arbiter_status": "critical",
            "router_arbiter_action": "freeze_to_core",
            "router_decision": {
                "delegation_intent": "core_execution",
                "prompt_profile": "core_exec_dev",
                "injection_mode": "minimal",
            },
        }
    )

    assert "[PromptRouteDecision]" in prompt_hints
    assert "route_quality_guard=warning:freeze_to_core" in prompt_hints
    assert "router_arbiter_guard=critical:freeze_to_core" in prompt_hints
    assert "Route policy: Core Execution." in prompt_hints


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


def test_shell_tools_endpoint_returns_shell_catalog() -> None:
    payload = asyncio.run(api_server.get_shell_tools_v1())

    assert payload["status"] == "success"
    assert payload["agent"] == "shell"
    assert payload["count"] == len(payload["tool_names"])
    assert "dispatch_to_core" in payload["tool_names"]
    assert "memory_search" in payload["tool_names"]


def test_chat_stream_emits_shell_available_tools_event(monkeypatch) -> None:
    class _FakeLLMService:
        def stream_chat_with_context(self, messages, temperature, model_override=None, tools=None, tool_choice="auto"):
            del messages, temperature, model_override, tools, tool_choice

            async def _gen():
                yield "data: {\"type\":\"content\",\"text\":\"hello\"}\n\n"
                yield "data: [DONE]\n\n"

            return _gen()

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

    async def _no_memory(_question: str, *, limit: int = 5):
        del limit
        return []

    monkeypatch.setattr(api_server, "get_llm_service", lambda: _FakeLLMService())
    monkeypatch.setattr(api_server, "_recall_memory_lines", _no_memory)

    req = api_server.ChatRequest(
        message="总结当前系统状态",
        stream=True,
        session_id="shell-tools-stream-session",
        stream_protocol="sse_json_v1",
        temporary=True,
    )
    response = asyncio.run(api_server.chat_stream(req))
    payloads = asyncio.run(_collect_payloads(response))

    assert payloads[0]["type"] == "session_meta"
    available_tools = next(item for item in payloads if item.get("type") == "available_tools")
    assert available_tools["agent"] == "shell"
    assert available_tools["scope"] == "entry"
    assert "dispatch_to_core" in available_tools["tool_names"]
    assert any(str(tool.get("name") or "") == "memory_read" for tool in available_tools["tools"])
    assert any(item.get("type") == "route_decision" for item in payloads)


def test_chat_stream_explicit_shell_tool_request_forces_tool_choice(monkeypatch) -> None:
    captured_tool_choices = []

    class _FakeLLMService:
        def stream_chat_with_context(self, messages, temperature, model_override=None, tools=None, tool_choice="auto"):
            del messages, temperature, model_override, tools
            captured_tool_choices.append(tool_choice)

            async def _gen():
                yield "data: {\"type\":\"content\",\"text\":\"ok\"}\n\n"
                yield "data: [DONE]\n\n"

            return _gen()

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

    async def _no_memory(_question: str, *, limit: int = 5):
        del limit
        return []

    monkeypatch.setattr(api_server, "get_llm_service", lambda: _FakeLLMService())
    monkeypatch.setattr(api_server, "_recall_memory_lines", _no_memory)

    req = api_server.ChatRequest(
        message="只调用 get_system_status，不要做别的事",
        stream=True,
        session_id="explicit-shell-tool-choice-session",
        stream_protocol="sse_json_v1",
        temporary=True,
    )
    response = asyncio.run(api_server.chat_stream(req))
    payloads = asyncio.run(_collect_payloads(response))

    assert payloads[0]["type"] == "session_meta"
    assert captured_tool_choices
    assert isinstance(captured_tool_choices[0], dict)
    assert captured_tool_choices[0]["function"]["name"] == "get_system_status"


def test_chat_stream_negated_tool_reference_does_not_force_tool_choice(monkeypatch) -> None:
    captured_tool_choices = []

    class _FakeLLMService:
        def stream_chat_with_context(self, messages, temperature, model_override=None, tools=None, tool_choice="auto"):
            del messages, temperature, model_override, tools
            captured_tool_choices.append(tool_choice)

            async def _gen():
                yield "data: {\"type\":\"content\",\"text\":\"ok\"}\n\n"
                yield "data: [DONE]\n\n"

            return _gen()

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

    async def _no_memory(_question: str, *, limit: int = 5):
        del limit
        return []

    monkeypatch.setattr(api_server, "get_llm_service", lambda: _FakeLLMService())
    monkeypatch.setattr(api_server, "_recall_memory_lines", _no_memory)

    req = api_server.ChatRequest(
        message="请列出当前 Shell 可用工具，并说明哪个工具用于升级到 Core。禁止调用 dispatch_to_core。",
        stream=True,
        session_id="negated-shell-tool-choice-session",
        stream_protocol="sse_json_v1",
        temporary=True,
    )
    response = asyncio.run(api_server.chat_stream(req))
    payloads = asyncio.run(_collect_payloads(response))

    assert payloads[0]["type"] == "session_meta"
    assert captured_tool_choices
    assert captured_tool_choices[0] == "auto"



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

    async def _fake_run_multi_agent_pipeline(**kwargs):
        pipeline_calls.append(dict(kwargs))
        assert str(kwargs.get("forced_route_semantic") or "") == "core_execution"
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
    monkeypatch.setattr(api_server, "_CORE_JOB_MANAGER", api_server.CoreDispatchJobManager())

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
    accepted = next(item for item in payloads if item.get("type") == "core_job_accepted")
    assert accepted["core_runtime_id"] == "core-main"
    assert str(accepted["core_job_id"]).startswith("corejob_")
    assert str(accepted["run_context_id"]) == "dispatch-only-route-session__core"
    assert isinstance(accepted["run_context_created"], bool)
    assert int(accepted["handoff_message_seq"]) > 0
    assert int(accepted["handoff_duplicate_count"]) == 0
    assert int(accepted["recovery_restart_count"]) == 0
    assert int(accepted["inbox_dedup_skipped_count"]) == 0
    assert accepted["worker_status"] == "running"
    assert int(accepted["queue_position"]) >= 1
    assert int(accepted["pipeline_depth"]) >= int(accepted["queue_position"])

    assert len(pipeline_calls) == 1
    assert str(pipeline_calls[0].get("message") or "") == "修复后端bug"
    assert str(pipeline_calls[0].get("forced_route_semantic") or "") == "core_execution"

    job_payload = api_server._get_core_job_manager().get_job_snapshot(accepted["core_job_id"])
    recent_event_types = [str(item.get("type") or "") for item in job_payload.get("recent_events") or []]
    assert "child_spawn_deferred" in recent_event_types
    assert "execution_receipt" in recent_event_types

    state_payload = api_server._build_chat_route_session_state_payload("dispatch-only-route-session", limit=20)
    assert state_payload["shell_session_id"] == "dispatch-only-route-session"
    assert state_payload["core_runtime_id"] == "core-main"
    assert state_payload["active_core_job_id"] == accepted["core_job_id"]
    assert state_payload["run_context_id"] == accepted["run_context_id"]
    assert state_payload["last_run_context_id"] == accepted["run_context_id"]
    assert state_payload["run_context_exists"] is True
    assert isinstance(state_payload["recent_route_events"], list)
    assert len(state_payload["recent_route_events"]) >= 1
    assert any(
        str(item.get("route_semantic") or "") == "core_execution" for item in state_payload["recent_route_events"]
    )
    assert any(
        str(item.get("run_context_id") or item.get("core_execution_session_id") or "") == str(state_payload["run_context_id"])
        for item in state_payload["recent_route_events"]
    )
    ack_rows = [item for item in payloads if item.get("type") == "content" and item.get("source") == "core_job_accept_ack"]
    assert ack_rows
    assert accepted["core_job_id"] in ack_rows[-1].get("text", "")

    api_server.message_manager.delete_session("dispatch-only-route-session")
    api_server.message_manager.delete_session(accepted["run_context_id"])


def test_pipeline_heartbeat_event_uses_summary_session_count() -> None:
    class _Store:
        def get_descendant_heartbeat_snapshot(self, _root_session_id):
            return {
                "root_session_id": "core-1",
                "summary": {
                    "session_count": 1,
                    "sessions_with_heartbeats": 0,
                    "task_count": 0,
                },
                "sessions": [],
                "heartbeats": [],
            }

    payload = api_server._build_pipeline_stream_heartbeat_event(
        pipeline_id="pipe-heartbeat-summary-1",
        shell_session_id="shell-1",
        core_execution_session_id="core-1",
        started_monotonic=0.0,
        last_event_type="pipeline_start",
        agent_session_store=_Store(),
    )

    assert payload["child_heartbeat_summary"]["session_count"] == 1
    assert payload["child_session_count"] == 1
    assert payload["child_heartbeat_count"] == 0


def test_chat_stream_returns_after_core_job_accept_without_waiting_for_pipeline(monkeypatch) -> None:
    class _FakeLLMService:
        def __init__(self) -> None:
            self.calls = 0

        def stream_chat_with_context(self, messages, temperature, model_override=None, tools=None, tool_choice="auto"):
            del messages, temperature, model_override, tools, tool_choice
            self.calls += 1

            async def _gen():
                if self.calls == 1:
                    yield (
                        'data: {"type":"tool_calls","text":[{"id":"call_heartbeat","name":"dispatch_to_core",'
                        '"arguments":{"goal":"审计后端链路","intent_type":"analysis","target_repo":"external"}}]}\n\n'
                    )
                yield "data: [DONE]\n\n"

            return _gen()

    async def _fake_run_multi_agent_pipeline(**kwargs):
        del kwargs
        await asyncio.sleep(1.1)
        yield {
            "type": "execution_receipt",
            "pipeline_id": "pipe-heartbeat-001",
            "agent_state": {
                "task_completed": True,
                "final_answer": "heartbeat pipeline finished",
            },
        }
        yield {
            "type": "pipeline_end",
            "pipeline_id": "pipe-heartbeat-001",
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

    async def _no_memory(_question: str, *, limit: int = 5):
        del limit
        return []

    monkeypatch.setattr(api_server, "get_llm_service", lambda: _FakeLLMService())
    monkeypatch.setattr(api_server, "run_multi_agent_pipeline", _fake_run_multi_agent_pipeline)
    monkeypatch.setattr(api_server, "_recall_memory_lines", _no_memory)
    monkeypatch.setattr(api_server, "_PIPELINE_STREAM_HEARTBEAT_INTERVAL_SECONDS", 1.0)
    monkeypatch.setattr(api_server, "_CORE_JOB_MANAGER", api_server.CoreDispatchJobManager())

    req = api_server.ChatRequest(
        message="请审计后端链路并回传报告",
        stream=True,
        session_id="dispatch-heartbeat-session",
        stream_protocol="sse_json_v1",
        temporary=True,
    )
    response = asyncio.run(api_server.chat_stream(req))
    payloads = asyncio.run(_collect_payloads(response))

    accepted = next(item for item in payloads if item.get("type") == "core_job_accepted")
    assert accepted["shell_session_id"] == "dispatch-heartbeat-session"
    assert accepted["core_runtime_id"] == "core-main"
    assert str(accepted["run_context_id"]) == "dispatch-heartbeat-session__core"
    assert isinstance(accepted["run_context_created"], bool)
    assert int(accepted["handoff_message_seq"]) > 0
    assert int(accepted["handoff_duplicate_count"]) == 0
    assert int(accepted["recovery_restart_count"]) == 0
    assert accepted["worker_status"] == "running"
    assert int(accepted["queue_position"]) >= 1
    assert not any(item.get("type") == "pipeline_heartbeat" for item in payloads)
    assert not any(item.get("type") == "execution_receipt" for item in payloads)

    api_server.message_manager.delete_session("dispatch-heartbeat-session")
    api_server.message_manager.delete_session(accepted["run_context_id"])



def test_chat_stream_emits_core_async_updates_before_shell_reply(monkeypatch) -> None:
    shell_session_id = "shell-core-async-prefetch"
    core_execution_session_id = f"{shell_session_id}__core"

    class _FakeLLMService:
        def stream_chat_with_context(self, messages, temperature, model_override=None, tools=None, tool_choice="auto"):
            del messages, temperature, model_override, tools, tool_choice

            async def _gen():
                yield "data: {\"type\":\"content\",\"text\":\"已继续处理当前只读问题。\"}\n\n"
                yield "data: [DONE]\n\n"

            return _gen()

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

    async def _no_memory(_question: str, *, limit: int = 5):
        del limit
        return []

    store = AgentSessionStore(db_path=":memory:")
    mailbox = AgentMailbox(db_path=":memory:")
    manager = api_server.CoreDispatchJobManager()
    api_server.message_manager.create_session(session_id=shell_session_id, temporary=True)
    api_server.message_manager.create_session(session_id=core_execution_session_id, temporary=True)
    api_server._register_core_job_submission(
        shell_session_id,
        core_runtime_id="core-main",
        core_job_id="corejob_async_prefetch_1",
        core_execution_session_id=core_execution_session_id,
    )
    mailbox.send(
        core_execution_session_id,
        shell_session_id,
        "[CORE RUNNING] job_id=corejob_async_prefetch_1 已开始执行：后台修复任务",
        message_type="status",
        metadata={
            "kind": "core_job_status",
            "status": "running",
            "core_job_id": "corejob_async_prefetch_1",
            "core_runtime_id": "core-main",
            "core_execution_session_id": core_execution_session_id,
        },
    )
    try:
        monkeypatch.setattr(api_server, "get_llm_service", lambda: _FakeLLMService())
        monkeypatch.setattr(api_server, "_recall_memory_lines", _no_memory)
        monkeypatch.setattr(api_server, "_CORE_JOB_MANAGER", manager)
        monkeypatch.setitem(api_server._routes_chat._CHAT_RUNTIME_CONTEXT, "agent_session_store", store)
        monkeypatch.setitem(api_server._routes_chat._CHAT_RUNTIME_CONTEXT, "agent_session_store_getter", None)
        monkeypatch.setitem(api_server._routes_chat._CHAT_RUNTIME_CONTEXT, "agent_mailbox", mailbox)
        monkeypatch.setitem(api_server._routes_chat._CHAT_RUNTIME_CONTEXT, "agent_mailbox_getter", None)
        monkeypatch.setitem(api_server._routes_chat._CHAT_RUNTIME_CONTEXT, "core_job_manager", manager)
        monkeypatch.setitem(api_server._routes_chat._CHAT_RUNTIME_CONTEXT, "core_job_manager_getter", None)

        req = api_server.ChatRequest(
            message="继续帮我查一下当前系统状态",
            stream=True,
            session_id=shell_session_id,
            stream_protocol="sse_json_v1",
            temporary=True,
        )
        response = asyncio.run(api_server.chat_stream(req))
        payloads = asyncio.run(_collect_payloads(response))

        async_state = next(item for item in payloads if item.get("type") == "core_async_state")
        assert async_state["source"] == "shell_turn_preflight"
        assert len(async_state["updates"]) == 1
        assert async_state["updates"][0]["status"] == "running"
        assert async_state["updates"][0]["core_job_id"] == "corejob_async_prefetch_1"

        inbox_payload = api_server._collect_chat_core_job_watch_payload(
            shell_session_id,
            core_execution_session_id=core_execution_session_id,
            limit=5,
            ack=False,
        )
        assert inbox_payload["pending_core_update_count"] == 0
        assert inbox_payload["unread_core_updates"] == []
    finally:
        asyncio.run(manager.shutdown())
        mailbox.close()
        store.close()
        api_server.message_manager.delete_session(shell_session_id)
        api_server.message_manager.delete_session(core_execution_session_id)


def test_chat_stream_stops_on_shell_progress_stall_and_forces_dispatch_to_core(monkeypatch) -> None:
    class _FakeLLMService:
        def __init__(self) -> None:
            self.calls = 0

        def stream_chat_with_context(self, messages, temperature, model_override=None, tools=None, tool_choice="auto"):
            del messages, temperature, model_override, tools, tool_choice
            self.calls += 1

            async def _gen():
                yield (
                    'data: {"type":"tool_calls","text":[{"id":"call_budget_%d","name":"memory_read",'
                    '"arguments":{"path":"agents/pipeline.py","start_line":1,"end_line":10}}]}\n\n'
                    % self.calls
                )
                yield "data: [DONE]\n\n"

            return _gen()

    pipeline_calls = []

    async def _fake_run_multi_agent_pipeline(**kwargs):
        pipeline_calls.append(dict(kwargs))
        yield {
            "type": "execution_receipt",
            "pipeline_id": "pipe-budget-fallback-001",
            "agent_state": {
                "task_completed": True,
                "final_answer": "budget fallback completed",
            },
        }
        yield {
            "type": "pipeline_end",
            "pipeline_id": "pipe-budget-fallback-001",
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

    async def _no_memory(_question: str, *, limit: int = 5):
        del limit
        return []

    def _fake_execute_tool(self, tool_name, arguments, *, session_id=""):
        del self, arguments, session_id
        if tool_name == "memory_read":
            return {"status": "success", "tool_name": "memory_read", "result": "ok"}
        raise AssertionError(f"unexpected tool {tool_name}")

    monkeypatch.setattr(api_server, "get_llm_service", lambda: _FakeLLMService())
    monkeypatch.setattr(api_server, "run_multi_agent_pipeline", _fake_run_multi_agent_pipeline)
    monkeypatch.setattr(api_server, "_recall_memory_lines", _no_memory)
    monkeypatch.setattr(api_server.ShellAgent, "execute_tool", _fake_execute_tool)
    monkeypatch.setattr(api_server, "_CORE_JOB_MANAGER", api_server.CoreDispatchJobManager())

    req = api_server.ChatRequest(
        message="审计 main.py 和 agents/pipeline.py，并把诊断结果写入 scratch/live_smoke/live_runtime_audit.md",
        stream=True,
        session_id="dispatch-budget-fallback-session",
        stream_protocol="sse_json_v1",
        temporary=True,
    )
    response = asyncio.run(api_server.chat_stream(req))
    payloads = asyncio.run(_collect_payloads(response))

    stalled = next(item for item in payloads if item.get("type") == "warning" and item.get("text") == "shell_tool_loop_stalled")
    assert "repeated_tool_pattern" in stalled["reasons"]
    assert any(item.get("type") == "warning" and item.get("text") == "shell_progress_force_dispatch_to_core" for item in payloads)
    route_events = [item for item in payloads if item.get("type") == "route_decision"]
    assert any(item.get("handoff_source") == "shell_progress_fallback" for item in route_events)
    assert len(pipeline_calls) == 1
    assert str(pipeline_calls[0].get("forced_route_semantic") or "") == "core_execution"
    state_payload = api_server._build_chat_route_session_state_payload("dispatch-budget-fallback-session", limit=5)

    api_server.message_manager.delete_session("dispatch-budget-fallback-session")
    api_server.message_manager.delete_session(state_payload["run_context_id"])


def test_chat_stream_uses_configured_shell_max_rounds_as_fuse(monkeypatch) -> None:
    class _FakeLLMService:
        def __init__(self) -> None:
            self.calls = 0

        def stream_chat_with_context(self, messages, temperature, model_override=None, tools=None, tool_choice="auto"):
            del messages, temperature, model_override, tools, tool_choice
            self.calls += 1

            async def _gen():
                yield (
                    'data: {"type":"tool_calls","text":[{"id":"call_budget_%d","name":"memory_read",'
                    '"arguments":{"path":"agents/pipeline.py","start_line":1,"end_line":10}}]}\n\n'
                    % self.calls
                )
                yield "data: [DONE]\n\n"

            return _gen()

    pipeline_calls = []

    async def _fake_run_multi_agent_pipeline(**kwargs):
        pipeline_calls.append(dict(kwargs))
        yield {
            "type": "execution_receipt",
            "pipeline_id": "pipe-budget-fallback-002",
            "agent_state": {
                "task_completed": True,
                "final_answer": "budget fallback completed",
            },
        }
        yield {
            "type": "pipeline_end",
            "pipeline_id": "pipe-budget-fallback-002",
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

    async def _no_memory(_question: str, *, limit: int = 5):
        del limit
        return []

    def _fake_execute_tool(self, tool_name, arguments, *, session_id=""):
        del self, arguments, session_id
        if tool_name == "memory_read":
            return {"status": "success", "tool_name": "memory_read", "result": "ok"}
        raise AssertionError(f"unexpected tool {tool_name}")

    cfg = api_server.get_config()
    original_shell_loop = cfg.api.shell_loop
    cfg.api.shell_loop = SimpleNamespace(
        max_rounds=2,
        repeated_tool_pattern_rounds=16,
        no_new_fact_rounds=16,
    )
    monkeypatch.setattr(api_server, "get_llm_service", lambda: _FakeLLMService())
    monkeypatch.setattr(api_server, "run_multi_agent_pipeline", _fake_run_multi_agent_pipeline)
    monkeypatch.setattr(api_server, "_recall_memory_lines", _no_memory)
    monkeypatch.setattr(api_server.ShellAgent, "execute_tool", _fake_execute_tool)
    monkeypatch.setattr(api_server, "_CORE_JOB_MANAGER", api_server.CoreDispatchJobManager())

    req = api_server.ChatRequest(
        message="审计 main.py 和 agents/pipeline.py，并把诊断结果写入 scratch/live_smoke/live_runtime_audit.md",
        stream=True,
        session_id="dispatch-budget-fallback-config-session",
        stream_protocol="sse_json_v1",
        temporary=True,
    )
    try:
        response = asyncio.run(api_server.chat_stream(req))
        payloads = asyncio.run(_collect_payloads(response))
    finally:
        cfg.api.shell_loop = original_shell_loop

    assert any(item.get("type") == "warning" and item.get("text") == "shell_tool_loop_max_rounds_reached" for item in payloads)
    assert any(item.get("type") == "warning" and item.get("text") == "shell_budget_force_dispatch_to_core" for item in payloads)
    route_events = [item for item in payloads if item.get("type") == "route_decision"]
    assert any(item.get("handoff_source") == "shell_budget_fallback" for item in route_events)
    assert len(pipeline_calls) == 1
    assert str(pipeline_calls[0].get("forced_route_semantic") or "") == "core_execution"
    state_payload = api_server._build_chat_route_session_state_payload("dispatch-budget-fallback-config-session", limit=5)

    api_server.message_manager.delete_session("dispatch-budget-fallback-config-session")
    api_server.message_manager.delete_session(state_payload["run_context_id"])


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
        "route_semantic": "shell_readonly",
        "risk_level": "read_only",
        "router_decision": {
            "task_type": "research",
            "prompt_profile": "shell_readonly_research",
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
    assert "Route policy: Shell Read-Only" in prompt
    assert "## 相关记忆" in prompt
    assert route_meta.get("_slice_selected_count", 0) >= 2
    assert "shell_base" in route_meta.get("_slice_selected", [])
    assert str(route_meta.get("_slice_prefix_hash") or "").strip()


def test_build_shell_system_prompt_with_gateway_falls_back_when_gateway_missing(monkeypatch) -> None:
    route_meta = {
        "route_semantic": "shell_clarify",
        "risk_level": "unknown",
        "router_decision": {
            "task_type": "general",
            "prompt_profile": "shell_general",
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
    assert "Route policy: Shell Clarify" in prompt
    assert "## 相关记忆" in prompt


def test_build_chat_route_prompt_hints_includes_core_async_status_digest() -> None:
    route_meta = {
        "route_semantic": "shell_readonly",
        "risk_level": "read_only",
        "_core_async_status_digest": "## Core 任务观测状态\n- running corejob_123: indexing repository",
        "router_decision": {
            "task_type": "research",
            "prompt_profile": "shell_readonly_research",
            "injection_mode": "minimal",
            "delegation_intent": "read_only_exploration",
        },
    }

    hints = api_server._build_chat_route_prompt_hints(route_meta)

    assert "PromptRouteDecision" in hints
    assert "Core 后台执行面" in hints
    assert "corejob_123" in hints
    assert "indexing repository" in hints


def test_shell_core_session_state_preserves_last_core_session_on_readonly_turn() -> None:
    shell_session_id = api_server.message_manager.create_session(temporary=True)
    try:
        core_route = {
            "route_semantic": "core_execution",
            "shell_readonly_hit": False,
            "core_execution_hit": True,
            "router_decision": {"delegation_intent": "core_execution"},
        }
        core_route = api_server._apply_shell_core_session_state(core_route, shell_session_id=shell_session_id)
        api_server._register_core_job_submission(
            shell_session_id,
            core_runtime_id="core-main",
            core_job_id="corejob_002",
            core_execution_session_id=f"{shell_session_id}__core",
            route_meta=core_route,
        )

        readonly_route = {
            "route_semantic": "shell_readonly",
            "shell_readonly_hit": True,
            "core_execution_hit": False,
            "router_decision": {"delegation_intent": "read_only_exploration"},
        }
        api_server._apply_shell_core_session_state(readonly_route, shell_session_id=shell_session_id)

        session = api_server.message_manager.get_session(shell_session_id)
        assert isinstance(session, dict)
        state = session[api_server._CHAT_ROUTE_STATE_KEY]
        assert state["last_run_context_id"] == f"{shell_session_id}__core"
        assert state["last_route_semantic"] == "shell_readonly"
        assert state["last_dispatch_to_core"] is False
    finally:
        api_server.message_manager.delete_session(shell_session_id)


def test_core_job_manager_reuses_stable_shell_core_session_and_serializes_jobs() -> None:
    async def _run() -> None:
        manager = api_server.CoreDispatchJobManager()
        store = api_server.AgentSessionStore(db_path=":memory:")
        mailbox = AgentMailbox(db_path=":memory:")
        started = []

        async def _fake_pipeline_runner(**kwargs):
            started.append(
                {
                    "goal": str(kwargs.get("message") or ""),
                    "core_execution_session_id": str(kwargs.get("core_execution_session_id") or ""),
                }
            )
            await asyncio.sleep(0.05)
            yield {
                "type": "execution_receipt",
                "pipeline_id": f"pipe-{len(started)}",
                "agent_state": {"task_completed": True, "final_answer": str(kwargs.get("message") or "")},
            }
            yield {
                "type": "pipeline_end",
                "pipeline_id": f"pipe-{len(started)}",
                "reason": "completed",
            }

        first = manager.submit_job(
            shell_session_id="shell-serial",
            goal="first task",
            risk_level="write_repo",
            handoff_source="dispatch_to_core",
            route_decision={},
            dispatch_payload={},
            core_runtime_id="core-main",
            store=store,
            message_manager=api_server.message_manager,
            mailbox=mailbox,
            pipeline_runner=_fake_pipeline_runner,
            heartbeat_interval_seconds=1.0,
        )
        second = manager.submit_job(
            shell_session_id="shell-serial",
            goal="second task",
            risk_level="write_repo",
            handoff_source="dispatch_to_core",
            route_decision={},
            dispatch_payload={},
            core_runtime_id="core-main",
            store=store,
            message_manager=api_server.message_manager,
            mailbox=mailbox,
            pipeline_runner=_fake_pipeline_runner,
            heartbeat_interval_seconds=1.0,
        )

        assert first["run_context_id"] == "shell-serial__core"
        assert second["run_context_id"] == "shell-serial__core"
        assert first["run_context_created"] is True
        assert second["run_context_created"] is False
        assert first["job_id"] != second["job_id"]
        assert first["queue_position"] == 1
        assert first["queue_depth"] == 0
        assert first["pipeline_depth"] == 1
        assert first["worker_status"] == "running"
        assert second["queue_position"] == 2
        assert second["queue_depth"] == 1
        assert second["pipeline_depth"] == 2
        assert second["worker_status"] == "running"
        assert first["handoff_message_seq"] > 0
        assert second["handoff_message_seq"] > first["handoff_message_seq"]

        handoff_rows = mailbox.read("shell-serial__core", message_type="query")
        assert [row.metadata.get("core_job_id") for row in handoff_rows] == [first["job_id"], second["job_id"]]
        assert [row.content for row in handoff_rows] == ["first task", "second task"]
        mailbox.send(
            "shell-serial",
            "shell-serial__core",
            "second task duplicate",
            message_type="query",
            metadata={"core_job_id": second["job_id"]},
        )
        duplicate_snapshot = manager.get_shell_snapshot("shell-serial", limit=10)
        assert duplicate_snapshot["queued_job_ids"] == [second["job_id"]]
        assert duplicate_snapshot["inbox_dedup_skipped_count"] == 1
        assert duplicate_snapshot["last_dedup_message_seq"] > second["handoff_message_seq"]

        await asyncio.sleep(0.02)
        first_snapshot = manager.get_job_snapshot(first["job_id"])
        second_snapshot = manager.get_job_snapshot(second["job_id"])
        assert first_snapshot["status"] == "running"
        assert second_snapshot["status"] == "accepted"
        assert first_snapshot["current_job_id"] == first["job_id"]
        assert first_snapshot["queued_job_ids"] == [second["job_id"]]
        assert first_snapshot["queue_position"] == 1
        assert second_snapshot["queue_position"] == 2
        assert first_snapshot["mailbox_cursor_seq"] == duplicate_snapshot["last_dedup_message_seq"]
        assert second_snapshot["handoff_duplicate_count"] == 1

        await asyncio.sleep(0.14)
        first_snapshot = manager.get_job_snapshot(first["job_id"])
        second_snapshot = manager.get_job_snapshot(second["job_id"])
        assert first_snapshot["status"] == "completed"
        assert second_snapshot["status"] == "completed"
        assert first_snapshot["completion_message_seq"] > 0
        assert second_snapshot["completion_message_seq"] > first_snapshot["completion_message_seq"]
        receipt_dispatch = (
            second_snapshot.get("last_execution_receipt", {}).get("agent_state", {}).get("core_dispatch", {})
            if isinstance(second_snapshot.get("last_execution_receipt"), dict)
            else {}
        )
        assert receipt_dispatch["handoff_duplicate_count"] == 1
        assert receipt_dispatch["shell_inbox_dedup_skipped_count"] == 1
        assert [item["goal"] for item in started] == ["first task", "second task"]
        assert all(item["core_execution_session_id"] == "shell-serial__core" for item in started)

        report_rows = mailbox.read("shell-serial", message_type="report")
        assert [row.metadata.get("core_job_id") for row in report_rows] == [first["job_id"], second["job_id"]]
        assert all(str(row.from_id) == "shell-serial__core" for row in report_rows)
        assert all(str(row.content).startswith("[CORE COMPLETED]") for row in report_rows)

        shell_snapshot = manager.get_shell_snapshot("shell-serial", limit=10)
        assert shell_snapshot["core_runtime_id"] == "core-main"
        assert shell_snapshot["latest_job"]["core_execution_session_id"] == "shell-serial__core"
        assert shell_snapshot["worker_status"] == "idle"
        assert shell_snapshot["current_job_id"] == ""
        assert shell_snapshot["queued_job_ids"] == []
        assert shell_snapshot["queue_depth"] == 0
        assert shell_snapshot["pipeline_depth"] == 0
        assert shell_snapshot["mailbox_cursor_seq"] == duplicate_snapshot["last_dedup_message_seq"]
        assert shell_snapshot["latest_handoff_message_seq"] == second["handoff_message_seq"]
        assert shell_snapshot["latest_completion_message_seq"] == second_snapshot["completion_message_seq"]
        assert shell_snapshot["inbox_dedup_skipped_count"] == 1

        await manager.shutdown()
        mailbox.close()
        api_server.message_manager.delete_session("shell-serial")
        api_server.message_manager.delete_session("shell-serial__core")
        store.close()

    asyncio.run(_run())


def test_core_job_manager_recovers_pending_jobs_from_persisted_recovery_state() -> None:
    async def _run() -> None:
        manager = api_server.CoreDispatchJobManager()
        store = api_server.AgentSessionStore(db_path=":memory:")
        mailbox = AgentMailbox(db_path=":memory:")
        started: list[str] = []
        shell_session_id = "shell-recover"
        core_execution_session_id = f"{shell_session_id}__core"

        store.create(role="core", session_id="core-main")
        store.create(
            role="core",
            parent_id="core-main",
            session_id=core_execution_session_id,
            metadata={
                "core_job_recovery_state": {
                    "shell_session_id": shell_session_id,
                    "core_runtime_id": "core-main",
                    "mailbox_cursor_seq": 0,
                    "pending_job_ids": ["corejob_recover_1", "corejob_recover_2"],
                    "jobs": {
                        "corejob_recover_1": {
                            "job_id": "corejob_recover_1",
                            "shell_session_id": shell_session_id,
                            "core_runtime_id": "core-main",
                            "core_execution_session_id": core_execution_session_id,
                            "goal": "recover first",
                            "risk_level": "write_repo",
                            "handoff_source": "dispatch_to_core",
                            "route_summary": {},
                            "route_decision": {},
                            "dispatch_payload": {},
                            "status": "accepted",
                            "enable_child_execution": False,
                            "child_session_cleanup_mode": "retain",
                            "child_session_cleanup_ttl_seconds": 0,
                        },
                        "corejob_recover_2": {
                            "job_id": "corejob_recover_2",
                            "shell_session_id": shell_session_id,
                            "core_runtime_id": "core-main",
                            "core_execution_session_id": core_execution_session_id,
                            "goal": "recover second",
                            "risk_level": "write_repo",
                            "handoff_source": "dispatch_to_core",
                            "route_summary": {},
                            "route_decision": {},
                            "dispatch_payload": {},
                            "status": "accepted",
                            "enable_child_execution": False,
                            "child_session_cleanup_mode": "retain",
                            "child_session_cleanup_ttl_seconds": 0,
                        },
                    },
                    "recent_terminal_jobs": [],
                }
            },
        )
        mailbox.send(
            shell_session_id,
            core_execution_session_id,
            "recover first",
            message_type="query",
            metadata={"core_job_id": "corejob_recover_1"},
        )
        mailbox.send(
            shell_session_id,
            core_execution_session_id,
            "recover second",
            message_type="query",
            metadata={"core_job_id": "corejob_recover_2"},
        )

        async def _fake_pipeline_runner(**kwargs):
            started.append(str(kwargs.get("message") or ""))
            await asyncio.sleep(0.03)
            yield {
                "type": "execution_receipt",
                "pipeline_id": f"pipe-{len(started)}",
                "agent_state": {
                    "task_completed": True,
                    "final_answer": str(kwargs.get("message") or ""),
                },
            }
            yield {
                "type": "pipeline_end",
                "pipeline_id": f"pipe-{len(started)}",
                "reason": "completed",
            }

        manager.configure_runtime_defaults(
            store=store,
            mailbox=mailbox,
            runner=_fake_pipeline_runner,
            enable_child_execution=False,
            child_session_cleanup_mode="retain",
            child_session_cleanup_ttl_seconds=0,
            heartbeat_interval_seconds=1.0,
        )

        initial_snapshot = manager.get_shell_snapshot(shell_session_id, limit=10)
        assert initial_snapshot["core_runtime_id"] == "core-main"
        assert initial_snapshot["pipeline_depth"] == 2
        assert initial_snapshot["mailbox_cursor_seq"] == 2
        assert initial_snapshot["recovery_restart_total"] == 2

        await asyncio.sleep(0.01)
        first_snapshot = manager.get_job_snapshot("corejob_recover_1")
        second_snapshot = manager.get_job_snapshot("corejob_recover_2")
        assert first_snapshot["status"] == "running"
        assert second_snapshot["status"] == "accepted"
        assert first_snapshot["current_job_id"] == "corejob_recover_1"
        assert first_snapshot["queued_job_ids"] == ["corejob_recover_2"]
        assert first_snapshot["recovery_restart_count"] == 1
        assert second_snapshot["recovery_restart_count"] == 1

        await asyncio.sleep(0.10)
        final_snapshot = manager.get_shell_snapshot(shell_session_id, limit=10)
        assert final_snapshot["worker_status"] == "idle"
        assert final_snapshot["queue_depth"] == 0
        assert final_snapshot["recovery_restart_total"] == 2
        assert [item for item in started] == ["recover first", "recover second"]
        recent_ids = {str(item.get("job_id") or "") for item in final_snapshot.get("jobs") or []}
        assert {"corejob_recover_1", "corejob_recover_2"}.issubset(recent_ids)

        reports = mailbox.read(shell_session_id, message_type="report")
        assert [row.metadata.get("core_job_id") for row in reports] == ["corejob_recover_1", "corejob_recover_2"]

        recovered_session = store.get(core_execution_session_id)
        assert recovered_session is not None
        recovery_state = dict(recovered_session.metadata.get("core_job_recovery_state") or {})
        assert recovery_state["pending_job_ids"] == []
        assert recovery_state["recovery_restart_total"] == 2
        archived_ids = {str(item.get("job_id") or "") for item in recovery_state.get("recent_terminal_jobs") or []}
        assert {"corejob_recover_1", "corejob_recover_2"} == archived_ids

        await manager.shutdown()
        mailbox.close()
        store.close()

    asyncio.run(_run())


def test_core_job_manager_runtime_monitor_recovers_pending_jobs_without_snapshot_calls() -> None:
    async def _run() -> None:
        manager = api_server.CoreDispatchJobManager()
        store = api_server.AgentSessionStore(db_path=":memory:")
        mailbox = AgentMailbox(db_path=":memory:")
        started: list[str] = []
        shell_session_id = "shell-recover-background"
        core_execution_session_id = f"{shell_session_id}__core"

        store.create(role="core", session_id="core-main", metadata={"agent_type": "core_runtime"})
        store.create(
            role="core",
            parent_id="core-main",
            session_id=core_execution_session_id,
            metadata={
                "session_kind": "shell_core_root",
                "shell_session_id": shell_session_id,
                "core_runtime_id": "core-main",
                "core_job_recovery_state": {
                    "shell_session_id": shell_session_id,
                    "core_runtime_id": "core-main",
                    "mailbox_cursor_seq": 0,
                    "pending_job_ids": ["corejob_background_1", "corejob_background_2"],
                    "jobs": {
                        "corejob_background_1": {
                            "job_id": "corejob_background_1",
                            "shell_session_id": shell_session_id,
                            "core_runtime_id": "core-main",
                            "core_execution_session_id": core_execution_session_id,
                            "goal": "background recover first",
                            "risk_level": "write_repo",
                            "handoff_source": "dispatch_to_core",
                            "route_summary": {},
                            "route_decision": {},
                            "dispatch_payload": {},
                            "status": "accepted",
                            "enable_child_execution": False,
                            "child_max_rounds": 12,
                            "child_session_cleanup_mode": "retain",
                            "child_session_cleanup_ttl_seconds": 0,
                        },
                        "corejob_background_2": {
                            "job_id": "corejob_background_2",
                            "shell_session_id": shell_session_id,
                            "core_runtime_id": "core-main",
                            "core_execution_session_id": core_execution_session_id,
                            "goal": "background recover second",
                            "risk_level": "write_repo",
                            "handoff_source": "dispatch_to_core",
                            "route_summary": {},
                            "route_decision": {},
                            "dispatch_payload": {},
                            "status": "accepted",
                            "enable_child_execution": False,
                            "child_max_rounds": 12,
                            "child_session_cleanup_mode": "retain",
                            "child_session_cleanup_ttl_seconds": 0,
                        },
                    },
                    "recent_terminal_jobs": [],
                },
            },
        )
        mailbox.send(
            shell_session_id,
            core_execution_session_id,
            "background recover first",
            message_type="query",
            metadata={"core_job_id": "corejob_background_1"},
        )
        mailbox.send(
            shell_session_id,
            core_execution_session_id,
            "background recover second",
            message_type="query",
            metadata={"core_job_id": "corejob_background_2"},
        )

        async def _fake_pipeline_runner(**kwargs):
            started.append(str(kwargs.get("message") or ""))
            await asyncio.sleep(0.03)
            yield {
                "type": "execution_receipt",
                "pipeline_id": f"pipe-{len(started)}",
                "agent_state": {
                    "task_completed": True,
                    "final_answer": str(kwargs.get("message") or ""),
                },
            }
            yield {
                "type": "pipeline_end",
                "pipeline_id": f"pipe-{len(started)}",
                "reason": "completed",
            }

        manager.configure_runtime_defaults(
            store=store,
            mailbox=mailbox,
            runner=_fake_pipeline_runner,
            enable_child_execution=False,
            child_session_cleanup_mode="retain",
            child_session_cleanup_ttl_seconds=0,
            heartbeat_interval_seconds=1.0,
        )

        await asyncio.sleep(0.35)

        assert started == ["background recover first", "background recover second"]
        reports = mailbox.read(shell_session_id, message_type="report")
        assert [row.metadata.get("core_job_id") for row in reports] == [
            "corejob_background_1",
            "corejob_background_2",
        ]

        await manager.shutdown()
        mailbox.close()
        store.close()

    asyncio.run(_run())


def test_core_job_manager_runtime_monitor_reconciles_recovered_waiting_descendants_without_poll() -> None:
    async def _run() -> None:
        manager = api_server.CoreDispatchJobManager()
        store = api_server.AgentSessionStore(db_path=":memory:")
        mailbox = AgentMailbox(db_path=":memory:")
        shell_session_id = "shell-recover-waiting-background"
        core_execution_session_id = f"{shell_session_id}__core"
        job_id = "corejob_waiting_background_1"

        store.create(role="core", session_id="core-main", metadata={"agent_type": "core_runtime"})
        store.create(
            role="core",
            parent_id="core-main",
            session_id=core_execution_session_id,
            metadata={
                "session_kind": "shell_core_root",
                "shell_session_id": shell_session_id,
                "core_runtime_id": "core-main",
                "core_job_recovery_state": {
                    "shell_session_id": shell_session_id,
                    "core_runtime_id": "core-main",
                    "mailbox_cursor_seq": 0,
                    "pending_job_ids": [job_id],
                    "jobs": {
                        job_id: {
                            "job_id": job_id,
                            "shell_session_id": shell_session_id,
                            "core_runtime_id": "core-main",
                            "core_execution_session_id": core_execution_session_id,
                            "goal": "waiting recovery should reconcile in background",
                            "risk_level": "write_repo",
                            "handoff_source": "dispatch_to_core",
                            "route_summary": {},
                            "route_decision": {},
                            "dispatch_payload": {},
                            "status": "waiting_descendants",
                            "pipeline_id": "pipe-waiting-background",
                            "last_execution_receipt": {
                                "type": "execution_receipt",
                                "pipeline_id": "pipe-waiting-background",
                                "agent_state": {
                                    "task_completed": False,
                                    "final_answer": "waiting on background report",
                                },
                            },
                            "enable_child_execution": False,
                            "child_max_rounds": 12,
                            "child_session_cleanup_mode": "retain",
                            "child_session_cleanup_ttl_seconds": 0,
                        }
                    },
                    "recent_terminal_jobs": [],
                },
            },
        )
        store.create(
            role="expert",
            parent_id=core_execution_session_id,
            session_id="expert_waiting_background_1",
            metadata={"pipeline_id": "pipe-waiting-background"},
        )
        store.update_status("expert_waiting_background_1", AgentStatus.WAITING)

        async def _fake_pipeline_runner(**kwargs):
            del kwargs
            if False:
                yield {}

        manager.configure_runtime_defaults(
            store=store,
            mailbox=mailbox,
            runner=_fake_pipeline_runner,
            enable_child_execution=False,
            heartbeat_interval_seconds=1.0,
        )

        await asyncio.sleep(0.15)
        mailbox.send(
            "expert_waiting_background_1",
            core_execution_session_id,
            "[COMPLETED] background descendant finished",
            message_type="report",
        )

        await asyncio.sleep(1.25)

        reports = mailbox.read(shell_session_id, message_type="report")
        assert len(reports) == 1
        assert reports[0].metadata.get("core_job_id") == job_id
        assert str(reports[0].content or "").startswith("[CORE COMPLETED]")

        await manager.shutdown()
        mailbox.close()
        store.close()

    asyncio.run(_run())


def test_core_job_manager_keeps_waiting_descendant_jobs_active() -> None:
    async def _run() -> None:
        manager = api_server.CoreDispatchJobManager()
        store = api_server.AgentSessionStore(db_path=":memory:")
        mailbox = AgentMailbox(db_path=":memory:")
        shell_session_id = "shell-waiting-desc"

        async def _fake_pipeline_runner(**kwargs):
            pipeline_id = "pipe-waiting-desc"
            core_execution_session_id = str(kwargs.get("core_execution_session_id") or "")
            if store.get("expert_waiting_desc_1") is None:
                store.create(
                    role="expert",
                    parent_id=core_execution_session_id,
                    session_id="expert_waiting_desc_1",
                    metadata={"pipeline_id": pipeline_id},
                )
            await asyncio.sleep(0.03)
            yield {
                "type": "execution_receipt",
                "pipeline_id": pipeline_id,
                "agent_state": {
                    "task_completed": False,
                    "final_answer": "waiting on outstanding descendants",
                },
            }
            yield {
                "type": "pipeline_end",
                "pipeline_id": pipeline_id,
                "reason": "delegated_waiting_child_completion",
            }

        submitted = manager.submit_job(
            shell_session_id=shell_session_id,
            goal="continue orchestrating until descendants settle",
            risk_level="write_repo",
            handoff_source="dispatch_to_core",
            route_decision={},
            dispatch_payload={},
            core_runtime_id="core-main",
            store=store,
            message_manager=api_server.message_manager,
            mailbox=mailbox,
            pipeline_runner=_fake_pipeline_runner,
            heartbeat_interval_seconds=1.0,
        )
        waiting_job_id = str(submitted.get("job_id") or "")

        await asyncio.sleep(0.12)

        job_snapshot = manager.get_job_snapshot(waiting_job_id)
        assert job_snapshot["status"] == "waiting_descendants"
        assert job_snapshot["pending_descendant_count"] == 1
        assert job_snapshot["pending_descendant_ids"] == ["expert_waiting_desc_1"]
        assert str(job_snapshot.get("pipeline_end_reason") or "") == "delegated_waiting_child_completion"

        shell_snapshot = manager.get_shell_snapshot(shell_session_id, limit=10)
        assert shell_snapshot["active_job_id"] == waiting_job_id
        assert shell_snapshot["active_job"]["status"] == "waiting_descendants"
        assert shell_snapshot["worker_status"] == "idle"
        assert shell_snapshot["queue_depth"] == 0
        assert shell_snapshot["pipeline_depth"] == 1

        core_session = store.get(f"{shell_session_id}__core")
        assert core_session is not None
        assert str(core_session.status.value) == "waiting"

        recovery_state = dict(core_session.metadata.get("core_job_recovery_state") or {})
        assert recovery_state["pending_job_ids"] == [waiting_job_id]
        assert str(((recovery_state.get("jobs") or {}).get(waiting_job_id) or {}).get("status") or "") == "waiting_descendants"

        report_rows = mailbox.read(shell_session_id, message_type="report")
        assert report_rows == []

        await manager.shutdown()
        mailbox.close()
        store.close()

    asyncio.run(_run())


def test_core_job_manager_emits_shell_status_updates_for_running_and_waiting_descendants() -> None:
    async def _run() -> None:
        manager = api_server.CoreDispatchJobManager()
        store = api_server.AgentSessionStore(db_path=":memory:")
        mailbox = AgentMailbox(db_path=":memory:")
        shell_session_id = "shell-status-outbox"

        async def _fake_pipeline_runner(**kwargs):
            pipeline_id = "pipe-status-outbox"
            core_execution_session_id = str(kwargs.get("core_execution_session_id") or "")
            if store.get("expert_status_outbox_1") is None:
                store.create(
                    role="expert",
                    parent_id=core_execution_session_id,
                    session_id="expert_status_outbox_1",
                    metadata={"pipeline_id": pipeline_id},
                )
                store.update_status("expert_status_outbox_1", AgentStatus.WAITING)
            await asyncio.sleep(0.03)
            yield {
                "type": "execution_receipt",
                "pipeline_id": pipeline_id,
                "agent_state": {
                    "task_completed": False,
                    "final_answer": "waiting on child result",
                },
            }
            yield {
                "type": "pipeline_end",
                "pipeline_id": pipeline_id,
                "reason": "delegated_waiting_child_completion",
            }

        submitted = manager.submit_job(
            shell_session_id=shell_session_id,
            goal="emit shell status updates",
            risk_level="write_repo",
            handoff_source="dispatch_to_core",
            route_decision={},
            dispatch_payload={},
            core_runtime_id="core-main",
            store=store,
            message_manager=api_server.message_manager,
            mailbox=mailbox,
            pipeline_runner=_fake_pipeline_runner,
            heartbeat_interval_seconds=1.0,
        )
        job_id = str(submitted.get("job_id") or "")

        await asyncio.sleep(0.12)

        status_rows = mailbox.read(shell_session_id, since_seq=0, limit=10, message_type="status")
        status_payloads = [row.metadata or {} for row in status_rows]
        statuses = [str(item.get("status") or "") for item in status_payloads]
        assert "running" in statuses
        assert "waiting_descendants" in statuses
        assert all(str(item.get("core_job_id") or "") == job_id for item in status_payloads)

        await manager.shutdown()
        mailbox.close()
        store.close()

    asyncio.run(_run())


def test_core_job_manager_auto_reconciles_waiting_descendants_after_reports_arrive() -> None:
    async def _run() -> None:
        manager = api_server.CoreDispatchJobManager()
        store = api_server.AgentSessionStore(db_path=":memory:")
        mailbox = AgentMailbox(db_path=":memory:")
        shell_session_id = "shell-waiting-reconcile"

        async def _fake_pipeline_runner(**kwargs):
            pipeline_id = "pipe-waiting-reconcile"
            core_execution_session_id = str(kwargs.get("core_execution_session_id") or "")
            if store.get("expert_waiting_reconcile_1") is None:
                store.create(
                    role="expert",
                    parent_id=core_execution_session_id,
                    session_id="expert_waiting_reconcile_1",
                    metadata={"pipeline_id": pipeline_id},
                )
                store.update_status("expert_waiting_reconcile_1", AgentStatus.WAITING)
            await asyncio.sleep(0.03)
            yield {
                "type": "execution_receipt",
                "pipeline_id": pipeline_id,
                "agent_state": {
                    "task_completed": False,
                    "final_answer": "waiting on expert report",
                },
            }
            yield {
                "type": "pipeline_end",
                "pipeline_id": pipeline_id,
                "reason": "delegated_waiting_child_completion",
            }

        submitted = manager.submit_job(
            shell_session_id=shell_session_id,
            goal="wait for deferred expert report then finalize",
            risk_level="write_repo",
            handoff_source="dispatch_to_core",
            route_decision={},
            dispatch_payload={},
            core_runtime_id="core-main",
            store=store,
            message_manager=api_server.message_manager,
            mailbox=mailbox,
            pipeline_runner=_fake_pipeline_runner,
            heartbeat_interval_seconds=1.0,
        )
        job_id = str(submitted.get("job_id") or "")
        core_execution_session_id = str(submitted.get("core_execution_session_id") or "")

        await asyncio.sleep(0.12)
        waiting_snapshot = manager.get_job_snapshot(job_id)
        assert waiting_snapshot["status"] == "waiting_descendants"
        assert waiting_snapshot["pending_descendant_ids"] == ["expert_waiting_reconcile_1"]

        mailbox.send(
            "expert_waiting_reconcile_1",
            core_execution_session_id,
            "[COMPLETED] deferred expert work finished",
            message_type="report",
        )

        await asyncio.sleep(1.2)

        final_snapshot = manager.get_job_snapshot(job_id)
        assert final_snapshot["status"] == "completed"
        assert final_snapshot["pending_descendant_count"] == 0
        last_receipt = dict(final_snapshot.get("last_execution_receipt") or {})
        assert str(last_receipt.get("stop_reason") or "") == "submitted_completion"
        assert bool(((last_receipt.get("agent_state") or {}).get("task_completed")))

        shell_snapshot = manager.get_shell_snapshot(shell_session_id, limit=10)
        assert shell_snapshot["active_job_id"] == ""
        assert shell_snapshot["latest_job"]["job_id"] == job_id
        assert shell_snapshot["latest_job"]["status"] == "completed"

        report_rows = mailbox.read(shell_session_id, message_type="report")
        assert len(report_rows) == 1
        assert report_rows[0].metadata.get("core_job_id") == job_id
        assert str(report_rows[0].content or "").startswith("[CORE COMPLETED]")

        core_session = store.get(core_execution_session_id)
        assert core_session is not None
        recovery_state = dict(core_session.metadata.get("core_job_recovery_state") or {})
        assert recovery_state["pending_job_ids"] == []

        await manager.shutdown()
        mailbox.close()
        store.close()

    asyncio.run(_run())


def test_core_job_manager_heartbeat_advances_waiting_review_descendants() -> None:
    async def _run() -> None:
        manager = api_server.CoreDispatchJobManager()
        store = api_server.AgentSessionStore(db_path=":memory:")
        mailbox = AgentMailbox(db_path=":memory:")
        shell_session_id = "shell-waiting-review-advance"

        async def _fake_pipeline_runner(**kwargs):
            pipeline_id = "pipe-waiting-review-advance"
            core_execution_session_id = str(kwargs.get("core_execution_session_id") or "")
            if store.get("expert_waiting_review_advance_1") is None:
                store.create(
                    role="expert",
                    parent_id=core_execution_session_id,
                    session_id="expert_waiting_review_advance_1",
                    metadata={"pipeline_id": pipeline_id, "board_id": ""},
                )
                store.update_status("expert_waiting_review_advance_1", AgentStatus.WAITING)
                store.create(
                    role="review",
                    parent_id="expert_waiting_review_advance_1",
                    session_id="review_waiting_review_advance_1",
                    task_description="Review the completed work and produce a structured review_result.",
                    metadata={
                        "pipeline_id": pipeline_id,
                        "review_cycle": 1,
                        "changed_files": ["agents/pipeline.py"],
                    },
                )
                store.update_status("review_waiting_review_advance_1", AgentStatus.WAITING)
            await asyncio.sleep(0.03)
            yield {
                "type": "execution_receipt",
                "pipeline_id": pipeline_id,
                "agent_state": {
                    "task_completed": False,
                    "final_answer": "waiting on deferred review execution",
                },
            }
            yield {
                "type": "pipeline_end",
                "pipeline_id": pipeline_id,
                "reason": "delegated_waiting_child_completion",
            }

        async def _fake_child_llm_call(messages, tools, model_name):
            del messages, model_name
            assert any(str(tool.get("name") or "") == "report_to_parent" for tool in tools)
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_review_complete",
                        "name": "report_to_parent",
                        "arguments": {
                            "type": "completed",
                            "content": "Independent review completed.",
                            "review_result": {
                                "verdict": "approve",
                                "requirement_alignment": [],
                                "code_quality": {"status": "passed", "summary": "No blocking issues found."},
                                "regression_risk": {"level": "low", "summary": "No new regression risk detected."},
                                "test_coverage": {"status": "passed", "summary": "Validation inputs look sufficient."},
                                "issues": [],
                                "suggestions": [],
                                "summary": "Review approved.",
                            },
                        },
                    }
                ],
            }

        async def _fake_child_tool_executor(tool_name, arguments, session_id):
            del tool_name, arguments, session_id
            return {"ok": True}

        submitted = manager.submit_job(
            shell_session_id=shell_session_id,
            goal="continue orchestrating until deferred review finishes",
            risk_level="write_repo",
            handoff_source="dispatch_to_core",
            route_decision={},
            dispatch_payload={},
            core_runtime_id="core-main",
            store=store,
            message_manager=api_server.message_manager,
            mailbox=mailbox,
            pipeline_runner=_fake_pipeline_runner,
            child_llm_call=_fake_child_llm_call,
            child_tool_executor=_fake_child_tool_executor,
            enable_child_execution=True,
            heartbeat_interval_seconds=1.0,
        )
        job_id = str(submitted.get("job_id") or "")

        await asyncio.sleep(0.12)

        waiting_snapshot = manager.get_job_snapshot(job_id)
        assert waiting_snapshot["status"] == "waiting_descendants"
        assert set(waiting_snapshot["pending_descendant_ids"]) == {
            "expert_waiting_review_advance_1",
            "review_waiting_review_advance_1",
        }

        await asyncio.sleep(1.25)

        final_snapshot = manager.get_job_snapshot(job_id)
        assert final_snapshot["status"] == "completed"
        assert final_snapshot["pending_descendant_count"] == 0
        last_receipt = dict(final_snapshot.get("last_execution_receipt") or {})
        assert str(last_receipt.get("stop_reason") or "") == "submitted_completion"
        assert bool(((last_receipt.get("agent_state") or {}).get("task_completed")))

        recent_event_types = [str(item.get("type") or "") for item in final_snapshot.get("recent_events") or []]
        assert "waiting_descendants_advance_start" in recent_event_types
        assert "review_waiting_descendant_start" in recent_event_types
        assert "review_waiting_descendant_end" in recent_event_types
        assert "expert_report_refresh" in recent_event_types
        assert "waiting_descendants_progress" in recent_event_types

        report_rows = mailbox.read(shell_session_id, message_type="report")
        assert len(report_rows) == 1
        assert report_rows[0].metadata.get("core_job_id") == job_id
        assert str(report_rows[0].content or "").startswith("[CORE COMPLETED]")

        await manager.shutdown()
        mailbox.close()
        store.close()

    asyncio.run(_run())


def test_core_job_manager_preserves_child_max_rounds_across_recovery(monkeypatch) -> None:
    async def _run() -> None:
        manager = api_server.CoreDispatchJobManager()
        store = api_server.AgentSessionStore(db_path=":memory:")
        mailbox = AgentMailbox(db_path=":memory:")
        shell_session_id = "shell-child-rounds-recovery"
        observed_runner_child_max_rounds: list[int] = []
        observed_recovery_child_max_rounds: list[int] = []

        async def _fake_pipeline_runner(**kwargs):
            observed_runner_child_max_rounds.append(int(kwargs.get("child_max_rounds") or 0))
            pipeline_id = "pipe-child-rounds-recovery"
            core_execution_session_id = str(kwargs.get("core_execution_session_id") or "")
            if store.get("expert_child_rounds_recovery_1") is None:
                store.create(
                    role="expert",
                    parent_id=core_execution_session_id,
                    session_id="expert_child_rounds_recovery_1",
                    metadata={"pipeline_id": pipeline_id},
                )
                store.update_status("expert_child_rounds_recovery_1", AgentStatus.WAITING)
            await asyncio.sleep(0.03)
            yield {
                "type": "execution_receipt",
                "pipeline_id": pipeline_id,
                "agent_state": {
                    "task_completed": False,
                    "final_answer": "waiting on expert with custom child rounds",
                },
            }
            yield {
                "type": "pipeline_end",
                "pipeline_id": pipeline_id,
                "reason": "delegated_waiting_child_completion",
            }

        submitted = manager.submit_job(
            shell_session_id=shell_session_id,
            goal="preserve child rounds across waiting recovery",
            risk_level="write_repo",
            handoff_source="dispatch_to_core",
            route_decision={},
            dispatch_payload={},
            core_runtime_id="core-main",
            store=store,
            message_manager=api_server.message_manager,
            mailbox=mailbox,
            pipeline_runner=_fake_pipeline_runner,
            enable_child_execution=True,
            child_max_rounds=37,
            heartbeat_interval_seconds=60.0,
        )
        job_id = str(submitted.get("job_id") or "")
        core_execution_session_id = str(submitted.get("core_execution_session_id") or "")

        await asyncio.sleep(0.12)

        waiting_snapshot = manager.get_job_snapshot(job_id)
        assert waiting_snapshot["status"] == "waiting_descendants"
        assert observed_runner_child_max_rounds == [37]

        core_session = store.get(core_execution_session_id)
        assert core_session is not None
        recovery_state = dict(core_session.metadata.get("core_job_recovery_state") or {})
        job_envelope = dict((recovery_state.get("jobs") or {}).get(job_id) or {})
        assert int(job_envelope.get("child_max_rounds") or 0) == 37

        await manager.shutdown()

        recovered_manager = api_server.CoreDispatchJobManager()
        recovered_manager.configure_runtime_defaults(
            store=store,
            mailbox=mailbox,
            runner=_fake_pipeline_runner,
            enable_child_execution=True,
            child_max_rounds=3,
            heartbeat_interval_seconds=60.0,
        )

        async def _fake_advance_waiting_descendants_once(**kwargs):
            observed_recovery_child_max_rounds.append(int(kwargs.get("child_max_rounds") or 0))
            return {"progress_made": False}

        monkeypatch.setattr(
            core_job_manager_module,
            "advance_core_waiting_descendants_once",
            _fake_advance_waiting_descendants_once,
        )

        recovered_snapshot = recovered_manager.get_shell_snapshot(shell_session_id, limit=10)
        assert recovered_snapshot["active_job_id"] == job_id
        assert recovered_snapshot["active_job"]["status"] == "waiting_descendants"

        progressed = await recovered_manager._try_advance_waiting_descendants(job_id)
        assert progressed is False
        assert observed_recovery_child_max_rounds == [37]

        await recovered_manager.shutdown()
        mailbox.close()
        store.close()

    asyncio.run(_run())


def test_core_job_manager_waiting_descendants_request_changes_runs_remediation_cycle() -> None:
    async def _run() -> None:
        tempdir = tempfile.TemporaryDirectory()
        manager = api_server.CoreDispatchJobManager()
        store = api_server.AgentSessionStore(db_path=":memory:")
        mailbox = AgentMailbox(db_path=":memory:")
        task_board = TaskBoardEngine(
            boards_dir=f"{tempdir.name}/boards",
            db_path=":memory:",
        )
        shell_session_id = "shell-waiting-review-request-changes"

        review_call_counts = {"cycle1": 0, "cycle2": 0}

        async def _fake_pipeline_runner(**kwargs):
            pipeline_id = "pipe-waiting-review-request-changes"
            core_execution_session_id = str(kwargs.get("core_execution_session_id") or "")
            if store.get("expert_waiting_review_request_changes_1") is None:
                board = task_board.create_board(
                    expert_type="backend",
                    tasks=[TaskItem(task_id="t-001", title="Implement remediation path", files=["agents/pipeline.py"])],
                )
                store.create(
                    role="expert",
                    parent_id=core_execution_session_id,
                    session_id="expert_waiting_review_request_changes_1",
                    task_description="Implement remediation path",
                    prompt_blocks=["agents/dev/dev_agent.md"],
                    tool_subset=["read_file", "grep", "patch"],
                    metadata={
                        "pipeline_id": pipeline_id,
                        "board_id": board.board_id,
                        "original_task": "Implement remediation path",
                    },
                )
                store.update_status("expert_waiting_review_request_changes_1", AgentStatus.WAITING)
                store.create(
                    role="dev",
                    parent_id="expert_waiting_review_request_changes_1",
                    session_id="dev_waiting_review_request_changes_1",
                    task_description="Task t-001: Implement remediation path",
                    prompt_blocks=["agents/dev/dev_agent.md"],
                    tool_subset=["read_file", "grep", "patch"],
                    metadata={
                        "pipeline_id": pipeline_id,
                        "completion_report": "Initial implementation complete.",
                        "verification_report": {
                            "tests": {"passed": 1, "failed": 0, "errors": 0, "attempts": 1, "summary": "initial pass"},
                            "lint": {"status": "passed", "errors": 0, "summary": "clean"},
                            "diff_review": {"complete": True, "summary": "initial diff reviewed", "missing_items": []},
                            "changed_files": ["agents/pipeline.py"],
                            "risks": [],
                        },
                        "changed_files": ["agents/pipeline.py"],
                    },
                )
                store.update_status("dev_waiting_review_request_changes_1", AgentStatus.WAITING)
                store.create(
                    role="review",
                    parent_id="expert_waiting_review_request_changes_1",
                    session_id="review_waiting_review_request_changes_1",
                    task_description="Review cycle 1 for TaskBoard: independently verify the completed work.",
                    prompt_blocks=["agents/review/code_reviewer.md"],
                    tool_subset=["memory_read", "memory_grep", "memory_tag", "memory_deprecate"],
                    metadata={
                        "pipeline_id": pipeline_id,
                        "review_cycle": 1,
                        "changed_files": ["agents/pipeline.py"],
                    },
                )
                store.update_status("review_waiting_review_request_changes_1", AgentStatus.WAITING)
            await asyncio.sleep(0.03)
            yield {
                "type": "execution_receipt",
                "pipeline_id": pipeline_id,
                "agent_state": {
                    "task_completed": False,
                    "final_answer": "waiting on review remediation flow",
                },
            }
            yield {
                "type": "pipeline_end",
                "pipeline_id": pipeline_id,
                "reason": "delegated_waiting_child_completion",
            }

        async def _fake_child_llm_call(messages, tools, model_name):
            del tools, model_name
            transcript = "\n".join(
                str(item.get("content") or "")
                for item in messages
                if isinstance(item, dict) and str(item.get("content") or "").strip()
            )
            if "Please address the reviewer feedback" in transcript or "Task t-001" in transcript:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_dev_complete",
                            "name": "report_to_parent",
                            "arguments": {
                                "type": "completed",
                                "content": "Applied requested remediation.",
                                "verification_report": {
                                    "tests": {"passed": 2, "failed": 0, "errors": 0, "attempts": 2, "summary": "remediation validated"},
                                    "lint": {"status": "passed", "errors": 0, "summary": "clean"},
                                    "diff_review": {"complete": True, "summary": "remediation diff reviewed", "missing_items": []},
                                    "changed_files": ["agents/pipeline.py"],
                                    "risks": [],
                                },
                            },
                        }
                    ],
                }
            if "Review cycle 1" in transcript:
                review_call_counts["cycle1"] += 1
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_review_cycle_1",
                            "name": "report_to_parent",
                            "arguments": {
                                "type": "completed",
                                "content": "Need one remediation pass.",
                                "review_result": {
                                    "verdict": "request_changes",
                                    "requirement_alignment": [],
                                    "code_quality": {"status": "needs_attention", "summary": "One remediation item remains."},
                                    "regression_risk": {"level": "medium", "summary": "Re-run validation after remediation."},
                                    "test_coverage": {"status": "needs_attention", "summary": "Re-check the updated path."},
                                    "issues": ["Please update the implementation and rerun self-verification."],
                                    "suggestions": ["Apply the minimal remediation and report completed again."],
                                    "summary": "Requesting one remediation pass.",
                                },
                            },
                        }
                    ],
                }
            if "Review cycle 2" in transcript:
                review_call_counts["cycle2"] += 1
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_review_cycle_2",
                            "name": "report_to_parent",
                            "arguments": {
                                "type": "completed",
                                "content": "Review approved.",
                                "review_result": {
                                    "verdict": "approve",
                                    "requirement_alignment": [],
                                    "code_quality": {"status": "passed", "summary": "No blocking issues remain."},
                                    "regression_risk": {"level": "low", "summary": "Risk is low after remediation."},
                                    "test_coverage": {"status": "passed", "summary": "Updated validation is sufficient."},
                                    "issues": [],
                                    "suggestions": [],
                                    "summary": "Review approved after remediation.",
                                },
                            },
                        }
                    ],
                }
            return {"content": "", "tool_calls": []}

        async def _fake_child_tool_executor(tool_name, arguments, session_id):
            del tool_name, arguments, session_id
            return {"ok": True}

        submitted = manager.submit_job(
            shell_session_id=shell_session_id,
            goal="continue orchestration through request_changes remediation",
            risk_level="write_repo",
            handoff_source="dispatch_to_core",
            route_decision={},
            dispatch_payload={},
            core_runtime_id="core-main",
            store=store,
            message_manager=api_server.message_manager,
            mailbox=mailbox,
            task_board_engine=task_board,
            pipeline_runner=_fake_pipeline_runner,
            child_llm_call=_fake_child_llm_call,
            child_tool_executor=_fake_child_tool_executor,
            enable_child_execution=True,
            heartbeat_interval_seconds=1.0,
        )
        job_id = str(submitted.get("job_id") or "")

        await asyncio.sleep(0.12)
        waiting_snapshot = manager.get_job_snapshot(job_id)
        assert waiting_snapshot["status"] == "waiting_descendants"
        assert set(waiting_snapshot["pending_descendant_ids"]) == {
            "expert_waiting_review_request_changes_1",
            "review_waiting_review_request_changes_1",
        }

        await asyncio.sleep(1.4)

        final_snapshot = manager.get_job_snapshot(job_id)
        assert final_snapshot["status"] == "completed"
        assert final_snapshot["pending_descendant_count"] == 0
        assert review_call_counts["cycle1"] >= 1
        assert review_call_counts["cycle2"] >= 1

        recent_event_types = [str(item.get("type") or "") for item in final_snapshot.get("recent_events") or []]
        assert "review_rework_requested" in recent_event_types
        assert "dev_review_resume_start" in recent_event_types
        assert "review_spawned" in recent_event_types

        await manager.shutdown()
        task_board.close()
        mailbox.close()
        store.close()
        tempdir.cleanup()

    asyncio.run(_run())


def test_core_job_manager_waiting_descendants_reject_respawns_new_dev() -> None:
    async def _run() -> None:
        tempdir = tempfile.TemporaryDirectory()
        manager = api_server.CoreDispatchJobManager()
        store = api_server.AgentSessionStore(db_path=":memory:")
        mailbox = AgentMailbox(db_path=":memory:")
        task_board = TaskBoardEngine(
            boards_dir=f"{tempdir.name}/boards",
            db_path=":memory:",
        )
        shell_session_id = "shell-waiting-review-reject-respawn"

        review_call_counts = {"cycle1": 0, "cycle2": 0}

        async def _fake_pipeline_runner(**kwargs):
            pipeline_id = "pipe-waiting-review-reject-respawn"
            core_execution_session_id = str(kwargs.get("core_execution_session_id") or "")
            if store.get("expert_waiting_review_reject_respawn_1") is None:
                board = task_board.create_board(
                    expert_type="backend",
                    tasks=[TaskItem(task_id="t-001", title="Implement reject remediation", files=["agents/pipeline.py"])],
                )
                store.create(
                    role="expert",
                    parent_id=core_execution_session_id,
                    session_id="expert_waiting_review_reject_respawn_1",
                    task_description="Implement reject remediation",
                    prompt_blocks=["agents/dev/dev_agent.md"],
                    tool_subset=["read_file", "grep", "patch"],
                    metadata={
                        "pipeline_id": pipeline_id,
                        "board_id": board.board_id,
                        "original_task": "Implement reject remediation",
                    },
                )
                store.update_status("expert_waiting_review_reject_respawn_1", AgentStatus.WAITING)
                store.create(
                    role="dev",
                    parent_id="expert_waiting_review_reject_respawn_1",
                    session_id="dev_waiting_review_reject_respawn_1",
                    task_description="Task t-001: Implement reject remediation",
                    prompt_blocks=["agents/dev/dev_agent.md"],
                    tool_subset=["read_file", "grep", "patch"],
                    metadata={
                        "pipeline_id": pipeline_id,
                        "completion_report": "Initial implementation complete.",
                        "verification_report": {
                            "tests": {"passed": 1, "failed": 0, "errors": 0, "attempts": 1, "summary": "initial pass"},
                            "lint": {"status": "passed", "errors": 0, "summary": "clean"},
                            "diff_review": {"complete": True, "summary": "initial diff reviewed", "missing_items": []},
                            "changed_files": ["agents/pipeline.py"],
                            "risks": [],
                        },
                        "changed_files": ["agents/pipeline.py"],
                    },
                )
                store.update_status("dev_waiting_review_reject_respawn_1", AgentStatus.WAITING)
                store.create(
                    role="review",
                    parent_id="expert_waiting_review_reject_respawn_1",
                    session_id="review_waiting_review_reject_respawn_1",
                    task_description="Review cycle 1 for TaskBoard: independently verify the completed work.",
                    prompt_blocks=["agents/review/code_reviewer.md"],
                    tool_subset=["memory_read", "memory_grep", "memory_tag", "memory_deprecate"],
                    metadata={
                        "pipeline_id": pipeline_id,
                        "review_cycle": 1,
                        "changed_files": ["agents/pipeline.py"],
                    },
                )
                store.update_status("review_waiting_review_reject_respawn_1", AgentStatus.WAITING)
            await asyncio.sleep(0.03)
            yield {
                "type": "execution_receipt",
                "pipeline_id": pipeline_id,
                "agent_state": {
                    "task_completed": False,
                    "final_answer": "waiting on reject remediation flow",
                },
            }
            yield {
                "type": "pipeline_end",
                "pipeline_id": pipeline_id,
                "reason": "delegated_waiting_child_completion",
            }

        async def _fake_child_llm_call(messages, tools, model_name):
            del tools, model_name
            transcript = "\n".join(
                str(item.get("content") or "")
                for item in messages
                if isinstance(item, dict) and str(item.get("content") or "").strip()
            )
            if "Task t-001" in transcript:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_dev_complete_respawn",
                            "name": "report_to_parent",
                            "arguments": {
                                "type": "completed",
                                "content": "Respawned dev completed the fix.",
                                "verification_report": {
                                    "tests": {"passed": 2, "failed": 0, "errors": 0, "attempts": 1, "summary": "respawn pass"},
                                    "lint": {"status": "passed", "errors": 0, "summary": "clean"},
                                    "diff_review": {"complete": True, "summary": "respawn diff reviewed", "missing_items": []},
                                    "changed_files": ["agents/pipeline.py"],
                                    "risks": [],
                                },
                            },
                        }
                    ],
                }
            if "Review cycle 1" in transcript:
                review_call_counts["cycle1"] += 1
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_review_cycle_1_reject",
                            "name": "report_to_parent",
                            "arguments": {
                                "type": "completed",
                                "content": "Rejecting current implementation.",
                                "review_result": {
                                    "verdict": "reject",
                                    "requirement_alignment": [],
                                    "code_quality": {"status": "failed", "summary": "Implementation needs a fresh remediation pass."},
                                    "regression_risk": {"level": "medium", "summary": "Retry with a new dev session."},
                                    "test_coverage": {"status": "failed", "summary": "Need a fresh validated pass."},
                                    "issues": ["Current implementation should be replaced with a fresh remediation pass."],
                                    "suggestions": ["Spawn a fresh dev session and complete the task again."],
                                    "summary": "Rejecting and requesting a fresh remediation pass.",
                                },
                            },
                        }
                    ],
                }
            if "Review cycle 2" in transcript:
                review_call_counts["cycle2"] += 1
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_review_cycle_2_approve",
                            "name": "report_to_parent",
                            "arguments": {
                                "type": "completed",
                                "content": "Respawn review approved.",
                                "review_result": {
                                    "verdict": "approve",
                                    "requirement_alignment": [],
                                    "code_quality": {"status": "passed", "summary": "Fresh remediation looks correct."},
                                    "regression_risk": {"level": "low", "summary": "Risk is low after the fresh remediation."},
                                    "test_coverage": {"status": "passed", "summary": "Validation coverage is now sufficient."},
                                    "issues": [],
                                    "suggestions": [],
                                    "summary": "Review approved after fresh remediation.",
                                },
                            },
                        }
                    ],
                }
            return {"content": "", "tool_calls": []}

        async def _fake_child_tool_executor(tool_name, arguments, session_id):
            del tool_name, arguments, session_id
            return {"ok": True}

        submitted = manager.submit_job(
            shell_session_id=shell_session_id,
            goal="continue orchestration through reject respawn flow",
            risk_level="write_repo",
            handoff_source="dispatch_to_core",
            route_decision={},
            dispatch_payload={},
            core_runtime_id="core-main",
            store=store,
            message_manager=api_server.message_manager,
            mailbox=mailbox,
            task_board_engine=task_board,
            pipeline_runner=_fake_pipeline_runner,
            child_llm_call=_fake_child_llm_call,
            child_tool_executor=_fake_child_tool_executor,
            enable_child_execution=True,
            heartbeat_interval_seconds=1.0,
        )
        job_id = str(submitted.get("job_id") or "")

        await asyncio.sleep(0.12)
        waiting_snapshot = manager.get_job_snapshot(job_id)
        assert waiting_snapshot["status"] == "waiting_descendants"
        assert set(waiting_snapshot["pending_descendant_ids"]) == {
            "expert_waiting_review_reject_respawn_1",
            "review_waiting_review_reject_respawn_1",
        }

        await asyncio.sleep(1.4)

        final_snapshot = manager.get_job_snapshot(job_id)
        assert final_snapshot["status"] == "completed"
        assert final_snapshot["pending_descendant_count"] == 0
        assert review_call_counts["cycle1"] >= 1
        assert review_call_counts["cycle2"] >= 1

        recent_event_types = [str(item.get("type") or "") for item in final_snapshot.get("recent_events") or []]
        assert "review_reject_respawn" in recent_event_types
        assert "dev_loop_start" in recent_event_types
        assert "review_spawned" in recent_event_types

        descendants = list(store.list_children("expert_waiting_review_reject_respawn_1") or [])
        dev_ids = {str(item.session_id or "") for item in descendants if str(item.role or "") == "dev"}
        assert len(dev_ids) >= 2

        await manager.shutdown()
        task_board.close()
        mailbox.close()
        store.close()
        tempdir.cleanup()

    asyncio.run(_run())


def test_chat_stream_reuses_stable_shell_core_session_across_multiple_dispatches(monkeypatch) -> None:
    core_session_id = "reuse-core-session-shell__core"
    agent_session_store = api_server._get_agent_session_store()
    existing_core_session = agent_session_store.get(core_session_id) if agent_session_store is not None else None
    if existing_core_session is not None:
        agent_session_store.destroy(core_session_id, reason="test_reset")

    class _FakeLLMService:
        def stream_chat_with_context(self, messages, temperature, model_override=None, tools=None, tool_choice="auto"):
            del messages, temperature, model_override, tools, tool_choice

            async def _gen():
                yield (
                    'data: {"type":"tool_calls","text":[{"id":"call_dispatch","name":"dispatch_to_core",'
                    '"arguments":{"goal":"排查核心链路","intent_type":"analysis","target_repo":"external"}}]}\n\n'
                )
                yield "data: [DONE]\n\n"

            return _gen()

    async def _fake_run_multi_agent_pipeline(**kwargs):
        await asyncio.sleep(0.05)
        yield {
            "type": "execution_receipt",
            "pipeline_id": f"pipe-{str(kwargs.get('message') or '')}",
            "agent_state": {
                "task_completed": True,
                "final_answer": str(kwargs.get("message") or ""),
            },
        }
        yield {
            "type": "pipeline_end",
            "pipeline_id": f"pipe-{str(kwargs.get('message') or '')}",
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

    async def _no_memory(_question: str, *, limit: int = 5):
        del limit
        return []

    monkeypatch.setattr(api_server, "get_llm_service", lambda: _FakeLLMService())
    monkeypatch.setattr(api_server, "run_multi_agent_pipeline", _fake_run_multi_agent_pipeline)
    monkeypatch.setattr(api_server, "_recall_memory_lines", _no_memory)
    monkeypatch.setattr(api_server, "_PIPELINE_STREAM_HEARTBEAT_INTERVAL_SECONDS", 1.0)
    monkeypatch.setattr(api_server, "_CORE_JOB_MANAGER", api_server.CoreDispatchJobManager())

    req1 = api_server.ChatRequest(
        message="第一次升级到 Core",
        stream=True,
        session_id="reuse-core-session-shell",
        stream_protocol="sse_json_v1",
        temporary=True,
    )
    req2 = api_server.ChatRequest(
        message="第二次升级到 Core",
        stream=True,
        session_id="reuse-core-session-shell",
        stream_protocol="sse_json_v1",
        temporary=True,
    )

    response1 = asyncio.run(api_server.chat_stream(req1))
    payloads1 = asyncio.run(_collect_payloads(response1))
    response2 = asyncio.run(api_server.chat_stream(req2))
    payloads2 = asyncio.run(_collect_payloads(response2))

    accepted1 = next(item for item in payloads1 if item.get("type") == "core_job_accepted")
    accepted2 = next(item for item in payloads2 if item.get("type") == "core_job_accepted")

    assert accepted1["run_context_id"] == core_session_id
    assert accepted2["run_context_id"] == core_session_id
    assert accepted1["run_context_created"] is True
    assert accepted1["core_job_id"] != accepted2["core_job_id"]

    state_payload = api_server._build_chat_route_session_state_payload("reuse-core-session-shell", limit=20)
    assert state_payload["run_context_id"] == core_session_id
    assert state_payload["last_run_context_id"] == core_session_id
    recent_job_ids = {str(item.get("job_id") or "") for item in state_payload.get("recent_core_jobs") or []}
    assert {accepted1["core_job_id"], accepted2["core_job_id"]}.issubset(recent_job_ids)

    api_server.message_manager.delete_session("reuse-core-session-shell")
    api_server.message_manager.delete_session(core_session_id)
    if agent_session_store is not None and agent_session_store.get(core_session_id) is not None:
        agent_session_store.destroy(core_session_id, reason="test_cleanup")
