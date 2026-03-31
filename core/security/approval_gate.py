"""Dual-lane approval gate for framework-maintenance changes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Set


@dataclass(frozen=True)
class ApprovalRequest:
    scope: str
    risk_level: str
    requested_by: str
    approval_ticket: str = ""
    lane: str = "task_execution"


@dataclass(frozen=True)
class ApprovalDecision:
    approved: bool
    reason_code: str
    reason_text: str
    requires_human_approval: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approved": self.approved,
            "reason_code": self.reason_code,
            "reason_text": self.reason_text,
            "requires_human_approval": self.requires_human_approval,
        }


class ApprovalGate:
    """Evaluate whether a request can cross into maintenance lane."""

    def __init__(
        self,
        *,
        approval_required_scopes: Set[str] | None = None,
        strict_maintenance_lane: bool = True,
    ) -> None:
        self.approval_required_scopes = {
            str(item).strip().lower()
            for item in (approval_required_scopes or {"core", "policy", "prompt_dna", "tools_registry"})
            if str(item).strip()
        }
        self.strict_maintenance_lane = bool(strict_maintenance_lane)

    def evaluate(self, request: ApprovalRequest) -> ApprovalDecision:
        scope = str(request.scope or "").strip().lower()
        lane = str(request.lane or "").strip().lower()
        has_ticket = bool(str(request.approval_ticket or "").strip())

        requires_human = scope in self.approval_required_scopes or lane == "framework_maintenance"

        if self.strict_maintenance_lane and lane == "framework_maintenance" and not has_ticket:
            return ApprovalDecision(
                approved=False,
                reason_code="APPROVAL_TICKET_REQUIRED",
                reason_text="framework maintenance lane requires an approval ticket",
                requires_human_approval=True,
            )

        if requires_human and not has_ticket:
            return ApprovalDecision(
                approved=False,
                reason_code="APPROVAL_TICKET_REQUIRED",
                reason_text=f"scope '{scope or 'unknown'}' requires human approval",
                requires_human_approval=True,
            )

        if requires_human:
            return ApprovalDecision(
                approved=True,
                reason_code="APPROVED_WITH_TICKET",
                reason_text="human approval ticket present",
                requires_human_approval=True,
            )

        return ApprovalDecision(
            approved=True,
            reason_code="AUTO_APPROVED_LOW_RISK",
            reason_text="request stays in task lane and scope is low risk",
            requires_human_approval=False,
        )
