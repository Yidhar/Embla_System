from __future__ import annotations

import asyncio

import apiserver.api_server as api_server
from agents.runtime.agent_session import AgentSessionStore
from agents.runtime.mailbox import AgentMailbox
from fastapi import HTTPException


def test_chat_route_session_state_payload_raises_404_when_session_missing() -> None:
    missing = "sess-not-found-ws28-011"
    try:
        api_server.message_manager.delete_session(missing)
    except Exception:
        pass

    try:
        api_server._build_chat_route_session_state_payload(missing)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("expected HTTPException 404")


def test_chat_route_session_state_payload_contains_state_and_recent_events(monkeypatch) -> None:
    shell_session_id = api_server.message_manager.create_session(temporary=True)
    core_execution_session_id = f"{shell_session_id}__core"
    api_server.message_manager.create_session(session_id=core_execution_session_id, temporary=True)
    try:
        session = api_server.message_manager.get_session(shell_session_id)
        assert isinstance(session, dict)
        session[api_server._CHAT_ROUTE_STATE_KEY] = {
            "core_execution_session_id": core_execution_session_id,
            "shell_clarify_turns": 1,
            "last_core_execution_session_id": core_execution_session_id,
            "last_core_escalation_at_ms": 1700000000000,
        }

        events = [
            {
                "timestamp": "2026-02-26T10:00:00+00:00",
                "event_type": "PromptInjectionComposed",
                "source": "apiserver.chat_stream",
                "payload": {
                    "session_id": shell_session_id,
                    "shell_session_id": shell_session_id,
                    "core_execution_session_id": core_execution_session_id,
                    "route_semantic": "core_execution",
                    "trigger": "core_execution",
                    "prompt_profile": "core_exec_general",
                    "injection_mode": "normal",
                    "delegation_intent": "core_execution",
                    "shell_clarify_budget_escalated": True,
                    "shell_clarify_budget_reason": "clarify_budget_exceeded_auto_escalate_core",
                    "shell_clarify_turns": 1,
                    "shell_clarify_limit": 1,
                    "core_execution_session_created": True,
                },
            },
            {
                "timestamp": "2026-02-26T10:01:00+00:00",
                "event_type": "PromptInjectionComposed",
                "source": "apiserver.chat_stream",
                "payload": {
                    "session_id": "another-session",
                    "shell_session_id": "another-session",
                    "core_execution_session_id": "another-session__core",
                    "route_semantic": "shell_readonly",
                },
            },
        ]
        monkeypatch.setattr(api_server, "_read_chat_route_event_rows", lambda limit=2000: events)

        payload = api_server._build_chat_route_session_state_payload(shell_session_id, limit=10)
        assert payload["status"] == "success"
        assert payload["shell_session_id"] == shell_session_id
        assert payload["core_execution_session_id"] == core_execution_session_id
        assert payload["core_execution_session_exists"] is True
        assert payload["state"]["shell_clarify_turns"] == 1

        history = payload["recent_route_events"]
        assert len(history) == 1
        assert history[0]["route_semantic"] == "core_execution"
        assert history[0]["shell_clarify_budget_escalated"] is True
        assert history[0]["core_execution_session_id"] == core_execution_session_id
    finally:
        api_server.message_manager.delete_session(shell_session_id)
        api_server.message_manager.delete_session(core_execution_session_id)


def test_chat_route_session_state_v1_endpoint_returns_same_snapshot(monkeypatch) -> None:
    shell_session_id = api_server.message_manager.create_session(temporary=True)
    core_execution_session_id = f"{shell_session_id}__core"
    api_server.message_manager.create_session(session_id=core_execution_session_id, temporary=True)
    try:
        session = api_server.message_manager.get_session(shell_session_id)
        assert isinstance(session, dict)
        session[api_server._CHAT_ROUTE_STATE_KEY] = {
            "core_execution_session_id": core_execution_session_id,
            "shell_clarify_turns": 0,
            "last_core_execution_session_id": core_execution_session_id,
            "last_core_escalation_at_ms": 1700000000500,
        }

        monkeypatch.setattr(api_server, "_read_chat_route_event_rows", lambda limit=2000: [])

        direct_payload = api_server._build_chat_route_session_state_payload(shell_session_id, limit=5)
        v1_payload = asyncio.run(api_server.get_chat_route_session_state_v1(session_id=shell_session_id, limit=5))
        base_payload = asyncio.run(api_server.get_chat_route_session_state(session_id=shell_session_id, limit=5))

        assert v1_payload["status"] == "success"
        assert base_payload["status"] == "success"
        assert v1_payload["shell_session_id"] == direct_payload["shell_session_id"] == shell_session_id
        assert (
            v1_payload["core_execution_session_id"]
            == direct_payload["core_execution_session_id"]
            == core_execution_session_id
        )
        assert base_payload["core_execution_session_id"] == direct_payload["core_execution_session_id"]
    finally:
        api_server.message_manager.delete_session(shell_session_id)
        api_server.message_manager.delete_session(core_execution_session_id)


def test_chat_route_session_state_payload_includes_child_heartbeat_snapshot(monkeypatch) -> None:
    shell_session_id = api_server.message_manager.create_session(temporary=True)
    core_execution_session_id = f"{shell_session_id}__core"
    api_server.message_manager.create_session(session_id=core_execution_session_id, temporary=True)
    store = AgentSessionStore(db_path=":memory:")
    mailbox = AgentMailbox(db_path=":memory:")
    try:
        session = api_server.message_manager.get_session(shell_session_id)
        assert isinstance(session, dict)
        session[api_server._CHAT_ROUTE_STATE_KEY] = {
            "core_execution_session_id": core_execution_session_id,
            "shell_clarify_turns": 0,
            "last_core_execution_session_id": core_execution_session_id,
            "last_core_escalation_at_ms": 1700000000500,
        }

        store.create(role="core", session_id=core_execution_session_id)
        store.create(role="expert", parent_id=core_execution_session_id, session_id="expert-heartbeat-1")
        store.create(role="dev", parent_id="expert-heartbeat-1", session_id="dev-heartbeat-1")
        store.publish_task_heartbeat(
            "dev-heartbeat-1",
            task_id="task-1",
            status="running",
            message="still alive",
            ttl_seconds=60,
            generated_at="2026-03-11T00:00:00+00:00",
        )

        monkeypatch.setattr(api_server, "_read_chat_route_event_rows", lambda limit=2000: [])
        monkeypatch.setattr(api_server, "_get_pipeline_runtime_handles", lambda: (store, mailbox, object()))

        payload = api_server._build_chat_route_session_state_payload(shell_session_id, limit=5)
        assert payload["child_heartbeat_summary"]["task_count"] == 1
        assert payload["child_heartbeat_summary"]["sessions_with_heartbeats"] == 1
        assert payload["child_heartbeat_sessions"][0]["session_id"] == "dev-heartbeat-1"
        assert payload["child_heartbeats"][0]["task_id"] == "task-1"
    finally:
        store.close()
        mailbox.close()
        api_server.message_manager.delete_session(shell_session_id)
        api_server.message_manager.delete_session(core_execution_session_id)



def test_chat_route_session_state_snapshot_uses_explicit_session_snapshot_when_no_events() -> None:
    shell_session_id = api_server.message_manager.create_session(temporary=True)
    core_execution_session_id = f"{shell_session_id}__core"
    api_server.message_manager.create_session(session_id=core_execution_session_id, temporary=True)
    try:
        session = api_server.message_manager.get_session(shell_session_id)
        assert isinstance(session, dict)
        session[api_server._CHAT_ROUTE_STATE_KEY] = {
            "core_execution_session_id": core_execution_session_id,
            "shell_clarify_turns": 0,
            "last_core_execution_session_id": core_execution_session_id,
            "last_core_escalation_at_ms": 1700000000500,
            "last_route_semantic": "core_execution",
            "last_active_agent": "core",
            "last_dispatch_to_core": True,
            "last_handoff_tool": "dispatch_to_core",
            "last_core_execution_route": "standard",
            "last_risk_level": "write_repo",
        }

        payload = api_server._build_chat_route_session_state_payload(shell_session_id, limit=5)

        assert payload["status"] == "success"
        assert payload["state"]["last_route_semantic"] == "core_execution"
        assert payload["state"]["last_dispatch_to_core"] is True
        assert payload["state"]["last_core_execution_route"] == "standard"
        assert payload["recent_route_events"][0]["event_type"] == "RouteSessionStateSnapshot"
        assert payload["recent_route_events"][0]["source"] == "session_state_snapshot"
        assert payload["recent_route_events"][0]["route_semantic"] == "core_execution"
        assert payload["recent_route_events"][0]["dispatch_to_core"] is True
        assert payload["recent_route_events"][0]["core_execution_route"] == "standard"
    finally:
        api_server.message_manager.delete_session(shell_session_id)
        api_server.message_manager.delete_session(core_execution_session_id)
