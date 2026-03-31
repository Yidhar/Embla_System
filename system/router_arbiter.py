"""Router arbiter helpers for repeated workspace transaction conflicts."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, Optional

MAX_DELEGATE_TURNS = 3

_CONFLICT_TICKET_RE = re.compile(r"conflict_ticket=([A-Za-z0-9_-]+)")

_WORKSPACE_TXN_ALIASES = {"workspace_txn_apply", "txn_apply", "scaffold_apply"}


@dataclass(frozen=True)
class RouterArbiterSignal:
    """Machine-readable escalation signal for router arbitration."""

    conflict_ticket: str
    delegate_turns: int
    max_delegate_turns: int
    freeze: bool
    hitl: bool
    escalated: bool
    reason: str

    def to_payload(self) -> Dict[str, Any]:
        return {
            "reason": self.reason,
            "conflict_ticket": self.conflict_ticket,
            "delegate_turns": self.delegate_turns,
            "max_delegate_turns": self.max_delegate_turns,
            "freeze": self.freeze,
            "hitl": self.hitl,
            "escalated": self.escalated,
        }


def _extract_conflict_ticket(error_text: str) -> str:
    matched = _CONFLICT_TICKET_RE.search(error_text or "")
    if not matched:
        return ""
    return matched.group(1)


def _is_workspace_txn_conflict(call: Dict[str, Any], result: Dict[str, Any]) -> bool:
    if str(result.get("status", "")) != "error":
        return False
    if str(call.get("agentType", "")) != "native":
        return False
    tool_name = str(call.get("tool_name", ""))
    if tool_name not in _WORKSPACE_TXN_ALIASES:
        return False
    error_text = str(result.get("result", "") or "")
    lowered = error_text.lower()
    return "workspace transaction failed" in lowered and "conflict_ticket=" in error_text


def evaluate_workspace_conflict_retry(
    call: Dict[str, Any],
    result: Dict[str, Any],
    *,
    previous_conflict_ticket: str,
    previous_delegate_turns: int,
    max_delegate_turns: int = MAX_DELEGATE_TURNS,
) -> Optional[RouterArbiterSignal]:
    """Evaluate whether repeated workspace_txn conflicts should trigger freeze/HITL."""

    if not _is_workspace_txn_conflict(call, result):
        return None

    threshold = max(1, int(max_delegate_turns))
    error_text = str(result.get("result", "") or "")
    current_ticket = _extract_conflict_ticket(error_text)

    if current_ticket and current_ticket == previous_conflict_ticket:
        delegate_turns = previous_delegate_turns + 1
    elif not current_ticket and previous_conflict_ticket:
        delegate_turns = previous_delegate_turns + 1
    else:
        delegate_turns = 1

    escalated = delegate_turns >= threshold
    reason = (
        "workspace_txn_conflict_threshold_exceeded"
        if escalated
        else "workspace_txn_conflict_retry"
    )

    return RouterArbiterSignal(
        conflict_ticket=current_ticket,
        delegate_turns=delegate_turns,
        max_delegate_turns=threshold,
        freeze=escalated,
        hitl=escalated,
        escalated=escalated,
        reason=reason,
    )


__all__ = [
    "MAX_DELEGATE_TURNS",
    "RouterArbiterSignal",
    "evaluate_workspace_conflict_retry",
]
