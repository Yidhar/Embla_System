from __future__ import annotations

from core.security.approval_gate import ApprovalGate, ApprovalRequest


def test_approval_gate_denies_framework_lane_without_ticket() -> None:
    gate = ApprovalGate()
    request = ApprovalRequest(
        scope="core",
        risk_level="high",
        requested_by="agent-runtime",
        lane="framework_maintenance",
        approval_ticket="",
    )

    decision = gate.evaluate(request)
    assert decision.approved is False
    assert decision.requires_human_approval is True
    assert decision.reason_code == "APPROVAL_TICKET_REQUIRED"


def test_approval_gate_allows_framework_lane_with_ticket() -> None:
    gate = ApprovalGate()
    request = ApprovalRequest(
        scope="core",
        risk_level="high",
        requested_by="agent-runtime",
        lane="framework_maintenance",
        approval_ticket="CAB-2026-001",
    )

    decision = gate.evaluate(request)
    assert decision.approved is True
    assert decision.requires_human_approval is True
    assert decision.reason_code == "APPROVED_WITH_TICKET"


def test_approval_gate_auto_approves_low_risk_task_lane() -> None:
    gate = ApprovalGate()
    request = ApprovalRequest(
        scope="workspace",
        risk_level="low",
        requested_by="agent-runtime",
        lane="task_execution",
    )

    decision = gate.evaluate(request)
    assert decision.approved is True
    assert decision.requires_human_approval is False
    assert decision.reason_code == "AUTO_APPROVED_LOW_RISK"
