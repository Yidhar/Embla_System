from __future__ import annotations

import asyncio

import apiserver.agentic_tool_loop as tool_loop


def test_inject_call_context_sets_default_approval_hook_for_write_repo() -> None:
    call = {
        "agentType": "native",
        "tool_name": "write_file",
        "path": "scratch/ws10_005.txt",
        "content": "hello",
    }

    tool_loop._inject_call_context_metadata(
        call,
        call_id="call_ws10_005_1",
        trace_id="trace_ws10_005_1",
        session_id="sess_ws10_005_1",
    )

    assert call["_risk_level"] == "write_repo"
    assert call["_approval_required"] is True
    assert call["_approval_policy"] == "on-request"
    assert call["approvalPolicy"] == "on-request"


def test_risk_gate_blocks_when_high_risk_policy_is_disabled(monkeypatch) -> None:
    calls = {"count": 0}

    async def _fake_execute(call: dict, session_id: str) -> dict:
        _ = (call, session_id)
        calls["count"] += 1
        return {
            "status": "success",
            "service_name": "native",
            "tool_name": "write_file",
            "result": "ok",
        }

    monkeypatch.setattr(tool_loop, "_execute_single_tool_call", _fake_execute)

    call = {
        "agentType": "native",
        "tool_name": "write_file",
        "path": "scratch/ws10_005_2.txt",
        "content": "content",
        "_risk_level": "write_repo",
        "approvalPolicy": "never",
    }
    row = asyncio.run(
        tool_loop._execute_tool_call_with_retry(
            call,
            "sess_ws10_005_2",
            semaphore=asyncio.Semaphore(1),
            retry_failed=True,
            max_retries=2,
            retry_backoff_seconds=0.0,
        )
    )

    assert calls["count"] == 0
    assert row["status"] == "error"
    assert row["error_code"] == "E_RISK_POLICY_BLOCKED"
    assert isinstance(row.get("tool_receipt"), dict)
    assert row["tool_receipt"]["approval"]["required"] is True
    assert row["tool_receipt"]["approval"]["policy"] == "never"


def test_risk_gate_blocks_secrets_without_explicit_approval(monkeypatch) -> None:
    calls = {"count": 0}

    async def _fake_execute(call: dict, session_id: str) -> dict:
        _ = (call, session_id)
        calls["count"] += 1
        return {
            "status": "success",
            "service_name": "mcp",
            "tool_name": "get_secret",
            "result": "ok",
        }

    monkeypatch.setattr(tool_loop, "_execute_single_tool_call", _fake_execute)

    call = {
        "agentType": "mcp",
        "service_name": "vault",
        "tool_name": "get_secret",
        "_risk_level": "secrets",
    }
    row = asyncio.run(
        tool_loop._execute_tool_call_with_retry(
            call,
            "sess_ws10_005_3",
            semaphore=asyncio.Semaphore(1),
            retry_failed=False,
            max_retries=0,
            retry_backoff_seconds=0.0,
        )
    )

    assert calls["count"] == 0
    assert row["status"] == "error"
    assert row["error_code"] == "E_RISK_APPROVAL_REQUIRED"
    assert "requires explicit human approval" in str(row.get("result", ""))


def test_risk_gate_allows_secrets_with_explicit_approval(monkeypatch) -> None:
    calls = {"count": 0}

    async def _fake_execute(call: dict, session_id: str) -> dict:
        _ = (call, session_id)
        calls["count"] += 1
        return {
            "status": "success",
            "service_name": "mcp",
            "tool_name": "get_secret",
            "result": "ok",
        }

    monkeypatch.setattr(tool_loop, "_execute_single_tool_call", _fake_execute)

    call = {
        "agentType": "mcp",
        "service_name": "vault",
        "tool_name": "get_secret",
        "_risk_level": "secrets",
        "approvalPolicy": "always",
        "approval_granted": True,
    }
    row = asyncio.run(
        tool_loop._execute_tool_call_with_retry(
            call,
            "sess_ws10_005_4",
            semaphore=asyncio.Semaphore(1),
            retry_failed=False,
            max_retries=0,
            retry_backoff_seconds=0.0,
        )
    )

    assert calls["count"] == 1
    assert row["status"] == "success"
    assert isinstance(row.get("tool_receipt"), dict)
    assert row["tool_receipt"]["approval"]["required"] is True
    assert row["tool_receipt"]["approval"]["policy"] == "always"
    assert row["tool_receipt"]["approval"]["granted"] is True
