"""WS18-005 loop detector + cost breaker guard."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, Optional, Protocol, Tuple


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventEmitter(Protocol):
    def emit(self, event_type: str, payload: Dict[str, Any], **kwargs: Any) -> None:
        ...


@dataclass(frozen=True)
class LoopCostThresholds:
    consecutive_error_limit: int = 5
    tool_call_limit_per_minute: int = 10
    task_cost_limit: float = 5.0
    daily_cost_limit: float = 50.0
    loop_window_seconds: int = 60


@dataclass(frozen=True)
class LoopCostAction:
    action: str
    reason: str
    level: str
    task_id: str
    tool_name: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class LoopCostGuard:
    """Detect repeated failure loops and budget overruns for hard stop decisions."""

    def __init__(
        self,
        *,
        thresholds: Optional[LoopCostThresholds] = None,
        event_emitter: Optional[EventEmitter] = None,
        now_fn: Optional[callable] = None,
    ) -> None:
        self.thresholds = thresholds or LoopCostThresholds()
        self.event_emitter = event_emitter
        self.now_fn = now_fn or time.time

        self._task_consecutive_errors: Dict[str, int] = defaultdict(int)
        self._task_cost: Dict[str, float] = defaultdict(float)
        self._daily_cost: float = 0.0
        self._task_tool_calls: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)

    def observe_tool_call(
        self,
        *,
        task_id: str,
        tool_name: str,
        success: bool,
        call_cost: float = 0.0,
    ) -> Optional[LoopCostAction]:
        tid = str(task_id or "unknown_task")
        tool = str(tool_name or "unknown_tool")
        cost = max(0.0, float(call_cost or 0.0))
        now = float(self.now_fn())

        # Track per-tool call pressure window for loop detection.
        key = (tid, tool)
        queue = self._task_tool_calls[key]
        queue.append(now)
        self._trim_window(queue, now=now)

        # Track error streak.
        if success:
            self._task_consecutive_errors[tid] = 0
        else:
            self._task_consecutive_errors[tid] += 1

        # Track budget.
        self._task_cost[tid] += cost
        self._daily_cost += cost

        action = self._evaluate(tid=tid, tool=tool, call_count=len(queue))
        if action is not None:
            self._emit(action)
        return action

    def snapshot(self) -> Dict[str, Any]:
        return {
            "ts": _utc_iso(),
            "task_consecutive_errors": dict(self._task_consecutive_errors),
            "task_cost": {k: round(v, 6) for k, v in self._task_cost.items()},
            "daily_cost": round(self._daily_cost, 6),
        }

    def _evaluate(self, *, tid: str, tool: str, call_count: int) -> Optional[LoopCostAction]:
        if self._task_consecutive_errors.get(tid, 0) >= self.thresholds.consecutive_error_limit:
            return LoopCostAction(
                action="kill_agent_loop",
                reason="consecutive_error_limit_exceeded",
                level="critical",
                task_id=tid,
                tool_name=tool,
                details={
                    "consecutive_errors": self._task_consecutive_errors.get(tid, 0),
                    "threshold": self.thresholds.consecutive_error_limit,
                },
            )

        if call_count > self.thresholds.tool_call_limit_per_minute:
            return LoopCostAction(
                action="kill_agent_loop",
                reason="tool_call_rate_limit_exceeded",
                level="critical",
                task_id=tid,
                tool_name=tool,
                details={
                    "tool_call_count_in_window": call_count,
                    "window_seconds": self.thresholds.loop_window_seconds,
                    "threshold": self.thresholds.tool_call_limit_per_minute,
                },
            )

        task_cost = self._task_cost.get(tid, 0.0)
        if task_cost > self.thresholds.task_cost_limit:
            return LoopCostAction(
                action="terminate_task_budget_exceeded",
                reason="task_cost_limit_exceeded",
                level="critical",
                task_id=tid,
                tool_name=tool,
                details={"task_cost": round(task_cost, 6), "threshold": self.thresholds.task_cost_limit},
            )

        if self._daily_cost > self.thresholds.daily_cost_limit:
            return LoopCostAction(
                action="freeze_noncritical_budget",
                reason="daily_cost_limit_exceeded",
                level="warn",
                task_id=tid,
                tool_name=tool,
                details={"daily_cost": round(self._daily_cost, 6), "threshold": self.thresholds.daily_cost_limit},
            )
        return None

    def _trim_window(self, queue: Deque[float], *, now: float) -> None:
        cutoff = now - float(self.thresholds.loop_window_seconds)
        while queue and queue[0] < cutoff:
            queue.popleft()

    def _emit(self, action: LoopCostAction) -> None:
        if self.event_emitter is None:
            return
        event_type = {
            "consecutive_error_limit_exceeded": "agent.loop.detected",
            "tool_call_rate_limit_exceeded": "agent.loop.detected",
            "task_cost_limit_exceeded": "budget.task.exceeded",
            "daily_cost_limit_exceeded": "budget.daily.exhausted",
        }.get(action.reason, "watchdog.loop_cost.action")
        try:
            self.event_emitter.emit(event_type, action.to_dict())
        except Exception:
            return
