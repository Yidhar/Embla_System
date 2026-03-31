"""WS33-004 watchdog actuator — executes intervention actions when thresholds are breached."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

logger = logging.getLogger(__name__)

_PAUSE_SIGNAL_FILE = Path("logs/runtime/watchdog_pause_signal.json")
_THROTTLE_CONFIG_FILE = Path("logs/runtime/watchdog_throttle_config.json")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventEmitter(Protocol):
    def emit(self, event_type: str, payload: Dict[str, Any], **kwargs: Any) -> None: ...


class WatchdogActuator:
    """Executes watchdog intervention actions when thresholds are breached."""

    def __init__(self, *, event_emitter: Optional[EventEmitter] = None) -> None:
        self._event_emitter = event_emitter

    def handle_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        action_type = str(action.get("action", "alert_only")).strip() or "alert_only"

        if action_type == "pause_dispatch_and_escalate":
            self._write_pause_signal(action)
        elif action_type == "throttle_new_workloads":
            self._write_throttle_config(action)

        # Always emit event
        if self._event_emitter is not None:
            try:
                self._event_emitter.emit("WatchdogActionExecuted", action)
            except Exception:
                logger.debug("WatchdogActuator: failed to emit WatchdogActionExecuted event")

        return {"executed": action_type}

    @staticmethod
    def _write_pause_signal(action: Dict[str, Any]) -> None:
        """Write a pause signal file that the pipeline can check."""
        payload = {
            "paused_at": _utc_iso(),
            "reason": "watchdog_pause_dispatch_and_escalate",
            "action": action,
        }
        try:
            _PAUSE_SIGNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
            _PAUSE_SIGNAL_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            logger.warning("WatchdogActuator: failed to write pause signal file")

    @staticmethod
    def _write_throttle_config(action: Dict[str, Any]) -> None:
        """Write throttle config that the pipeline can check."""
        payload = {
            "throttled_at": _utc_iso(),
            "reason": "watchdog_throttle_new_workloads",
            "action": action,
        }
        try:
            _THROTTLE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            _THROTTLE_CONFIG_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            logger.warning("WatchdogActuator: failed to write throttle config file")


__all__ = ["WatchdogActuator"]
