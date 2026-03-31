from __future__ import annotations

import asyncio
import tempfile
from typing import Any, Callable

import apiserver.core_job_manager as core_job_manager_module
from agents.runtime.agent_session import AgentSessionStore, AgentStatus
from agents.runtime.mailbox import AgentMailbox
from agents.runtime.task_board import TaskBoardEngine, TaskItem
from apiserver.core_job_manager import CoreDispatchJobManager, DEFAULT_CORE_RUNTIME_ID


async def _wait_until(
    predicate: Callable[[], bool],
    *,
    timeout: float = 2.0,
    interval: float = 0.01,
    description: str = "condition",
) -> None:
    deadline = asyncio.get_running_loop().time() + max(0.1, float(timeout))
    while True:
        if predicate():
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"Timed out waiting for {description}")
        await asyncio.sleep(max(0.001, float(interval)))


def test_core_job_manager_submit_run_completes_and_persists_terminal_state() -> None:
    async def _run() -> None:
        manager = CoreDispatchJobManager()
        store = AgentSessionStore(db_path=":memory:")
        mailbox = AgentMailbox(db_path=":memory:")
        started: list[dict[str, Any]] = []

        async def _fake_runner(**kwargs):
            started.append(
                {
                    "goal": str(kwargs.get("message") or ""),
                    "run_context_id": str(kwargs.get("core_execution_session_id") or ""),
                }
            )
            await asyncio.sleep(0.02)
            yield {
                "type": "execution_receipt",
                "pipeline_id": "pipe-core-lifecycle-submit-run",
                "agent_state": {
                    "task_completed": True,
                    "final_answer": "submit-run completed",
                },
            }
            yield {
                "type": "pipeline_end",
                "pipeline_id": "pipe-core-lifecycle-submit-run",
                "reason": "completed",
            }

        manager.configure_runtime_defaults(
            store=store,
            mailbox=mailbox,
            runner=_fake_runner,
            enable_child_execution=False,
            heartbeat_interval_seconds=1.0,
        )

        try:
            submitted = manager.submit_job(
                shell_session_id="shell-core-lifecycle-submit",
                goal="submit-run lifecycle",
                risk_level="write_repo",
                handoff_source="dispatch_to_core",
                route_decision={},
                dispatch_payload={},
                core_runtime_id=DEFAULT_CORE_RUNTIME_ID,
                store=store,
                mailbox=mailbox,
                pipeline_runner=_fake_runner,
                heartbeat_interval_seconds=1.0,
            )

            job_id = str(submitted.get("job_id") or "")
            assert str(submitted.get("status") or "") == "accepted"
            assert str(submitted.get("run_context_id") or "") == "shell-core-lifecycle-submit__core"
            assert bool(submitted.get("run_context_created")) is True
            assert int(submitted.get("queue_position") or 0) == 1
            assert str(submitted.get("worker_status") or "") == "running"
            assert int(submitted.get("handoff_message_seq") or 0) > 0

            await _wait_until(
                lambda: str(manager.get_job_snapshot(job_id, include_events=False).get("status") or "") == "completed",
                description="core job completion",
            )

            snapshot = manager.get_job_snapshot(job_id)
            assert str(snapshot.get("status") or "") == "completed"
            assert str(snapshot.get("pipeline_end_reason") or "") == "completed"
            assert int(snapshot.get("completion_message_seq") or 0) > 0
            assert snapshot.get("worker_status") == "idle"
            dispatch_state = (
                ((snapshot.get("last_execution_receipt") or {}).get("agent_state") or {}).get("core_dispatch") or {}
            )
            assert str(dispatch_state.get("job_id") or "") == job_id
            assert str(dispatch_state.get("shell_session_id") or "") == "shell-core-lifecycle-submit"
            assert str(dispatch_state.get("core_runtime_id") or "") == DEFAULT_CORE_RUNTIME_ID

            assert started == [
                {
                    "goal": "submit-run lifecycle",
                    "run_context_id": "shell-core-lifecycle-submit__core",
                }
            ]

            report_rows = mailbox.read("shell-core-lifecycle-submit", message_type="report")
            assert len(report_rows) == 1
            assert str(report_rows[0].metadata.get("core_job_id") or "") == job_id
            assert str(report_rows[0].content or "").startswith("[CORE COMPLETED]")

            core_runtime = store.get(DEFAULT_CORE_RUNTIME_ID)
            assert core_runtime is not None
            assert core_runtime.status == AgentStatus.WAITING

            core_session = store.get("shell-core-lifecycle-submit__core")
            assert core_session is not None
            assert core_session.status == AgentStatus.WAITING
            assert str(core_session.metadata.get("last_job_id") or "") == job_id
            assert str(core_session.metadata.get("last_pipeline_end_reason") or "") == "completed"

            recovery_state = dict(core_session.metadata.get("core_job_recovery_state") or {})
            assert recovery_state.get("pending_job_ids") == []
            archived_jobs = list(recovery_state.get("recent_terminal_jobs") or [])
            assert len(archived_jobs) == 1
            assert str(archived_jobs[0].get("job_id") or "") == job_id
            assert str(archived_jobs[0].get("status") or "") == "completed"
        finally:
            await manager.shutdown()
            mailbox.close()
            store.close()

    asyncio.run(_run())


def test_core_job_manager_runtime_monitor_recovers_persisted_jobs_in_dedicated_flow() -> None:
    async def _run() -> None:
        manager = CoreDispatchJobManager()
        store = AgentSessionStore(db_path=":memory:")
        mailbox = AgentMailbox(db_path=":memory:")
        shell_session_id = "shell-core-lifecycle-recover"
        core_execution_session_id = f"{shell_session_id}__core"
        job_id = "corejob_recover_dedicated_1"
        started: list[str] = []

        async def _fake_runner(**kwargs):
            started.append(str(kwargs.get("message") or ""))
            await asyncio.sleep(0.02)
            yield {
                "type": "execution_receipt",
                "pipeline_id": "pipe-core-lifecycle-recover",
                "agent_state": {
                    "task_completed": True,
                    "final_answer": "recover completed",
                },
            }
            yield {
                "type": "pipeline_end",
                "pipeline_id": "pipe-core-lifecycle-recover",
                "reason": "completed",
            }

        store.create(
            role="core",
            session_id=DEFAULT_CORE_RUNTIME_ID,
            metadata={"agent_type": "core_runtime", "runtime_kind": "long_lived_core"},
        )
        store.create(
            role="core",
            parent_id=DEFAULT_CORE_RUNTIME_ID,
            session_id=core_execution_session_id,
            metadata={
                "session_kind": "shell_core_root",
                "shell_session_id": shell_session_id,
                "core_runtime_id": DEFAULT_CORE_RUNTIME_ID,
                "core_job_recovery_state": {
                    "shell_session_id": shell_session_id,
                    "core_runtime_id": DEFAULT_CORE_RUNTIME_ID,
                    "mailbox_cursor_seq": 0,
                    "recovery_restart_total": 0,
                    "pending_job_ids": [job_id],
                    "jobs": {
                        job_id: {
                            "job_id": job_id,
                            "shell_session_id": shell_session_id,
                            "core_runtime_id": DEFAULT_CORE_RUNTIME_ID,
                            "core_execution_session_id": core_execution_session_id,
                            "goal": "recover lifecycle flow",
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
                        }
                    },
                    "recent_terminal_jobs": [],
                },
            },
        )
        mailbox.send(
            shell_session_id,
            core_execution_session_id,
            "recover lifecycle flow",
            message_type="query",
            metadata={"core_job_id": job_id},
        )

        manager.configure_runtime_defaults(
            store=store,
            mailbox=mailbox,
            runner=_fake_runner,
            enable_child_execution=False,
            heartbeat_interval_seconds=1.0,
        )

        try:
            await _wait_until(
                lambda: str(manager.get_job_snapshot(job_id, include_events=False).get("status") or "") == "completed",
                timeout=2.5,
                description="recovered core job completion",
            )

            snapshot = manager.get_job_snapshot(job_id)
            assert str(snapshot.get("status") or "") == "completed"
            assert int(snapshot.get("recovery_restart_count") or 0) == 1
            assert str(snapshot.get("run_context_id") or "") == core_execution_session_id
            assert started == ["recover lifecycle flow"]

            shell_snapshot = manager.get_shell_snapshot(shell_session_id, limit=10)
            assert shell_snapshot["worker_status"] == "idle"
            assert shell_snapshot["queue_depth"] == 0
            assert shell_snapshot["pipeline_depth"] == 0
            assert int(shell_snapshot["recovery_restart_total"] or 0) == 1
            assert str(shell_snapshot["latest_job"]["job_id"] or "") == job_id
            assert str(shell_snapshot["latest_job"]["status"] or "") == "completed"

            report_rows = mailbox.read(shell_session_id, message_type="report")
            assert len(report_rows) == 1
            assert str(report_rows[0].metadata.get("core_job_id") or "") == job_id
            assert str(report_rows[0].content or "").startswith("[CORE COMPLETED]")

            core_session = store.get(core_execution_session_id)
            assert core_session is not None
            recovery_state = dict(core_session.metadata.get("core_job_recovery_state") or {})
            assert recovery_state.get("pending_job_ids") == []
            assert int(recovery_state.get("recovery_restart_total") or 0) == 1
            archived_jobs = list(recovery_state.get("recent_terminal_jobs") or [])
            assert len(archived_jobs) == 1
            assert str(archived_jobs[0].get("job_id") or "") == job_id
        finally:
            await manager.shutdown()
            mailbox.close()
            store.close()

    asyncio.run(_run())


def test_core_job_manager_runner_exception_marks_failed_and_reports_error() -> None:
    async def _run() -> None:
        manager = CoreDispatchJobManager()
        store = AgentSessionStore(db_path=":memory:")
        mailbox = AgentMailbox(db_path=":memory:")

        async def _failing_runner(**kwargs):
            del kwargs
            await asyncio.sleep(0.02)
            if False:
                yield {}
            raise RuntimeError("pipeline exploded")

        manager.configure_runtime_defaults(
            store=store,
            mailbox=mailbox,
            runner=_failing_runner,
            enable_child_execution=False,
            heartbeat_interval_seconds=1.0,
        )

        try:
            submitted = manager.submit_job(
                shell_session_id="shell-core-lifecycle-failed",
                goal="runner should fail",
                risk_level="write_repo",
                handoff_source="dispatch_to_core",
                route_decision={},
                dispatch_payload={},
                core_runtime_id=DEFAULT_CORE_RUNTIME_ID,
                store=store,
                mailbox=mailbox,
                pipeline_runner=_failing_runner,
                heartbeat_interval_seconds=1.0,
            )
            job_id = str(submitted.get("job_id") or "")

            await _wait_until(
                lambda: str(manager.get_job_snapshot(job_id, include_events=False).get("status") or "") == "failed",
                description="failed core job completion",
            )

            snapshot = manager.get_job_snapshot(job_id)
            assert str(snapshot.get("status") or "") == "failed"
            assert str(snapshot.get("error_text") or "") == "pipeline exploded"
            assert str(snapshot.get("pipeline_end_reason") or "") == ""
            assert int(snapshot.get("completion_message_seq") or 0) > 0

            report_rows = mailbox.read("shell-core-lifecycle-failed", message_type="report")
            assert len(report_rows) == 1
            assert str(report_rows[0].metadata.get("core_job_id") or "") == job_id
            assert str(report_rows[0].metadata.get("status") or "") == "failed"
            assert "pipeline exploded" in str(report_rows[0].content or "")

            core_session = store.get("shell-core-lifecycle-failed__core")
            assert core_session is not None
            assert core_session.status == AgentStatus.WAITING
            assert str(core_session.metadata.get("last_job_id") or "") == job_id
            assert str(core_session.metadata.get("last_error_text") or "") == "pipeline exploded"
        finally:
            await manager.shutdown()
            mailbox.close()
            store.close()

    asyncio.run(_run())


def test_core_job_manager_serializes_jobs_tracks_dedup_and_exposes_full_shell_snapshot() -> None:
    async def _run() -> None:
        manager = CoreDispatchJobManager()
        store = AgentSessionStore(db_path=":memory:")
        mailbox = AgentMailbox(db_path=":memory:")
        started: list[dict[str, Any]] = []

        async def _fake_runner(**kwargs):
            started.append(
                {
                    "goal": str(kwargs.get("message") or ""),
                    "run_context_id": str(kwargs.get("core_execution_session_id") or ""),
                }
            )
            await asyncio.sleep(0.05)
            yield {
                "type": "execution_receipt",
                "pipeline_id": f"pipe-serial-{len(started)}",
                "agent_state": {
                    "task_completed": True,
                    "final_answer": str(kwargs.get("message") or ""),
                },
            }
            yield {
                "type": "pipeline_end",
                "pipeline_id": f"pipe-serial-{len(started)}",
                "reason": "completed",
            }

        manager.configure_runtime_defaults(
            store=store,
            mailbox=mailbox,
            runner=_fake_runner,
            enable_child_execution=False,
            heartbeat_interval_seconds=1.0,
        )

        try:
            first = manager.submit_job(
                shell_session_id="shell-core-lifecycle-serial",
                goal="first serial task",
                risk_level="write_repo",
                handoff_source="dispatch_to_core",
                route_decision={},
                dispatch_payload={},
                core_runtime_id=DEFAULT_CORE_RUNTIME_ID,
                store=store,
                mailbox=mailbox,
                pipeline_runner=_fake_runner,
                heartbeat_interval_seconds=1.0,
            )
            second = manager.submit_job(
                shell_session_id="shell-core-lifecycle-serial",
                goal="second serial task",
                risk_level="write_repo",
                handoff_source="dispatch_to_core",
                route_decision={},
                dispatch_payload={},
                core_runtime_id=DEFAULT_CORE_RUNTIME_ID,
                store=store,
                mailbox=mailbox,
                pipeline_runner=_fake_runner,
                heartbeat_interval_seconds=1.0,
            )

            assert str(first.get("run_context_id") or "") == "shell-core-lifecycle-serial__core"
            assert str(second.get("run_context_id") or "") == "shell-core-lifecycle-serial__core"
            assert bool(first.get("run_context_created")) is True
            assert bool(second.get("run_context_created")) is False
            assert int(first.get("queue_position") or 0) == 1
            assert int(second.get("queue_position") or 0) == 2

            mailbox.send(
                "shell-core-lifecycle-serial",
                "shell-core-lifecycle-serial__core",
                "duplicate second serial task",
                message_type="query",
                metadata={"core_job_id": str(second.get("job_id") or "")},
            )

            await asyncio.sleep(0.02)

            first_snapshot = manager.get_job_snapshot(str(first.get("job_id") or ""))
            second_snapshot = manager.get_job_snapshot(str(second.get("job_id") or ""))
            assert str(first_snapshot.get("status") or "") == "running"
            assert str(second_snapshot.get("status") or "") == "accepted"
            assert str(first_snapshot.get("current_job_id") or "") == str(first.get("job_id") or "")
            assert list(first_snapshot.get("queued_job_ids") or []) == [str(second.get("job_id") or "")]
            assert int(first_snapshot.get("queue_position") or 0) == 1
            assert int(second_snapshot.get("queue_position") or 0) == 2
            assert int(second_snapshot.get("handoff_duplicate_count") or 0) == 1

            duplicate_snapshot = manager.get_shell_snapshot("shell-core-lifecycle-serial", limit=10)
            expected_shell_snapshot_fields = {
                "shell_session_id",
                "core_runtime_id",
                "active_job_id",
                "active_job_ids",
                "latest_job_id",
                "latest_job",
                "active_job",
                "jobs",
                "worker_status",
                "current_job_id",
                "queued_job_ids",
                "queue_depth",
                "pipeline_depth",
                "mailbox_cursor_seq",
                "recovery_restart_total",
                "inbox_dedup_skipped_count",
                "last_dedup_message_seq",
                "latest_handoff_message_seq",
                "latest_completion_message_seq",
            }
            assert expected_shell_snapshot_fields.issubset(set(duplicate_snapshot.keys()))
            assert duplicate_snapshot["shell_session_id"] == "shell-core-lifecycle-serial"
            assert duplicate_snapshot["core_runtime_id"] == DEFAULT_CORE_RUNTIME_ID
            assert duplicate_snapshot["active_job_id"] == str(first.get("job_id") or "")
            assert duplicate_snapshot["active_job_ids"] == [str(first.get("job_id") or ""), str(second.get("job_id") or "")]
            assert duplicate_snapshot["latest_job_id"] == str(second.get("job_id") or "")
            assert duplicate_snapshot["current_job_id"] == str(first.get("job_id") or "")
            assert duplicate_snapshot["queued_job_ids"] == [str(second.get("job_id") or "")]
            assert int(duplicate_snapshot["queue_depth"] or 0) == 1
            assert int(duplicate_snapshot["pipeline_depth"] or 0) == 2
            assert int(duplicate_snapshot["recovery_restart_total"] or 0) == 0
            assert int(duplicate_snapshot["inbox_dedup_skipped_count"] or 0) == 1
            assert int(duplicate_snapshot["last_dedup_message_seq"] or 0) > int(second.get("handoff_message_seq") or 0)
            assert int(duplicate_snapshot["latest_handoff_message_seq"] or 0) == int(second.get("handoff_message_seq") or 0)
            assert int(duplicate_snapshot["latest_completion_message_seq"] or 0) == 0

            await _wait_until(
                lambda: (
                    str(manager.get_job_snapshot(str(first.get("job_id") or ""), include_events=False).get("status") or "") == "completed"
                    and str(manager.get_job_snapshot(str(second.get("job_id") or ""), include_events=False).get("status") or "") == "completed"
                ),
                description="serialized core jobs completion",
            )

            final_shell_snapshot = manager.get_shell_snapshot("shell-core-lifecycle-serial", limit=10)
            assert final_shell_snapshot["shell_session_id"] == "shell-core-lifecycle-serial"
            assert final_shell_snapshot["core_runtime_id"] == DEFAULT_CORE_RUNTIME_ID
            assert final_shell_snapshot["active_job_id"] == ""
            assert final_shell_snapshot["active_job_ids"] == []
            assert final_shell_snapshot["latest_job_id"] == str(second.get("job_id") or "")
            assert str((final_shell_snapshot["latest_job"] or {}).get("job_id") or "") == str(second.get("job_id") or "")
            assert final_shell_snapshot["active_job"] == {}
            assert len(final_shell_snapshot["jobs"]) == 2
            assert final_shell_snapshot["worker_status"] == "idle"
            assert final_shell_snapshot["current_job_id"] == ""
            assert final_shell_snapshot["queued_job_ids"] == []
            assert int(final_shell_snapshot["queue_depth"] or 0) == 0
            assert int(final_shell_snapshot["pipeline_depth"] or 0) == 0
            assert int(final_shell_snapshot["mailbox_cursor_seq"] or 0) >= int(duplicate_snapshot["last_dedup_message_seq"] or 0)
            assert int(final_shell_snapshot["recovery_restart_total"] or 0) == 0
            assert int(final_shell_snapshot["inbox_dedup_skipped_count"] or 0) == 1
            assert int(final_shell_snapshot["last_dedup_message_seq"] or 0) == int(duplicate_snapshot["last_dedup_message_seq"] or 0)
            assert int(final_shell_snapshot["latest_handoff_message_seq"] or 0) == int(second.get("handoff_message_seq") or 0)
            second_final_snapshot = manager.get_job_snapshot(str(second.get("job_id") or ""))
            assert int(final_shell_snapshot["latest_completion_message_seq"] or 0) == int(second_final_snapshot.get("completion_message_seq") or 0)

            receipt_dispatch = (
                ((second_final_snapshot.get("last_execution_receipt") or {}).get("agent_state") or {}).get("core_dispatch")
                or {}
            )
            assert int(receipt_dispatch.get("handoff_duplicate_count") or 0) == 1
            assert int(receipt_dispatch.get("shell_inbox_dedup_skipped_count") or 0) == 1
            assert [item["goal"] for item in started] == ["first serial task", "second serial task"]
            assert all(item["run_context_id"] == "shell-core-lifecycle-serial__core" for item in started)
        finally:
            await manager.shutdown()
            mailbox.close()
            store.close()

    asyncio.run(_run())


def test_core_job_manager_waiting_descendants_persists_active_waiting_state() -> None:
    async def _run() -> None:
        manager = CoreDispatchJobManager()
        store = AgentSessionStore(db_path=":memory:")
        mailbox = AgentMailbox(db_path=":memory:")
        shell_session_id = "shell-core-lifecycle-waiting"

        async def _fake_runner(**kwargs):
            pipeline_id = "pipe-core-lifecycle-waiting"
            core_execution_session_id = str(kwargs.get("core_execution_session_id") or "")
            if store.get("expert_core_lifecycle_waiting_1") is None:
                store.create(
                    role="expert",
                    parent_id=core_execution_session_id,
                    session_id="expert_core_lifecycle_waiting_1",
                    metadata={"pipeline_id": pipeline_id},
                )
                store.update_status("expert_core_lifecycle_waiting_1", AgentStatus.WAITING)
            await asyncio.sleep(0.02)
            yield {
                "type": "execution_receipt",
                "pipeline_id": pipeline_id,
                "agent_state": {
                    "task_completed": False,
                    "final_answer": "waiting on descendant output",
                },
            }
            yield {
                "type": "pipeline_end",
                "pipeline_id": pipeline_id,
                "reason": "delegated_waiting_child_completion",
            }

        manager.configure_runtime_defaults(
            store=store,
            mailbox=mailbox,
            runner=_fake_runner,
            enable_child_execution=False,
            heartbeat_interval_seconds=1.0,
        )

        try:
            submitted = manager.submit_job(
                shell_session_id=shell_session_id,
                goal="wait on deferred descendant",
                risk_level="write_repo",
                handoff_source="dispatch_to_core",
                route_decision={},
                dispatch_payload={},
                core_runtime_id=DEFAULT_CORE_RUNTIME_ID,
                store=store,
                mailbox=mailbox,
                pipeline_runner=_fake_runner,
                heartbeat_interval_seconds=1.0,
            )
            job_id = str(submitted.get("job_id") or "")

            await _wait_until(
                lambda: str(manager.get_job_snapshot(job_id, include_events=False).get("status") or "") == "waiting_descendants",
                description="waiting descendants state",
            )

            waiting_snapshot = manager.get_job_snapshot(job_id)
            assert str(waiting_snapshot.get("status") or "") == "waiting_descendants"
            assert int(waiting_snapshot.get("pending_descendant_count") or 0) == 1
            assert waiting_snapshot.get("pending_descendant_ids") == ["expert_core_lifecycle_waiting_1"]
            assert str(waiting_snapshot.get("pipeline_end_reason") or "") == "delegated_waiting_child_completion"

            shell_snapshot = manager.get_shell_snapshot(shell_session_id, limit=10)
            assert shell_snapshot["active_job_id"] == job_id
            assert shell_snapshot["active_job_ids"] == [job_id]
            assert str((shell_snapshot["active_job"] or {}).get("status") or "") == "waiting_descendants"
            assert shell_snapshot["worker_status"] == "idle"
            assert shell_snapshot["current_job_id"] == ""
            assert shell_snapshot["queued_job_ids"] == []
            assert int(shell_snapshot["queue_depth"] or 0) == 0
            assert int(shell_snapshot["pipeline_depth"] or 0) == 1

            core_session = store.get(f"{shell_session_id}__core")
            assert core_session is not None
            assert core_session.status == AgentStatus.WAITING
            recovery_state = dict(core_session.metadata.get("core_job_recovery_state") or {})
            assert recovery_state["pending_job_ids"] == [job_id]
            assert str(((recovery_state.get("jobs") or {}).get(job_id) or {}).get("status") or "") == "waiting_descendants"

            report_rows = mailbox.read(shell_session_id, message_type="report")
            assert report_rows == []
        finally:
            await manager.shutdown()
            mailbox.close()
            store.close()

    asyncio.run(_run())


def test_core_job_manager_try_advance_waiting_descendants_records_progress(monkeypatch) -> None:
    async def _run() -> None:
        manager = CoreDispatchJobManager()
        store = AgentSessionStore(db_path=":memory:")
        mailbox = AgentMailbox(db_path=":memory:")
        shell_session_id = "shell-core-lifecycle-advance"
        observed_child_max_rounds: list[int] = []

        async def _fake_runner(**kwargs):
            pipeline_id = "pipe-core-lifecycle-advance"
            core_execution_session_id = str(kwargs.get("core_execution_session_id") or "")
            if store.get("expert_core_lifecycle_advance_1") is None:
                store.create(
                    role="expert",
                    parent_id=core_execution_session_id,
                    session_id="expert_core_lifecycle_advance_1",
                    metadata={"pipeline_id": pipeline_id},
                )
                store.update_status("expert_core_lifecycle_advance_1", AgentStatus.WAITING)
            await asyncio.sleep(0.02)
            yield {
                "type": "execution_receipt",
                "pipeline_id": pipeline_id,
                "agent_state": {
                    "task_completed": False,
                    "final_answer": "advance waiting descendants once",
                },
            }
            yield {
                "type": "pipeline_end",
                "pipeline_id": pipeline_id,
                "reason": "delegated_waiting_child_completion",
            }

        manager.configure_runtime_defaults(
            store=store,
            mailbox=mailbox,
            runner=_fake_runner,
            enable_child_execution=True,
            child_max_rounds=19,
            heartbeat_interval_seconds=1.0,
        )

        try:
            submitted = manager.submit_job(
                shell_session_id=shell_session_id,
                goal="advance waiting descendants",
                risk_level="write_repo",
                handoff_source="dispatch_to_core",
                route_decision={},
                dispatch_payload={},
                core_runtime_id=DEFAULT_CORE_RUNTIME_ID,
                store=store,
                mailbox=mailbox,
                pipeline_runner=_fake_runner,
                enable_child_execution=True,
                child_max_rounds=19,
                heartbeat_interval_seconds=1.0,
            )
            job_id = str(submitted.get("job_id") or "")

            await _wait_until(
                lambda: str(manager.get_job_snapshot(job_id, include_events=False).get("status") or "") == "waiting_descendants",
                description="waiting descendants before advance",
            )

            async def _fake_advance_waiting_descendants_once(**kwargs):
                observed_child_max_rounds.append(int(kwargs.get("child_max_rounds") or 0))
                emit = kwargs.get("emit")
                if callable(emit):
                    await emit(
                        {
                            "type": "waiting_descendants_advance_start",
                            "pipeline_id": "pipe-core-lifecycle-advance",
                            "core_execution_session_id": str(kwargs.get("core_execution_session_id") or ""),
                            "pending_descendant_count": 1,
                            "pending_descendant_ids": ["expert_core_lifecycle_advance_1"],
                        }
                    )
                return {
                    "progress_made": True,
                    "pending_count_before": 1,
                    "pending_count_after": 1,
                    "advanced_dev_ids": [],
                    "advanced_review_ids": [],
                    "refreshed_expert_ids": [],
                    "errors": [],
                }

            monkeypatch.setattr(
                core_job_manager_module,
                "advance_core_waiting_descendants_once",
                _fake_advance_waiting_descendants_once,
            )

            progressed = await manager._try_advance_waiting_descendants(job_id)
            assert progressed is True
            assert observed_child_max_rounds == [19]

            advanced_snapshot = manager.get_job_snapshot(job_id)
            recent_event_types = [str(item.get("type") or "") for item in advanced_snapshot.get("recent_events") or []]
            assert "waiting_descendants_advance_start" in recent_event_types
            assert "waiting_descendants_progress" in recent_event_types
            assert str(advanced_snapshot.get("status") or "") == "waiting_descendants"
        finally:
            await manager.shutdown()
            mailbox.close()
            store.close()

    asyncio.run(_run())


def test_core_job_manager_waiting_descendants_request_changes_runs_remediation_cycle() -> None:
    async def _run() -> None:
        tempdir = tempfile.TemporaryDirectory()
        manager = CoreDispatchJobManager()
        store = AgentSessionStore(db_path=":memory:")
        mailbox = AgentMailbox(db_path=":memory:")
        task_board = TaskBoardEngine(
            boards_dir=f"{tempdir.name}/boards",
            db_path=":memory:",
        )
        shell_session_id = "shell-core-lifecycle-request-changes"
        review_call_counts = {"cycle1": 0, "cycle2": 0}

        async def _fake_pipeline_runner(**kwargs):
            pipeline_id = "pipe-core-lifecycle-request-changes"
            core_execution_session_id = str(kwargs.get("core_execution_session_id") or "")
            if store.get("expert_core_lifecycle_request_changes_1") is None:
                board = task_board.create_board(
                    expert_type="backend",
                    tasks=[TaskItem(task_id="t-001", title="Implement remediation path", files=["agents/pipeline.py"])],
                )
                store.create(
                    role="expert",
                    parent_id=core_execution_session_id,
                    session_id="expert_core_lifecycle_request_changes_1",
                    task_description="Implement remediation path",
                    prompt_blocks=["agents/dev/dev_agent.md"],
                    tool_subset=["read_file", "grep", "patch"],
                    metadata={
                        "pipeline_id": pipeline_id,
                        "board_id": board.board_id,
                        "original_task": "Implement remediation path",
                    },
                )
                store.update_status("expert_core_lifecycle_request_changes_1", AgentStatus.WAITING)
                store.create(
                    role="dev",
                    parent_id="expert_core_lifecycle_request_changes_1",
                    session_id="dev_core_lifecycle_request_changes_1",
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
                store.update_status("dev_core_lifecycle_request_changes_1", AgentStatus.WAITING)
                store.create(
                    role="review",
                    parent_id="expert_core_lifecycle_request_changes_1",
                    session_id="review_core_lifecycle_request_changes_1",
                    task_description="Review cycle 1 for TaskBoard: independently verify the completed work.",
                    prompt_blocks=["agents/review/code_reviewer.md"],
                    tool_subset=["memory_read", "memory_grep", "memory_tag", "memory_deprecate"],
                    metadata={
                        "pipeline_id": pipeline_id,
                        "review_cycle": 1,
                        "changed_files": ["agents/pipeline.py"],
                    },
                )
                store.update_status("review_core_lifecycle_request_changes_1", AgentStatus.WAITING)
            await asyncio.sleep(0.02)
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

        manager.configure_runtime_defaults(
            store=store,
            mailbox=mailbox,
            task_board_engine=task_board,
            runner=_fake_pipeline_runner,
            child_llm_call=_fake_child_llm_call,
            child_tool_executor=_fake_child_tool_executor,
            enable_child_execution=True,
            heartbeat_interval_seconds=1.0,
        )

        try:
            submitted = manager.submit_job(
                shell_session_id=shell_session_id,
                goal="continue orchestration through request_changes remediation",
                risk_level="write_repo",
                handoff_source="dispatch_to_core",
                route_decision={},
                dispatch_payload={},
                core_runtime_id=DEFAULT_CORE_RUNTIME_ID,
                store=store,
                mailbox=mailbox,
                task_board_engine=task_board,
                pipeline_runner=_fake_pipeline_runner,
                child_llm_call=_fake_child_llm_call,
                child_tool_executor=_fake_child_tool_executor,
                enable_child_execution=True,
                heartbeat_interval_seconds=1.0,
            )
            job_id = str(submitted.get("job_id") or "")

            await _wait_until(
                lambda: str(manager.get_job_snapshot(job_id, include_events=False).get("status") or "") == "waiting_descendants",
                description="request changes waiting descendants",
            )

            waiting_snapshot = manager.get_job_snapshot(job_id)
            assert str(waiting_snapshot.get("status") or "") == "waiting_descendants"
            assert set(waiting_snapshot.get("pending_descendant_ids") or []) == {
                "expert_core_lifecycle_request_changes_1",
                "review_core_lifecycle_request_changes_1",
            }

            await _wait_until(
                lambda: str(manager.get_job_snapshot(job_id, include_events=False).get("status") or "") == "completed",
                timeout=3.0,
                description="request changes remediation completion",
            )

            final_snapshot = manager.get_job_snapshot(job_id)
            assert str(final_snapshot.get("status") or "") == "completed"
            assert int(final_snapshot.get("pending_descendant_count") or 0) == 0
            assert review_call_counts["cycle1"] >= 1
            assert review_call_counts["cycle2"] >= 1

            recent_event_types = [str(item.get("type") or "") for item in final_snapshot.get("recent_events") or []]
            assert "review_rework_requested" in recent_event_types
            assert "dev_review_resume_start" in recent_event_types
            assert "review_spawned" in recent_event_types
        finally:
            await manager.shutdown()
            task_board.close()
            mailbox.close()
            store.close()
            tempdir.cleanup()

    asyncio.run(_run())


def test_core_job_manager_waiting_descendants_reject_respawns_new_dev() -> None:
    async def _run() -> None:
        tempdir = tempfile.TemporaryDirectory()
        manager = CoreDispatchJobManager()
        store = AgentSessionStore(db_path=":memory:")
        mailbox = AgentMailbox(db_path=":memory:")
        task_board = TaskBoardEngine(
            boards_dir=f"{tempdir.name}/boards",
            db_path=":memory:",
        )
        shell_session_id = "shell-core-lifecycle-reject-respawn"
        review_call_counts = {"cycle1": 0, "cycle2": 0}

        async def _fake_pipeline_runner(**kwargs):
            pipeline_id = "pipe-core-lifecycle-reject-respawn"
            core_execution_session_id = str(kwargs.get("core_execution_session_id") or "")
            if store.get("expert_core_lifecycle_reject_respawn_1") is None:
                board = task_board.create_board(
                    expert_type="backend",
                    tasks=[TaskItem(task_id="t-001", title="Implement reject remediation", files=["agents/pipeline.py"])],
                )
                store.create(
                    role="expert",
                    parent_id=core_execution_session_id,
                    session_id="expert_core_lifecycle_reject_respawn_1",
                    task_description="Implement reject remediation",
                    prompt_blocks=["agents/dev/dev_agent.md"],
                    tool_subset=["read_file", "grep", "patch"],
                    metadata={
                        "pipeline_id": pipeline_id,
                        "board_id": board.board_id,
                        "original_task": "Implement reject remediation",
                    },
                )
                store.update_status("expert_core_lifecycle_reject_respawn_1", AgentStatus.WAITING)
                store.create(
                    role="dev",
                    parent_id="expert_core_lifecycle_reject_respawn_1",
                    session_id="dev_core_lifecycle_reject_respawn_1",
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
                store.update_status("dev_core_lifecycle_reject_respawn_1", AgentStatus.WAITING)
                store.create(
                    role="review",
                    parent_id="expert_core_lifecycle_reject_respawn_1",
                    session_id="review_core_lifecycle_reject_respawn_1",
                    task_description="Review cycle 1 for TaskBoard: independently verify the completed work.",
                    prompt_blocks=["agents/review/code_reviewer.md"],
                    tool_subset=["memory_read", "memory_grep", "memory_tag", "memory_deprecate"],
                    metadata={
                        "pipeline_id": pipeline_id,
                        "review_cycle": 1,
                        "changed_files": ["agents/pipeline.py"],
                    },
                )
                store.update_status("review_core_lifecycle_reject_respawn_1", AgentStatus.WAITING)
            await asyncio.sleep(0.02)
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

        manager.configure_runtime_defaults(
            store=store,
            mailbox=mailbox,
            task_board_engine=task_board,
            runner=_fake_pipeline_runner,
            child_llm_call=_fake_child_llm_call,
            child_tool_executor=_fake_child_tool_executor,
            enable_child_execution=True,
            heartbeat_interval_seconds=1.0,
        )

        try:
            submitted = manager.submit_job(
                shell_session_id=shell_session_id,
                goal="continue orchestration through reject respawn flow",
                risk_level="write_repo",
                handoff_source="dispatch_to_core",
                route_decision={},
                dispatch_payload={},
                core_runtime_id=DEFAULT_CORE_RUNTIME_ID,
                store=store,
                mailbox=mailbox,
                task_board_engine=task_board,
                pipeline_runner=_fake_pipeline_runner,
                child_llm_call=_fake_child_llm_call,
                child_tool_executor=_fake_child_tool_executor,
                enable_child_execution=True,
                heartbeat_interval_seconds=1.0,
            )
            job_id = str(submitted.get("job_id") or "")

            await _wait_until(
                lambda: str(manager.get_job_snapshot(job_id, include_events=False).get("status") or "") == "waiting_descendants",
                description="reject respawn waiting descendants",
            )

            waiting_snapshot = manager.get_job_snapshot(job_id)
            assert str(waiting_snapshot.get("status") or "") == "waiting_descendants"
            assert set(waiting_snapshot.get("pending_descendant_ids") or []) == {
                "expert_core_lifecycle_reject_respawn_1",
                "review_core_lifecycle_reject_respawn_1",
            }

            await _wait_until(
                lambda: str(manager.get_job_snapshot(job_id, include_events=False).get("status") or "") == "completed",
                timeout=3.0,
                description="reject respawn completion",
            )

            final_snapshot = manager.get_job_snapshot(job_id)
            assert str(final_snapshot.get("status") or "") == "completed"
            assert int(final_snapshot.get("pending_descendant_count") or 0) == 0
            assert review_call_counts["cycle1"] >= 1
            assert review_call_counts["cycle2"] >= 1

            recent_event_types = [str(item.get("type") or "") for item in final_snapshot.get("recent_events") or []]
            assert "review_reject_respawn" in recent_event_types
            assert "dev_loop_start" in recent_event_types
            assert "review_spawned" in recent_event_types

            descendants = list(store.list_children("expert_core_lifecycle_reject_respawn_1") or [])
            dev_ids = {str(item.session_id or "") for item in descendants if str(item.role or "") == "dev"}
            assert len(dev_ids) >= 2
        finally:
            await manager.shutdown()
            task_board.close()
            mailbox.close()
            store.close()
            tempdir.cleanup()

    asyncio.run(_run())


def test_core_job_manager_shutdown_cancels_live_tasks_and_clears_runtime_handles() -> None:
    async def _run() -> None:
        manager = CoreDispatchJobManager()
        store = AgentSessionStore(db_path=":memory:")
        mailbox = AgentMailbox(db_path=":memory:")
        entered = asyncio.Event()
        cancelled = asyncio.Event()

        async def _blocking_runner(**kwargs):
            del kwargs
            entered.set()
            try:
                while True:
                    await asyncio.sleep(10)
                    if False:
                        yield {}
            except asyncio.CancelledError:
                cancelled.set()
                raise

        manager.configure_runtime_defaults(
            store=store,
            mailbox=mailbox,
            runner=_blocking_runner,
            enable_child_execution=False,
            heartbeat_interval_seconds=1.0,
        )

        submitted = manager.submit_job(
            shell_session_id="shell-core-lifecycle-shutdown",
            goal="shutdown cancellation flow",
            risk_level="write_repo",
            handoff_source="dispatch_to_core",
            route_decision={},
            dispatch_payload={},
            core_runtime_id=DEFAULT_CORE_RUNTIME_ID,
            store=store,
            mailbox=mailbox,
            pipeline_runner=_blocking_runner,
            heartbeat_interval_seconds=1.0,
        )
        job_id = str(submitted.get("job_id") or "")

        try:
            await asyncio.wait_for(entered.wait(), timeout=1.0)

            runtime_monitor_task = manager._runtime_monitor_task
            shell_worker_task = manager._shell_workers.get("shell-core-lifecycle-shutdown")
            heartbeat_task = manager._heartbeat_tasks.get(job_id)

            assert runtime_monitor_task is not None
            assert shell_worker_task is not None
            assert heartbeat_task is not None

            await manager.shutdown()

            assert cancelled.is_set()
            assert runtime_monitor_task.done()
            assert shell_worker_task.done()
            assert heartbeat_task.done()
            assert manager._runtime_monitor_task is None
            assert manager._job_tasks == {}
            assert manager._heartbeat_tasks == {}
            assert manager._job_specs == {}
            assert manager._shell_workers == {}
            assert manager._shell_current_jobs == {}
            assert manager._shell_queues == {}

            snapshot = manager.get_job_snapshot(job_id, include_events=False)
            assert str(snapshot.get("status") or "") == "cancelled"

            core_runtime = store.get(DEFAULT_CORE_RUNTIME_ID)
            assert core_runtime is not None
            assert core_runtime.status == AgentStatus.WAITING

            core_session = store.get("shell-core-lifecycle-shutdown__core")
            assert core_session is not None
            assert core_session.status == AgentStatus.WAITING

            report_rows = mailbox.read("shell-core-lifecycle-shutdown", message_type="report")
            assert report_rows == []
            assert int(snapshot.get("completion_message_seq") or 0) == 0
        finally:
            mailbox.close()
            store.close()

    asyncio.run(_run())
