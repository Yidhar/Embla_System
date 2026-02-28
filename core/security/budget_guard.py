"""Runtime budget guard facade for loop-cost protection and observability."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from system.loop_cost_guard import LoopCostAction, LoopCostGuard, LoopCostThresholds


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _normalize_status(action: LoopCostAction) -> str:
    if str(action.level or "").strip().lower() in {"critical", "error"}:
        return "critical"
    if str(action.level or "").strip().lower() in {"warn", "warning"}:
        return "warning"
    return "ok"


@dataclass(frozen=True)
class BudgetGuardState:
    generated_at: str
    status: str
    reason_code: str
    reason_text: str
    task_id: str
    tool_name: str
    action: str
    details: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BudgetGuardController:
    """Controller around `LoopCostGuard` that persists last decision state."""

    def __init__(
        self,
        *,
        thresholds: Optional[LoopCostThresholds] = None,
        state_file: Path = Path("scratch/runtime/budget_guard_state_ws28_028.json"),
    ) -> None:
        self.guard = LoopCostGuard(thresholds=thresholds or LoopCostThresholds())
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def observe_tool_call(
        self,
        *,
        task_id: str,
        tool_name: str,
        success: bool,
        call_cost: float = 0.0,
    ) -> Optional[Dict[str, Any]]:
        action = self.guard.observe_tool_call(
            task_id=task_id,
            tool_name=tool_name,
            success=success,
            call_cost=call_cost,
        )
        if action is None:
            return None
        return self.record_action_payload(action.to_dict())

    def record_action_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        action_reason = str(payload.get("reason") or "BUDGET_GUARD_TRIGGERED").strip()
        action_level = str(payload.get("level") or "").strip().lower()
        action_status = "critical" if action_level in {"critical", "error"} else "warning"
        state = BudgetGuardState(
            generated_at=_utc_iso(),
            status=action_status,
            reason_code=action_reason.upper(),
            reason_text=f"budget guard triggered: {action_reason}",
            task_id=str(payload.get("task_id") or ""),
            tool_name=str(payload.get("tool_name") or ""),
            action=str(payload.get("action") or ""),
            details=dict(payload.get("details") or {}),
        )
        self._write_state(state)
        return {**payload, "status": state.status, "reason_code": state.reason_code}

    def ensure_baseline_state(
        self,
        *,
        requested_by: str = "startup",
        force: bool = False,
    ) -> Dict[str, Any]:
        if self.state_file.exists() and not force:
            snapshot = self.read_state()
            snapshot["baseline_written"] = False
            return snapshot

        state = BudgetGuardState(
            generated_at=_utc_iso(),
            status="ok",
            reason_code="BUDGET_GUARD_BASELINE_READY",
            reason_text="budget guard baseline state initialized",
            task_id="",
            tool_name="",
            action="",
            details={
                "baseline": True,
                "requested_by": str(requested_by or "startup").strip() or "startup",
            },
        )
        self._write_state(state)
        return {
            **state.to_dict(),
            "state_file": _to_unix(self.state_file),
            "baseline_written": True,
            "heartbeat_age_seconds": 0.0,
            "stale_warning_seconds": 120.0,
            "stale_critical_seconds": 300.0,
        }

    def read_state(
        self,
        *,
        stale_warning_seconds: float = 120.0,
        stale_critical_seconds: float = 300.0,
    ) -> Dict[str, Any]:
        if not self.state_file.exists():
            return {
                "status": "unknown",
                "reason_code": "BUDGET_GUARD_STATE_MISSING",
                "reason_text": "budget guard state file is missing",
                "state_file": _to_unix(self.state_file),
            }
        try:
            payload = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "status": "warning",
                "reason_code": "BUDGET_GUARD_STATE_INVALID",
                "reason_text": "budget guard state payload is invalid",
                "state_file": _to_unix(self.state_file),
            }
        if not isinstance(payload, dict):
            return {
                "status": "warning",
                "reason_code": "BUDGET_GUARD_STATE_INVALID",
                "reason_text": "budget guard state payload is invalid",
                "state_file": _to_unix(self.state_file),
            }

        generated_at = str(payload.get("generated_at") or "")
        generated_ts = self._parse_iso_ts(generated_at)
        heartbeat_age_seconds = None
        if generated_ts is not None:
            heartbeat_age_seconds = max(0.0, round(time.time() - generated_ts, 3))

        status = str(payload.get("status") or "unknown").strip().lower()
        reason_code = str(payload.get("reason_code") or "")
        reason_text = str(payload.get("reason_text") or "")
        if generated_ts is None:
            status = "warning"
            reason_code = "BUDGET_GUARD_TIMESTAMP_INVALID"
            reason_text = "budget guard state timestamp is invalid"
        elif heartbeat_age_seconds is not None and heartbeat_age_seconds > float(stale_critical_seconds):
            status = "critical"
            reason_code = "BUDGET_GUARD_STATE_STALE_CRITICAL"
            reason_text = "budget guard state is stale beyond critical threshold"
        elif heartbeat_age_seconds is not None and heartbeat_age_seconds > float(stale_warning_seconds):
            status = "warning"
            reason_code = "BUDGET_GUARD_STATE_STALE_WARNING"
            reason_text = "budget guard state is stale beyond warning threshold"

        return {
            **payload,
            "status": status,
            "reason_code": reason_code,
            "reason_text": reason_text,
            "state_file": _to_unix(self.state_file),
            "heartbeat_age_seconds": heartbeat_age_seconds,
            "stale_warning_seconds": float(stale_warning_seconds),
            "stale_critical_seconds": float(stale_critical_seconds),
        }

    @staticmethod
    def _parse_iso_ts(value: str) -> Optional[float]:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            return datetime.fromisoformat(text).timestamp()
        except ValueError:
            return None

    def _write_state(self, state: BudgetGuardState) -> None:
        payload = {**state.to_dict(), "state_file": _to_unix(self.state_file)}
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


__all__ = ["BudgetGuardController", "BudgetGuardState"]
