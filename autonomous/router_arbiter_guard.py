"""WS19-008 router arbiter guard (delegate cap + freeze + HITL escalation)."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from system.router_arbiter import MAX_DELEGATE_TURNS, evaluate_workspace_conflict_retry


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class RouterArbiterDecision:
    decision_id: str
    created_at: str
    task_id: str
    conflict_ticket: str
    delegate_turns: int
    max_delegate_turns: int
    freeze: bool
    hitl: bool
    escalated: bool
    reason: str
    conflict_points: List[str]
    candidate_decisions: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class _TaskArbiterState:
    conflict_ticket: str = ""
    delegate_turns: int = 0
    freeze: bool = False
    hitl: bool = False
    escalated: bool = False
    history: List[Dict[str, Any]] = field(default_factory=list)


class RouterArbiterGuard:
    """Track repeated delegate conflicts and enforce freeze/HITL escalation."""

    def __init__(
        self,
        *,
        max_delegate_turns: int = MAX_DELEGATE_TURNS,
        history_limit: int = 20,
        decision_log: Optional[Path] = None,
    ) -> None:
        self.max_delegate_turns = max(1, int(max_delegate_turns))
        self.history_limit = max(5, int(history_limit))
        self.decision_log = Path(decision_log) if decision_log else None
        if self.decision_log is not None:
            self.decision_log.parent.mkdir(parents=True, exist_ok=True)
        self._states: Dict[str, _TaskArbiterState] = {}
        self._lock = threading.Lock()

    def register_delegate_turn(
        self,
        *,
        task_id: str,
        from_agent: str,
        to_agent: str,
        reason: str,
        conflict_ticket: str = "",
        candidate_decisions: Optional[List[str]] = None,
    ) -> RouterArbiterDecision:
        task_key = str(task_id or "").strip() or "unknown_task"
        ticket = str(conflict_ticket or "").strip()
        reason_text = str(reason or "").strip() or "router_delegate_turn"
        candidates = [str(item) for item in (candidate_decisions or []) if str(item).strip()]

        with self._lock:
            state = self._states.setdefault(task_key, _TaskArbiterState())
            if ticket and ticket == state.conflict_ticket:
                delegate_turns = state.delegate_turns + 1
            elif not ticket and state.conflict_ticket:
                delegate_turns = state.delegate_turns + 1
            else:
                delegate_turns = 1

            escalated = delegate_turns >= self.max_delegate_turns
            freeze = escalated
            hitl = escalated
            if escalated:
                reason_text = "router_delegate_threshold_exceeded"

            history_row = {
                "ts": _utc_iso(),
                "task_id": task_key,
                "from_agent": str(from_agent or ""),
                "to_agent": str(to_agent or ""),
                "reason": reason_text,
                "conflict_ticket": ticket,
                "candidate_decisions": candidates,
            }
            state.history.append(history_row)
            if len(state.history) > self.history_limit:
                state.history = state.history[-self.history_limit :]
            state.conflict_ticket = ticket
            state.delegate_turns = delegate_turns
            state.freeze = freeze
            state.hitl = hitl
            state.escalated = escalated

            decision = RouterArbiterDecision(
                decision_id=f"arbiter_{uuid.uuid4().hex[:12]}",
                created_at=_utc_iso(),
                task_id=task_key,
                conflict_ticket=ticket,
                delegate_turns=delegate_turns,
                max_delegate_turns=self.max_delegate_turns,
                freeze=freeze,
                hitl=hitl,
                escalated=escalated,
                reason=reason_text,
                conflict_points=self._collect_conflict_points(state.history),
                candidate_decisions=self._collect_candidate_decisions(state.history),
            )
            self._append_decision_log(decision=decision, history_row=history_row)
            return decision

    def observe_workspace_conflict(
        self,
        *,
        task_id: str,
        call: Dict[str, Any],
        result: Dict[str, Any],
        from_agent: str = "agent",
        to_agent: str = "agent",
    ) -> Optional[RouterArbiterDecision]:
        task_key = str(task_id or "").strip() or "unknown_task"
        with self._lock:
            state = self._states.setdefault(task_key, _TaskArbiterState())
            previous_ticket = state.conflict_ticket
            previous_turns = state.delegate_turns

        signal = evaluate_workspace_conflict_retry(
            call,
            result,
            previous_conflict_ticket=previous_ticket,
            previous_delegate_turns=previous_turns,
            max_delegate_turns=self.max_delegate_turns,
        )
        if signal is None:
            return None
        return self.register_delegate_turn(
            task_id=task_key,
            from_agent=from_agent,
            to_agent=to_agent,
            reason=str(signal.reason or ""),
            conflict_ticket=str(signal.conflict_ticket or ""),
        )

    def should_freeze_task(self, task_id: str) -> bool:
        state = self._states.get(str(task_id or "").strip())
        return bool(state and state.freeze)

    def build_conflict_summary(self, task_id: str) -> Dict[str, Any]:
        task_key = str(task_id or "").strip() or "unknown_task"
        state = self._states.get(task_key)
        if state is None:
            return {
                "task_id": task_key,
                "delegate_turns": 0,
                "conflict_ticket": "",
                "freeze": False,
                "hitl": False,
                "conflict_points": [],
                "candidate_decisions": [],
            }
        return {
            "task_id": task_key,
            "delegate_turns": state.delegate_turns,
            "conflict_ticket": state.conflict_ticket,
            "freeze": state.freeze,
            "hitl": state.hitl,
            "conflict_points": self._collect_conflict_points(state.history),
            "candidate_decisions": self._collect_candidate_decisions(state.history),
        }

    def reset_task(self, task_id: str) -> None:
        self._states.pop(str(task_id or "").strip(), None)

    @staticmethod
    def _collect_conflict_points(history: List[Dict[str, Any]]) -> List[str]:
        points: List[str] = []
        for row in history:
            reason = str(row.get("reason") or "").strip()
            if reason and reason not in points:
                points.append(reason)
        return points

    @staticmethod
    def _collect_candidate_decisions(history: List[Dict[str, Any]]) -> List[str]:
        decisions: List[str] = []
        for row in history:
            for candidate in row.get("candidate_decisions", []) or []:
                text = str(candidate or "").strip()
                if text and text not in decisions:
                    decisions.append(text)
        return decisions

    def _append_decision_log(self, *, decision: RouterArbiterDecision, history_row: Dict[str, Any]) -> None:
        if self.decision_log is None:
            return
        row = {"ts": _utc_iso(), "decision": decision.to_dict(), "history_row": history_row}
        line = json.dumps(row, ensure_ascii=False)
        with self.decision_log.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


__all__ = ["RouterArbiterDecision", "RouterArbiterGuard"]
