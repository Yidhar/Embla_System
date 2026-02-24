"""Agentic loop guard helper tests (WS13-002 + WS14-003 signal path)."""

from __future__ import annotations

import asyncio

import apiserver.agentic_tool_loop as tool_loop
from apiserver.agentic_tool_loop import _apply_parallel_contract_gate, _requires_global_mutex


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
