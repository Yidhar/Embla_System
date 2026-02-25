"""Agentic loop guard helper tests (WS13-002 + WS14-003 signal path)."""

from __future__ import annotations

import asyncio

import apiserver.agentic_tool_loop as tool_loop
from apiserver.agentic_tool_loop import _apply_parallel_contract_gate, _requires_global_mutex
from system.global_mutex import LeaseHandle


def test_contract_gate_downgrades_parallel_mutating_calls():
    calls = [
        {"agentType": "native", "tool_name": "write_file", "path": "a.txt", "content": "a"},
        {"agentType": "native", "tool_name": "workspace_txn_apply", "changes": [{"path": "b.txt", "content": "b"}]},
    ]
    messages, force_serial = _apply_parallel_contract_gate(calls)
    assert force_serial is True
    assert messages
    assert all(bool(call.get("_force_serial")) for call in calls)


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
    messages, force_serial = _apply_parallel_contract_gate(calls)
    assert force_serial is False
    assert messages == []


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
    return {
        "status": "error",
        "service_name": "native",
        "tool_name": "workspace_txn_apply",
        "result": (
            "workspace transaction failed "
            f"(clean_state=False, recovery_ticket=rcv-1, conflict_ticket={ticket}, backoff_ms=120): "
            "conflict detected"
        ),
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
