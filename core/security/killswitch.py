"""KillSwitch controller for runtime freeze intent tracking.

This module wraps the low-level plan builder with explicit state persistence so
ops posture/incidents can reason about kill-switch activation.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from system.killswitch_guard import KillSwitchPlan, build_oob_killswitch_plan


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


@dataclass(frozen=True)
class KillSwitchState:
    generated_at: str
    status: str
    reason_code: str
    reason_text: str
    mode: str
    execution_state: str
    active: bool
    approval_ticket: str
    requested_by: str
    oob_allowlist: List[str]
    commands_count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class KillSwitchController:
    """Build/record killswitch plans and expose a stable state file."""

    def __init__(
        self,
        *,
        state_file: Path = Path("scratch/runtime/killswitch_guard_state_ws28_028.json"),
    ) -> None:
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def create_freeze_plan(
        self,
        *,
        oob_allowlist: Iterable[str],
        dns_allow: bool = True,
        requested_by: str = "runtime",
        approval_ticket: str = "",
        activate: bool = True,
    ) -> KillSwitchPlan:
        plan = build_oob_killswitch_plan(oob_allowlist=oob_allowlist, dns_allow=dns_allow)
        self._write_state(
            KillSwitchState(
                generated_at=_utc_iso(),
                status="ok",
                reason_code="KILLSWITCH_PLAN_GENERATED" if activate else "KILLSWITCH_PLAN_PREVIEWED",
                reason_text=(
                    "KillSwitch freeze plan generated; execute it out-of-band to engage."
                    if activate
                    else "KillSwitch freeze plan generated in preview mode."
                ),
                mode=plan.mode,
                execution_state="planned" if activate else "previewed",
                active=False,
                approval_ticket=str(approval_ticket or "").strip(),
                requested_by=str(requested_by or "").strip() or "runtime",
                oob_allowlist=list(plan.oob_allowlist),
                commands_count=len(list(plan.commands)),
            )
        )
        return plan

    def release(self, *, requested_by: str = "runtime", approval_ticket: str = "") -> Dict[str, Any]:
        state = KillSwitchState(
            generated_at=_utc_iso(),
            status="ok",
            reason_code="KILLSWITCH_RELEASED",
            reason_text="KillSwitch state marked as released.",
            mode="released",
            execution_state="released",
            active=False,
            approval_ticket=str(approval_ticket or "").strip(),
            requested_by=str(requested_by or "").strip() or "runtime",
            oob_allowlist=[],
            commands_count=0,
        )
        self._write_state(state)
        return state.to_dict()

    def read_state(self) -> Dict[str, Any]:
        if not self.state_file.exists():
            return {
                "status": "unknown",
                "reason_code": "KILLSWITCH_STATE_MISSING",
                "reason_text": "killswitch state file is missing",
                "state_file": _to_unix(self.state_file),
                "active": False,
                "execution_state": "unknown",
            }
        try:
            payload = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "status": "warning",
                "reason_code": "KILLSWITCH_STATE_INVALID",
                "reason_text": "killswitch state payload is invalid",
                "state_file": _to_unix(self.state_file),
                "active": False,
                "execution_state": "invalid",
            }
        if not isinstance(payload, dict):
            return {
                "status": "warning",
                "reason_code": "KILLSWITCH_STATE_INVALID",
                "reason_text": "killswitch state payload is invalid",
                "state_file": _to_unix(self.state_file),
                "active": False,
                "execution_state": "invalid",
            }

        payload.setdefault("state_file", _to_unix(self.state_file))
        payload["requested_by"] = str(payload.get("requested_by") or "")
        payload["approval_ticket"] = str(payload.get("approval_ticket") or "")
        payload["status"] = str(payload.get("status") or "unknown").strip().lower()
        payload["reason_code"] = str(payload.get("reason_code") or "")
        payload["reason_text"] = str(payload.get("reason_text") or "")

        execution_state = str(payload.get("execution_state") or "").strip().lower()
        if not execution_state:
            legacy_native_tool_engaged = (
                payload["reason_code"] == "KILLSWITCH_ENGAGED"
                and str(payload.get("requested_by") or "").strip().lower() == "native_tool"
                and not str(payload.get("approval_ticket") or "").strip()
            )
            if legacy_native_tool_engaged:
                execution_state = "planned"
                payload["status"] = "ok"
                payload["reason_code"] = "KILLSWITCH_PLAN_GENERATED"
                payload["reason_text"] = "KillSwitch freeze plan generated; execute it out-of-band to engage."
                payload["active"] = False
            elif bool(payload.get("active")):
                execution_state = "engaged"
            elif payload["reason_code"] == "KILLSWITCH_PLAN_PREVIEWED":
                execution_state = "previewed"
            elif payload["reason_code"] == "KILLSWITCH_RELEASED":
                execution_state = "released"
            else:
                execution_state = "planned"

        payload["execution_state"] = execution_state
        payload["active"] = bool(payload.get("active")) and execution_state == "engaged"
        return payload

    def _write_state(self, state: KillSwitchState) -> None:
        payload = {**state.to_dict(), "state_file": _to_unix(self.state_file)}
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


__all__ = ["KillSwitchController", "KillSwitchState"]
