"""WS18-007 DNA change audit and approval workflow tests."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest

from system.dna_change_audit import DNAChangeAuditLedger


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_dna_change_audit_full_approval_flow_is_traceable() -> None:
    case_root = _make_case_root("test_dna_change_audit_ws18_007")
    try:
        ledger = DNAChangeAuditLedger(ledger_file=case_root / "dna_change_audit.jsonl")
        change_id = ledger.request_change(
            file_path="system/prompts/tool_dispatch_prompt.md",
            old_hash="sha256_old",
            new_hash="sha256_new",
            requested_by="agent-security",
            request_ticket="CHG-2026-0201",
            notes="tighten command policy rule",
        )
        ledger.approve_change(
            change_id=change_id,
            approved_by="ops-lead",
            approval_ticket="CAB-2026-1001",
            notes="approved in CAB",
        )
        ledger.mark_applied(change_id=change_id, applied_by="release-bot", notes="rolled out to prod")

        report = ledger.build_tracking_report()
        assert report["total_changes"] == 1
        assert report["by_status"] == {"applied": 1}

        change = report["changes"][0]
        assert change["change_id"] == change_id
        assert change["requested_by"] == "agent-security"
        assert change["request_ticket"] == "CHG-2026-0201"
        assert change["approved_by"] == "ops-lead"
        assert change["approval_ticket"] == "CAB-2026-1001"
        assert change["applied_by"] == "release-bot"
        assert change["status"] == "applied"

        events = ledger.list_events()
        assert [event["event"] for event in events] == ["change_requested", "change_approved", "change_applied"]

        report_path = ledger.write_tracking_report(output_file=case_root / "reports" / "dna_tracking_report.json")
        exported = json.loads(report_path.read_text(encoding="utf-8"))
        assert exported["total_changes"] == 1
        assert exported["changes"][0]["change_id"] == change_id
    finally:
        _cleanup_case_root(case_root)


def test_dna_change_audit_rejected_flow_keeps_ticket_and_owner() -> None:
    case_root = _make_case_root("test_dna_change_audit_ws18_007")
    try:
        ledger = DNAChangeAuditLedger(ledger_file=case_root / "dna_change_audit.jsonl")
        change_id = ledger.request_change(
            file_path="system/prompts/conversation_style_prompt.md",
            old_hash="hash_a",
            new_hash="hash_b",
            requested_by="agent-a",
            request_ticket="CHG-2026-0202",
            notes="adjust style constraints",
        )
        ledger.reject_change(
            change_id=change_id,
            rejected_by="security-reviewer",
            rejection_ticket="SEC-REJECT-2026-09",
            notes="missing blast radius assessment",
        )

        report = ledger.build_tracking_report()
        assert report["by_status"] == {"rejected": 1}
        change = report["changes"][0]
        assert change["status"] == "rejected"
        assert change["requested_by"] == "agent-a"
        assert change["request_ticket"] == "CHG-2026-0202"
        assert change["rejected_by"] == "security-reviewer"
        assert change["rejection_ticket"] == "SEC-REJECT-2026-09"
    finally:
        _cleanup_case_root(case_root)


def test_dna_change_audit_enforces_tickets_and_state_transitions() -> None:
    case_root = _make_case_root("test_dna_change_audit_ws18_007")
    try:
        ledger = DNAChangeAuditLedger(ledger_file=case_root / "dna_change_audit.jsonl")

        with pytest.raises(ValueError, match="request_ticket is required"):
            ledger.request_change(
                file_path="system/prompts/agentic_tool_prompt.md",
                old_hash="hash_1",
                new_hash="hash_2",
                requested_by="agent-a",
                request_ticket="",
            )

        change_id = ledger.request_change(
            file_path="system/prompts/agentic_tool_prompt.md",
            old_hash="hash_1",
            new_hash="hash_2",
            requested_by="agent-a",
            request_ticket="CHG-2026-0203",
        )
        with pytest.raises(ValueError, match="approval_ticket is required"):
            ledger.approve_change(change_id=change_id, approved_by="ops", approval_ticket="")
        with pytest.raises(ValueError, match="not approved"):
            ledger.mark_applied(change_id=change_id, applied_by="release-bot")

        ledger.approve_change(change_id=change_id, approved_by="ops", approval_ticket="CAB-2026-1002")
        ledger.mark_applied(change_id=change_id, applied_by="release-bot")

        with pytest.raises(ValueError, match="is not pending"):
            ledger.approve_change(change_id=change_id, approved_by="ops", approval_ticket="CAB-2026-1003")
        with pytest.raises(ValueError, match="not found"):
            ledger.reject_change(change_id="dna_change_missing", rejected_by="ops", rejection_ticket="SEC-404")
    finally:
        _cleanup_case_root(case_root)
