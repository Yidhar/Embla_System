from __future__ import annotations

import json
from pathlib import Path

from core.security.audit_ledger import AuditLedger


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_audit_ledger_hash_chain_happy_path(tmp_path: Path) -> None:
    ledger_path = tmp_path / "audit_ledger.jsonl"
    ledger = AuditLedger(ledger_file=ledger_path, signing_key="test-signing-key")

    first = ledger.append_record(
        record_type="change_proposed",
        change_id="chg_001",
        scope="core",
        risk_level="high",
        requested_by="agent-runtime",
        approved_by="human-ops",
        approval_ticket="CAB-001",
        evidence_refs=["scratch/reports/proposal_001.json"],
        payload={"summary": "introduce guardrail"},
    )
    second = ledger.append_record(
        record_type="change_promoted",
        change_id="chg_001",
        scope="core",
        risk_level="high",
        requested_by="agent-runtime",
        approved_by="human-ops",
        approval_ticket="CAB-001",
        evidence_refs=["scratch/reports/release_001.json"],
        payload={"result": "passed"},
    )

    assert first.prev_ledger_hash == "GENESIS"
    assert second.prev_ledger_hash == first.ledger_hash

    verify = ledger.verify_chain()
    assert verify.passed is True
    assert verify.checked_count == 2
    assert verify.errors == []


def test_audit_ledger_detects_tampering(tmp_path: Path) -> None:
    ledger_path = tmp_path / "audit_ledger_tampered.jsonl"
    ledger = AuditLedger(ledger_file=ledger_path)

    ledger.append_record(
        record_type="change_proposed",
        change_id="chg_002",
        scope="policy",
        risk_level="medium",
        requested_by="agent-runtime",
        payload={"before": "A", "after": "B"},
    )
    ledger.append_record(
        record_type="change_promoted",
        change_id="chg_002",
        scope="policy",
        risk_level="medium",
        requested_by="agent-runtime",
        approved_by="human-ops",
        approval_ticket="CAB-002",
    )

    lines = _read_lines(ledger_path)
    assert len(lines) == 2

    first_payload = json.loads(lines[0])
    first_payload["payload"]["after"] = "C"  # tamper payload without recomputing hash
    lines[0] = json.dumps(first_payload, ensure_ascii=False)
    ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    verify = ledger.verify_chain()
    assert verify.passed is False
    assert verify.checked_count == 2
    assert any("ledger_hash mismatch" in item for item in verify.errors)
