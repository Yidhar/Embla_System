"""Agentic loop guard helper tests (WS13-002 + WS14-003 signal path)."""

from __future__ import annotations

import asyncio

import apiserver.agentic_tool_loop as tool_loop
from apiserver.agentic_tool_loop import _apply_parallel_contract_gate, _requires_global_mutex
from system.global_mutex import LeaseHandle


def test_contract_gate_downgrades_missing_checksum_parallel_writes_to_readonly():
    calls = [
        {"agentType": "native", "tool_name": "write_file", "path": "a.txt", "content": "a"},
        {"agentType": "native", "tool_name": "workspace_txn_apply", "changes": [{"path": "b.txt", "content": "b"}]},
        {"agentType": "native", "tool_name": "read_file", "path": "README.md"},
    ]
    decision = _apply_parallel_contract_gate(calls)
    assert decision.readonly_downgraded is True
    assert decision.force_serial is False
    assert decision.reason == "contract_checksum_missing_parallel_write_downgraded_to_readonly"
    assert decision.dropped_mutating_calls == 2
    assert decision.messages
    assert decision.validation_errors
    assert len(decision.actionable_calls) == 1
    assert decision.actionable_calls[0]["tool_name"] == "read_file"


def test_contract_gate_passes_when_contract_matches():
    calls = [
        {
            "agentType": "native",
            "tool_name": "write_file",
            "path": "a.txt",
            "content": "a",
            "contract_id": "contract-1",
            "contract_checksum": "same",
        },
        {
            "agentType": "native",
            "tool_name": "workspace_txn_apply",
            "changes": [{"path": "b.txt", "content": "b"}],
            "contract_id": "contract-1",
            "contract_checksum": "same",
        },
    ]
    decision = _apply_parallel_contract_gate(calls)
    assert decision.force_serial is False
    assert decision.readonly_downgraded is False
    assert decision.messages == []
    assert decision.validation_errors == []
    assert len(decision.actionable_calls) == 2


def test_contract_gate_still_serializes_when_contract_id_mismatched():
    calls = [
        {
            "agentType": "native",
            "tool_name": "write_file",
            "path": "a.txt",
            "content": "a",
            "contract_id": "contract-1",
            "contract_checksum": "same",
        },
        {
            "agentType": "native",
            "tool_name": "workspace_txn_apply",
            "changes": [{"path": "b.txt", "content": "b"}],
            "contract_id": "contract-2",
            "contract_checksum": "same",
        },
    ]
    decision = _apply_parallel_contract_gate(calls)
    assert decision.force_serial is True
    assert decision.readonly_downgraded is False
    assert decision.messages
    assert all(bool(call.get("_force_serial")) for call in calls)


def test_global_mutex_signal_for_run_cmd_install():
    call = {
        "agentType": "native",
        "tool_name": "run_cmd",
        "command": "npm install",
    }
    assert _requires_global_mutex(call) is True


def test_global_mutex_signal_for_read_only_call():
    call = {
        "agentType": "native",
        "tool_name": "read_file",
        "path": "README.md",
    }
    assert _requires_global_mutex(call) is False


def test_global_mutex_pre_acquire_scavenger_runs_and_attaches_report(monkeypatch):
    class DummyMutexManager:
        def __init__(self) -> None:
            self.scan_reasons = []
            self.acquire_calls = 0
            self.release_calls = 0

        async def scan_and_reap_expired(self, *, reason: str):
            self.scan_reasons.append(reason)
            return {
                "reason": reason,
                "reclaimed_count": 1,
                "cleanup_mode": "fencing_epoch",
                "lineage_reaped_count": 1,
                "fencing_epoch": 3,
            }

        async def acquire(self, **kwargs):
            self.acquire_calls += 1
            return LeaseHandle(
                lease_id="lease-ws26",
                owner_id=str(kwargs.get("owner_id") or "owner"),
                job_id=str(kwargs.get("job_id") or "job"),
                fencing_epoch=7,
                expires_at=9999999999.0,
                ttl_seconds=10.0,
            )

        async def renew(self, handle: LeaseHandle):
            return handle

        async def release(self, handle: LeaseHandle):
            self.release_calls += 1
            return True

    manager = DummyMutexManager()

    async def _execute_ok(call: dict, session_id: str) -> dict:
        return {
            "status": "success",
            "service_name": "native",
            "tool_name": "run_cmd",
            "result": "ok",
            "narrative_summary": "ok",
            "display_preview": "ok",
        }

    monkeypatch.setattr(tool_loop, "get_global_mutex_manager", lambda: manager)
    monkeypatch.setattr(tool_loop, "_execute_single_tool_call", _execute_ok)

    call = {
        "agentType": "native",
        "tool_name": "run_cmd",
        "command": "npm install",
    }
    result = asyncio.run(
        tool_loop._execute_tool_call_with_retry(
            call,
            "sess-mutex-scavenge",
            semaphore=asyncio.Semaphore(1),
            retry_failed=True,
            max_retries=0,
            retry_backoff_seconds=0.0,
        )
    )

    assert manager.acquire_calls == 1
    assert manager.release_calls == 1
    assert manager.scan_reasons
    assert manager.scan_reasons[0].startswith("tool_call_pre_acquire:")
    assert call.get("_fencing_epoch") == 7
    assert result["status"] == "success"
    assert isinstance(result.get("mutex_scavenge_report"), dict)
    assert int(result["mutex_scavenge_report"].get("reclaimed_count") or 0) == 1


def test_global_mutex_pre_acquire_scavenger_scan_error_is_non_blocking(monkeypatch):
    class DummyMutexManager:
        def __init__(self) -> None:
            self.acquire_calls = 0
            self.release_calls = 0

        async def scan_and_reap_expired(self, *, reason: str):
            raise RuntimeError("scan_failed")

        async def acquire(self, **kwargs):
            self.acquire_calls += 1
            return LeaseHandle(
                lease_id="lease-ws26-scan-error",
                owner_id=str(kwargs.get("owner_id") or "owner"),
                job_id=str(kwargs.get("job_id") or "job"),
                fencing_epoch=5,
                expires_at=9999999999.0,
                ttl_seconds=10.0,
            )

        async def renew(self, handle: LeaseHandle):
            return handle

        async def release(self, handle: LeaseHandle):
            self.release_calls += 1
            return True

    manager = DummyMutexManager()

    async def _execute_ok(call: dict, session_id: str) -> dict:
        return {
            "status": "success",
            "service_name": "native",
            "tool_name": "run_cmd",
            "result": "ok",
            "narrative_summary": "ok",
            "display_preview": "ok",
        }

    monkeypatch.setattr(tool_loop, "get_global_mutex_manager", lambda: manager)
    monkeypatch.setattr(tool_loop, "_execute_single_tool_call", _execute_ok)

    call = {
        "agentType": "native",
        "tool_name": "run_cmd",
        "command": "npm install",
    }
    result = asyncio.run(
        tool_loop._execute_tool_call_with_retry(
            call,
            "sess-mutex-scan-error",
            semaphore=asyncio.Semaphore(1),
            retry_failed=True,
            max_retries=0,
            retry_backoff_seconds=0.0,
        )
    )

    assert manager.acquire_calls == 1
    assert manager.release_calls == 1
    assert result["status"] == "success"
    assert isinstance(result.get("mutex_scavenge_report"), dict)
    assert result["mutex_scavenge_report"].get("cleanup_mode") == "scan_error"
    assert result["mutex_scavenge_report"].get("scan_error") == "RuntimeError"


def _workspace_conflict_result(ticket: str) -> dict:
    detail = (
        "workspace transaction failed "
        f"(clean_state=False, recovery_ticket=rcv-1, conflict_ticket={ticket}, backoff_ms=120): "
        "conflict detected"
    )
    return {
        "status": "error",
        "service_name": "native",
        "tool_name": "workspace_txn_apply",
        "result": detail,
        "narrative_summary": detail,
        "display_preview": detail,
    }


def test_workspace_conflict_reaches_threshold_triggers_router_arbiter(monkeypatch):
    attempts = {"count": 0}

    async def _always_conflict(call: dict, session_id: str) -> dict:
        attempts["count"] += 1
        return _workspace_conflict_result("conflict_same_ticket")

    monkeypatch.setattr(tool_loop, "_execute_single_tool_call", _always_conflict)
    call = {
        "agentType": "native",
        "tool_name": "workspace_txn_apply",
        "changes": [{"path": "scratch/a.txt", "content": "x"}],
    }

    result = asyncio.run(
        tool_loop._execute_tool_call_with_retry(
            call,
            "sess-router-threshold",
            semaphore=asyncio.Semaphore(1),
            retry_failed=True,
            max_retries=8,
            retry_backoff_seconds=0.0,
        )
    )

    assert attempts["count"] == 3
    assert result["status"] == "error"
    assert result.get("conflict_ticket") == "conflict_same_ticket"
    assert result.get("delegate_turns") == 3
    assert result.get("freeze") is True
    assert result.get("hitl") is True
    arbiter = result.get("router_arbiter")
    assert isinstance(arbiter, dict)
    assert arbiter.get("escalated") is True
    assert arbiter.get("max_delegate_turns") == 3


def test_workspace_conflict_below_threshold_still_retries_normally(monkeypatch):
    attempts = {"count": 0}

    async def _conflict_then_success(call: dict, session_id: str) -> dict:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return _workspace_conflict_result("conflict_same_ticket")
        return {
            "status": "success",
            "service_name": "native",
            "tool_name": "workspace_txn_apply",
            "result": "ok",
            "narrative_summary": "ok",
            "display_preview": "ok",
        }

    monkeypatch.setattr(tool_loop, "_execute_single_tool_call", _conflict_then_success)
    call = {
        "agentType": "native",
        "tool_name": "workspace_txn_apply",
        "changes": [{"path": "scratch/b.txt", "content": "y"}],
    }

    result = asyncio.run(
        tool_loop._execute_tool_call_with_retry(
            call,
            "sess-router-below-threshold",
            semaphore=asyncio.Semaphore(1),
            retry_failed=True,
            max_retries=5,
            retry_backoff_seconds=0.0,
        )
    )

    assert attempts["count"] == 3
    assert result["status"] == "success"
    assert result.get("retry_attempts") == 2
    assert "router_arbiter" not in result
    assert "freeze" not in result
    assert "hitl" not in result


def test_non_conflict_error_does_not_trigger_router_arbiter(monkeypatch):
    attempts = {"count": 0}

    async def _generic_error(call: dict, session_id: str) -> dict:
        attempts["count"] += 1
        return {
            "status": "error",
            "service_name": "native",
            "tool_name": "workspace_txn_apply",
            "result": "workspace transaction failed (clean_state=False): permission denied",
            "narrative_summary": "workspace transaction failed (clean_state=False): permission denied",
            "display_preview": "workspace transaction failed (clean_state=False): permission denied",
        }

    monkeypatch.setattr(tool_loop, "_execute_single_tool_call", _generic_error)
    call = {
        "agentType": "native",
        "tool_name": "workspace_txn_apply",
        "changes": [{"path": "scratch/c.txt", "content": "z"}],
    }

    result = asyncio.run(
        tool_loop._execute_tool_call_with_retry(
            call,
            "sess-router-non-conflict",
            semaphore=asyncio.Semaphore(1),
            retry_failed=True,
            max_retries=4,
            retry_backoff_seconds=0.0,
        )
    )

    assert attempts["count"] == 5
    assert result["status"] == "error"
    assert result.get("retry_attempts") == 4
    assert "router_arbiter" not in result
    assert "freeze" not in result
    assert "hitl" not in result


def test_l1_5_prompt_slice_injection_upserts_existing_context():
    messages = [
        {"role": "system", "content": "base_system"},
        {"role": "user", "content": "hello"},
    ]

    inserted = tool_loop._inject_ephemeral_system_context(messages, "seed_context")
    assert inserted is True
    assert len(messages) == 3
    assert tool_loop._L15_SLICE_MARKER in str(messages[1].get("content", ""))
    assert "seed_context" in str(messages[1].get("content", ""))

    unchanged = tool_loop._inject_ephemeral_system_context(messages, "seed_context")
    assert unchanged is False
    assert len(messages) == 3

    replaced = tool_loop._inject_ephemeral_system_context(messages, "execution_context")
    assert replaced is True
    assert len(messages) == 3
    assert "execution_context" in str(messages[1].get("content", ""))
    assert "seed_context" not in str(messages[1].get("content", ""))


def test_seed_contract_upgrades_to_execution_and_binds_mutating_calls():
    contract_state = tool_loop._build_seed_contract_state(
        session_id="sess-core-contract",
        latest_user_request="请修改 API 并补回归测试",
    )
    assert isinstance(contract_state, dict)
    assert contract_state["stage"] == "seed"
    assert contract_state["seed_contract_checksum"]

    actionable_calls = [
        {
            "agentType": "native",
            "tool_name": "write_file",
            "path": "a.txt",
            "content": "x",
        },
        {
            "agentType": "native",
            "tool_name": "read_file",
            "path": "a.txt",
        },
    ]
    upgraded = tool_loop._upgrade_seed_to_execution_contract_state(
        contract_state=contract_state,
        actionable_calls=actionable_calls,
        round_num=2,
        elapsed_ms=123.0,
    )
    assert isinstance(upgraded, dict)
    assert upgraded["stage"] == "execution"
    assert upgraded["execution_contract_id"]
    assert upgraded["execution_contract_checksum"]
    assert upgraded["contract_upgrade_latency_ms"] == 123.0

    tool_loop._bind_execution_contract_to_calls(actionable_calls, contract_state=upgraded)

    write_call = actionable_calls[0]
    read_call = actionable_calls[1]
    assert write_call.get("contract_id") == upgraded["execution_contract_id"]
    assert write_call.get("contract_checksum") == upgraded["execution_contract_checksum"]
    assert read_call.get("contract_id") is None
    assert read_call.get("contract_checksum") is None

    # all calls keep observability metadata
    assert write_call.get("_contract_stage") == "execution"
    assert read_call.get("_contract_stage") == "execution"
