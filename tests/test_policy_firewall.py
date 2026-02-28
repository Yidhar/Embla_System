"""Policy firewall tests (WS14-001 + WS14-009)."""

from __future__ import annotations

from pathlib import Path

from system.policy_firewall import PolicyFirewall


def test_firewall_blocks_obfuscation_and_audits():
    base = Path("scratch/test_policy_firewall")
    base.mkdir(parents=True, exist_ok=True)
    audit_file = base / "pfw_audit.jsonl"
    if audit_file.exists():
        audit_file.unlink()
    fw = PolicyFirewall(audit_file=audit_file)

    decision = fw.validate_native_call(
        "run_cmd",
        {
            "tool_name": "run_cmd",
            "command": "x='r'; y='m'; $x$y -rf /",
        },
    )
    assert decision.allowed is False
    assert decision.rule_id in {"OBFUSCATION_VAR_CONCAT", "PROGRAM_NOT_ALLOWLISTED"}
    assert decision.audit_id
    assert audit_file.exists() is True
    assert decision.audit_id in audit_file.read_text(encoding="utf-8")


def test_firewall_blocks_invalid_argv_schema():
    base = Path("scratch/test_policy_firewall")
    base.mkdir(parents=True, exist_ok=True)
    fw = PolicyFirewall(audit_file=base / "pfw_audit_2.jsonl")
    decision = fw.validate_native_call(
        "workspace_txn_apply",
        {
            "tool_name": "workspace_txn_apply",
            "changes": [],
            "unexpected_field": "boom",
        },
    )
    assert decision.allowed is False
    assert decision.rule_id == "INVALID_ARGV_SCHEMA"


def test_firewall_allows_known_safe_command():
    base = Path("scratch/test_policy_firewall")
    base.mkdir(parents=True, exist_ok=True)
    fw = PolicyFirewall(audit_file=base / "pfw_audit_3.jsonl")
    decision = fw.validate_native_call(
        "run_cmd",
        {
            "tool_name": "run_cmd",
            "command": "git status --short",
        },
    )
    assert decision.allowed is True


def test_firewall_allows_run_cmd_with_approval_fields():
    base = Path("scratch/test_policy_firewall")
    base.mkdir(parents=True, exist_ok=True)
    fw = PolicyFirewall(audit_file=base / "pfw_audit_4.jsonl")
    decision = fw.validate_native_call(
        "run_cmd",
        {
            "tool_name": "run_cmd",
            "command": "git status --short",
            "approvalPolicy": "on-request",
            "approval_granted": True,
        },
    )
    assert decision.allowed is True


def test_firewall_keeps_run_cmd_strict_unknown_nonempty_field():
    base = Path("scratch/test_policy_firewall")
    base.mkdir(parents=True, exist_ok=True)
    fw = PolicyFirewall(audit_file=base / "pfw_audit_5.jsonl")
    decision = fw.validate_native_call(
        "run_cmd",
        {
            "tool_name": "run_cmd",
            "command": "echo strict",
            "mode": "preview",
        },
    )
    assert decision.allowed is False
    assert decision.rule_id == "INVALID_ARGV_SCHEMA"
