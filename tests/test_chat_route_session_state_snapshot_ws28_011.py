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
            "run_context_id": core_execution_session_id,
            "core_execution_session_id": core_execution_session_id,
            "shell_clarify_turns": 1,
            "last_run_context_id": core_execution_session_id,
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
                    "run_context_id": core_execution_session_id,
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
                    "run_context_created": True,
                },
            },
            {
                "timestamp": "2026-02-26T10:01:00+00:00",
                "event_type": "PromptInjectionComposed",
                "source": "apiserver.chat_stream",
                "payload": {
                    "session_id": "another-session",
                    "shell_session_id": "another-session",
                    "run_context_id": "another-session__core",
                    "core_execution_session_id": "another-session__core",
                    "route_semantic": "shell_readonly",
                },
            },
        ]
        monkeypatch.setattr(api_server, "_read_chat_route_event_rows", lambda limit=2000: events)

        payload = api_server._build_chat_route_session_state_payload(shell_session_id, limit=10)
        assert payload["status"] == "success"
        assert payload["shell_session_id"] == shell_session_id
        assert payload["run_context_id"] == core_execution_session_id
        assert payload["last_run_context_id"] == core_execution_session_id
        assert payload["run_context_exists"] is True
        assert payload["state"]["shell_clarify_turns"] == 1

        history = payload["recent_route_events"]
        assert len(history) == 1
        assert history[0]["route_semantic"] == "core_execution"
        assert history[0]["shell_clarify_budget_escalated"] is True
        assert history[0]["run_context_id"] == core_execution_session_id
        assert history[0]["run_context_created"] is True
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
            "run_context_id": core_execution_session_id,
            "core_execution_session_id": core_execution_session_id,
            "shell_clarify_turns": 0,
            "last_run_context_id": core_execution_session_id,
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
            v1_payload["run_context_id"]
            == direct_payload["run_context_id"]
            == core_execution_session_id
        )
        assert base_payload["run_context_id"] == direct_payload["run_context_id"]
        assert base_payload["last_run_context_id"] == direct_payload["last_run_context_id"]
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


def test_chat_route_session_state_payload_includes_core_worker_queue_state(monkeypatch) -> None:
    async def _run() -> None:
        shell_session_id = api_server.message_manager.create_session(temporary=True)
        store = AgentSessionStore(db_path=":memory:")
        mailbox = AgentMailbox(db_path=":memory:")
        manager = api_server.CoreDispatchJobManager()
        try:
            monkeypatch.setattr(api_server, "_CORE_JOB_MANAGER", manager)
            monkeypatch.setattr(api_server, "_read_chat_route_event_rows", lambda limit=2000: [])
            monkeypatch.setitem(api_server._routes_chat._CHAT_RUNTIME_CONTEXT, "agent_session_store", store)
            monkeypatch.setitem(api_server._routes_chat._CHAT_RUNTIME_CONTEXT, "agent_session_store_getter", None)
            monkeypatch.setitem(api_server._routes_chat._CHAT_RUNTIME_CONTEXT, "agent_mailbox", mailbox)
            monkeypatch.setitem(api_server._routes_chat._CHAT_RUNTIME_CONTEXT, "agent_mailbox_getter", None)
            monkeypatch.setitem(api_server._routes_chat._CHAT_RUNTIME_CONTEXT, "core_job_manager", manager)
            monkeypatch.setitem(api_server._routes_chat._CHAT_RUNTIME_CONTEXT, "core_job_manager_getter", None)

            async def _fake_pipeline_runner(**kwargs):
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

            first = manager.submit_job(
                shell_session_id=shell_session_id,
                goal="first queued route task",
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
                shell_session_id=shell_session_id,
                goal="second queued route task",
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

            await asyncio.sleep(0.02)
            payload = api_server._build_chat_route_session_state_payload(shell_session_id, limit=5)

            assert payload["core_worker_status"] == "running"
            assert payload["current_core_job_id"] == first["job_id"]
            assert payload["queued_core_job_ids"] == [second["job_id"]]
            assert payload["core_queue_depth"] == 1
            assert payload["core_pipeline_depth"] == 2
            assert payload["state"]["core_worker_status"] == "running"
            assert payload["state"]["current_core_job_id"] == first["job_id"]
            assert payload["state"]["queued_core_job_ids"] == [second["job_id"]]
            assert payload["state"]["core_queue_depth"] == 1
            assert payload["state"]["core_pipeline_depth"] == 2
            assert payload["core_mailbox_cursor_seq"] == second["handoff_message_seq"]
            assert payload["last_core_handoff_message_seq"] == second["handoff_message_seq"]
            assert payload["core_recovery_restart_total"] == 0
            assert payload["core_job_watch_dedup_skipped_count"] == 0
            assert payload["core_last_dedup_message_seq"] == 0
            assert payload["run_context_id"] == f"{shell_session_id}__core"
            assert payload["last_run_context_id"] == f"{shell_session_id}__core"

            await asyncio.sleep(0.12)
            completed_payload = api_server._build_chat_route_session_state_payload(shell_session_id, limit=5)
            assert completed_payload["last_core_completion_message_seq"] > 0
            assert completed_payload["state"]["core_recovery_restart_total"] == 0
            assert completed_payload["state"]["core_job_watch_dedup_skipped_count"] == 0
            assert len(completed_payload["recent_core_reports"]) >= 1
            assert completed_payload["recent_core_reports"][-1]["from_id"] == f"{shell_session_id}__core"
            assert completed_payload["recent_core_reports"][-1]["metadata"]["core_job_id"] == second["job_id"]
        finally:
            await manager.shutdown()
            mailbox.close()
            store.close()
            api_server.message_manager.delete_session(shell_session_id)
            api_server.message_manager.delete_session(f"{shell_session_id}__core")

    asyncio.run(_run())


def test_chat_route_session_state_payload_and_core_job_watch_track_unread_async_updates(monkeypatch) -> None:
    async def _run() -> None:
        shell_session_id = api_server.message_manager.create_session(temporary=True)
        core_execution_session_id = f"{shell_session_id}__core"
        api_server.message_manager.create_session(session_id=core_execution_session_id, temporary=True)
        store = AgentSessionStore(db_path=":memory:")
        mailbox = AgentMailbox(db_path=":memory:")
        manager = api_server.CoreDispatchJobManager()
        try:
            monkeypatch.setattr(api_server, "_CORE_JOB_MANAGER", manager)
            monkeypatch.setattr(api_server, "_read_chat_route_event_rows", lambda limit=2000: [])
            monkeypatch.setitem(api_server._routes_chat._CHAT_RUNTIME_CONTEXT, "agent_session_store", store)
            monkeypatch.setitem(api_server._routes_chat._CHAT_RUNTIME_CONTEXT, "agent_session_store_getter", None)
            monkeypatch.setitem(api_server._routes_chat._CHAT_RUNTIME_CONTEXT, "agent_mailbox", mailbox)
            monkeypatch.setitem(api_server._routes_chat._CHAT_RUNTIME_CONTEXT, "agent_mailbox_getter", None)
            monkeypatch.setitem(api_server._routes_chat._CHAT_RUNTIME_CONTEXT, "core_job_manager", manager)
            monkeypatch.setitem(api_server._routes_chat._CHAT_RUNTIME_CONTEXT, "core_job_manager_getter", None)

            api_server._register_core_job_submission(
                shell_session_id,
                core_runtime_id="core-main",
                core_job_id="corejob_async_state_1",
                core_execution_session_id=core_execution_session_id,
            )
            mailbox.send(
                core_execution_session_id,
                shell_session_id,
                "[CORE RUNNING] job_id=corejob_async_state_1 已开始执行：后台任务",
                message_type="status",
                metadata={
                    "kind": "core_job_status",
                    "status": "running",
                    "core_job_id": "corejob_async_state_1",
                    "core_runtime_id": "core-main",
                    "core_execution_session_id": core_execution_session_id,
                },
            )
            mailbox.send(
                core_execution_session_id,
                shell_session_id,
                "[CORE COMPLETED] 后台任务已完成",
                message_type="report",
                metadata={
                    "kind": "core_job_report",
                    "status": "completed",
                    "core_job_id": "corejob_async_state_1",
                    "core_runtime_id": "core-main",
                    "core_execution_session_id": core_execution_session_id,
                },
            )

            payload = api_server._build_chat_route_session_state_payload(shell_session_id, limit=5)
            assert payload["pending_core_update_count"] == 2
            assert len(payload["unread_core_updates"]) == 2
            assert len(payload["recent_core_updates"]) == 2
            assert payload["recent_core_reports"][-1]["message_type"] == "report"
            assert payload["state"]["core_outbox_cursor_seq"] == 0

            inbox_payload = await api_server.get_chat_core_job_watch(shell_session_id, limit=5, ack=True)
            assert inbox_payload["watch_scope"] == "session_triggered_core_jobs"
            assert inbox_payload["run_context_id"] == core_execution_session_id
            assert inbox_payload["run_context_exists"] is True
            assert inbox_payload["watched_core_job"]["run_context_id"] == core_execution_session_id
            assert inbox_payload["pending_core_update_count"] == 0
            assert len(inbox_payload["unread_core_updates"]) == 2
            assert inbox_payload["last_core_outbox_seq"] >= inbox_payload["core_outbox_cursor_seq"] > 0

            payload_after_ack = api_server._build_chat_route_session_state_payload(shell_session_id, limit=5)
            assert payload_after_ack["pending_core_update_count"] == 0
            assert payload_after_ack["unread_core_updates"] == []
            assert payload_after_ack["state"]["core_outbox_cursor_seq"] > 0
            assert (
                payload_after_ack["state"]["core_outbox_cursor_seq"]
                == payload_after_ack["state"]["last_core_outbox_seq"]
            )
        finally:
            await manager.shutdown()
            mailbox.close()
            store.close()
            api_server.message_manager.delete_session(shell_session_id)
            api_server.message_manager.delete_session(core_execution_session_id)

    asyncio.run(_run())
