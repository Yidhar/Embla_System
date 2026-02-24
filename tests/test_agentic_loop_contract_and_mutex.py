"""Agentic loop guard helper tests (WS13-002 + WS14-003 signal path)."""

from __future__ import annotations

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
