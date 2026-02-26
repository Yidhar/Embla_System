from __future__ import annotations

import asyncio

import apiserver.api_server as api_server
from fastapi import HTTPException


def test_chat_route_bridge_payload_raises_404_when_session_missing() -> None:
    missing = "sess-not-found-ws28-011"
    try:
        api_server.message_manager.delete_session(missing)
    except Exception:
        pass

    try:
        api_server._build_chat_route_bridge_payload(missing)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("expected HTTPException 404")


def test_chat_route_bridge_payload_contains_state_and_recent_events(monkeypatch) -> None:
    outer_session_id = api_server.message_manager.create_session(temporary=True)
    core_session_id = f"{outer_session_id}__core"
    api_server.message_manager.create_session(session_id=core_session_id, temporary=True)
    try:
        session = api_server.message_manager.get_session(outer_session_id)
        assert isinstance(session, dict)
        session[api_server._CHAT_ROUTE_STATE_KEY] = {
            "core_session_id": core_session_id,
            "path_b_clarify_turns": 1,
            "last_execution_session_id": core_session_id,
            "last_core_escalation_at_ms": 1700000000000,
        }

        events = [
            {
                "timestamp": "2026-02-26T10:00:00+00:00",
                "event_type": "PromptInjectionComposed",
                "source": "apiserver.chat_stream",
                "payload": {
                    "session_id": outer_session_id,
                    "outer_session_id": outer_session_id,
                    "core_session_id": core_session_id,
                    "execution_session_id": core_session_id,
                    "path": "path-c",
                    "trigger": "path-c",
                    "prompt_profile": "core_exec_general",
                    "injection_mode": "normal",
                    "delegation_intent": "core_execution",
                    "path_b_budget_escalated": True,
                    "path_b_budget_reason": "clarify_budget_exceeded_auto_escalate_core",
                    "path_b_clarify_turns": 1,
                    "path_b_clarify_limit": 1,
                    "core_session_created": True,
                },
            },
            {
                "timestamp": "2026-02-26T10:01:00+00:00",
                "event_type": "PromptInjectionComposed",
                "source": "apiserver.chat_stream",
                "payload": {
                    "session_id": "another-session",
                    "outer_session_id": "another-session",
                    "core_session_id": "another-session__core",
                    "execution_session_id": "another-session__core",
                    "path": "path-a",
                },
            },
        ]
        monkeypatch.setattr(api_server, "_read_chat_route_event_rows", lambda limit=2000: events)

        payload = api_server._build_chat_route_bridge_payload(outer_session_id, limit=10)
        assert payload["status"] == "success"
        assert payload["outer_session_id"] == outer_session_id
        assert payload["core_session_id"] == core_session_id
        assert payload["execution_session_id"] == core_session_id
        assert payload["core_session_exists"] is True
        assert payload["state"]["path_b_clarify_turns"] == 1

        history = payload["recent_route_events"]
        assert len(history) == 1
        assert history[0]["path"] == "path-c"
        assert history[0]["path_b_budget_escalated"] is True
        assert history[0]["execution_session_id"] == core_session_id
    finally:
        api_server.message_manager.delete_session(outer_session_id)
        api_server.message_manager.delete_session(core_session_id)


def test_chat_route_bridge_v1_endpoint_alias_returns_same_snapshot(monkeypatch) -> None:
    outer_session_id = api_server.message_manager.create_session(temporary=True)
    core_session_id = f"{outer_session_id}__core"
    api_server.message_manager.create_session(session_id=core_session_id, temporary=True)
    try:
        session = api_server.message_manager.get_session(outer_session_id)
        assert isinstance(session, dict)
        session[api_server._CHAT_ROUTE_STATE_KEY] = {
            "core_session_id": core_session_id,
            "path_b_clarify_turns": 0,
            "last_execution_session_id": core_session_id,
            "last_core_escalation_at_ms": 1700000000500,
        }

        monkeypatch.setattr(api_server, "_read_chat_route_event_rows", lambda limit=2000: [])

        direct_payload = api_server._build_chat_route_bridge_payload(outer_session_id, limit=5)
        v1_payload = asyncio.run(api_server.get_chat_route_bridge_v1(session_id=outer_session_id, limit=5))
        legacy_payload = asyncio.run(api_server.get_chat_route_bridge(session_id=outer_session_id, limit=5))

        assert v1_payload["status"] == "success"
        assert legacy_payload["status"] == "success"
        assert v1_payload["outer_session_id"] == direct_payload["outer_session_id"] == outer_session_id
        assert v1_payload["core_session_id"] == direct_payload["core_session_id"] == core_session_id
        assert legacy_payload["execution_session_id"] == direct_payload["execution_session_id"] == core_session_id
    finally:
        api_server.message_manager.delete_session(outer_session_id)
        api_server.message_manager.delete_session(core_session_id)
