"""WS18-004 watchdog daemon for resource monitoring and threshold actions."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol

import psutil

from system.loop_cost_guard import LoopCostGuard


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unix_path(path: Path) -> str:
    return str(path).replace("\\", "/")


class EventEmitter(Protocol):
    def emit(self, event_type: str, payload: Dict[str, Any], **kwargs: Any) -> None:
        ...


MetricsProvider = Callable[[], Dict[str, float]]


@dataclass(frozen=True)
class WatchdogThresholds:
    cpu_percent: float = 85.0
    memory_percent: float = 85.0
    disk_percent: float = 90.0
    io_read_bps: float = 50 * 1024 * 1024
    io_write_bps: float = 50 * 1024 * 1024
    cost_per_hour: float = 5.0


@dataclass(frozen=True)
class WatchdogSnapshot:
    ts: str
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    io_read_bps: float
    io_write_bps: float
    cost_per_hour: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WatchdogAction:
    level: str
    action: str
    reasons: List[str] = field(default_factory=list)
    snapshot: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WatchdogDaemon:
    """Collects runtime resource metrics and emits threshold actions."""

    def __init__(
        self,
        *,
        thresholds: Optional[WatchdogThresholds] = None,
        metrics_provider: Optional[MetricsProvider] = None,
        event_emitter: Optional[EventEmitter] = None,
        warn_only: bool = True,
        loop_cost_guard: Optional[LoopCostGuard] = None,
    ) -> None:
        self.thresholds = thresholds or WatchdogThresholds()
        self.metrics_provider = metrics_provider or self._default_metrics_provider
        self.event_emitter = event_emitter
        self.warn_only = bool(warn_only)
        self.loop_cost_guard = loop_cost_guard
        self._last_io = psutil.disk_io_counters()
        self._last_ts = time.time()
        self._last_observation: Dict[str, Any] = {}

    def sample(self) -> WatchdogSnapshot:
        metrics = self.metrics_provider()
        return WatchdogSnapshot(
            ts=_utc_iso(),
            cpu_percent=float(metrics.get("cpu_percent", 0.0)),
            memory_percent=float(metrics.get("memory_percent", 0.0)),
            disk_percent=float(metrics.get("disk_percent", 0.0)),
            io_read_bps=float(metrics.get("io_read_bps", 0.0)),
            io_write_bps=float(metrics.get("io_write_bps", 0.0)),
            cost_per_hour=float(metrics.get("cost_per_hour", 0.0)),
        )

    def evaluate(self, snapshot: WatchdogSnapshot) -> Optional[WatchdogAction]:
        reasons: List[str] = []
        critical_reasons: List[str] = []

        if snapshot.cpu_percent >= self.thresholds.cpu_percent:
            reasons.append(f"cpu_percent={snapshot.cpu_percent:.2f}>={self.thresholds.cpu_percent:.2f}")
            if snapshot.cpu_percent >= self.thresholds.cpu_percent + 10:
                critical_reasons.append("cpu")

        if snapshot.memory_percent >= self.thresholds.memory_percent:
            reasons.append(f"memory_percent={snapshot.memory_percent:.2f}>={self.thresholds.memory_percent:.2f}")
            if snapshot.memory_percent >= self.thresholds.memory_percent + 8:
                critical_reasons.append("memory")

        if snapshot.disk_percent >= self.thresholds.disk_percent:
            reasons.append(f"disk_percent={snapshot.disk_percent:.2f}>={self.thresholds.disk_percent:.2f}")
            if snapshot.disk_percent >= self.thresholds.disk_percent + 5:
                critical_reasons.append("disk")

        if snapshot.io_read_bps >= self.thresholds.io_read_bps:
            reasons.append(f"io_read_bps={snapshot.io_read_bps:.0f}>={self.thresholds.io_read_bps:.0f}")

        if snapshot.io_write_bps >= self.thresholds.io_write_bps:
            reasons.append(f"io_write_bps={snapshot.io_write_bps:.0f}>={self.thresholds.io_write_bps:.0f}")

        if snapshot.cost_per_hour >= self.thresholds.cost_per_hour:
            reasons.append(f"cost_per_hour={snapshot.cost_per_hour:.2f}>={self.thresholds.cost_per_hour:.2f}")
            if snapshot.cost_per_hour >= self.thresholds.cost_per_hour * 1.5:
                critical_reasons.append("cost")

        if not reasons:
            return None

        level = "critical" if critical_reasons else "warn"
        if self.warn_only:
            action = "alert_only"
        elif level == "critical":
            action = "pause_dispatch_and_escalate"
        else:
            action = "throttle_new_workloads"
        return WatchdogAction(level=level, action=action, reasons=reasons, snapshot=snapshot.to_dict())

    def run_once(self) -> Optional[WatchdogAction]:
        snapshot = self.sample()
        action = self.evaluate(snapshot)
        self._last_observation = {
            "generated_at": snapshot.ts,
            "snapshot": snapshot.to_dict(),
            "threshold_hit": bool(action is not None),
            "action": action.to_dict() if action is not None else None,
        }
        if action is None:
            self._emit("WatchdogMetricsSampled", {"snapshot": snapshot.to_dict(), "threshold_hit": False})
            return None

        self._emit(
            "WatchdogThresholdExceeded",
            {
                "level": action.level,
                "action": action.action,
                "reasons": action.reasons,
                "snapshot": action.snapshot,
                "warn_only": self.warn_only,
            },
        )
        return action

    def get_last_observation(self) -> Dict[str, Any]:
        return dict(self._last_observation)

    def run_daemon(
        self,
        *,
        state_file: Path,
        interval_seconds: float = 5.0,
        max_ticks: int = 1000000000,
        stop_requested: Optional[Callable[[], bool]] = None,
        sleep_fn: Optional[Callable[[float], None]] = None,
    ) -> Dict[str, Any]:
        tick = 0
        safe_interval = max(0.0, float(interval_seconds))
        safe_max_ticks = max(1, int(max_ticks))
        should_stop = stop_requested or (lambda: False)
        sleeper = sleep_fn or time.sleep
        last_payload: Dict[str, Any] = {}

        while tick < safe_max_ticks:
            if should_stop():
                break
            tick += 1
            action = self.run_once()
            observation = self.get_last_observation()
            snapshot = observation.get("snapshot") if isinstance(observation.get("snapshot"), dict) else {}
            action_payload = action.to_dict() if action is not None else None
            level = str((action_payload or {}).get("level") or "").strip().lower()
            if level == "critical":
                status = "critical"
            elif level in {"warn", "warning"}:
                status = "warning"
            else:
                status = "ok"
            payload = {
                "generated_at": str(observation.get("generated_at") or _utc_iso()),
                "pid": int(os.getpid()),
                "mode": "daemon",
                "tick": int(tick),
                "interval_seconds": safe_interval,
                "warn_only": bool(self.warn_only),
                "threshold_hit": bool(observation.get("threshold_hit")),
                "status": status,
                "snapshot": snapshot,
                "action": action_payload,
            }
            self._write_state_file(state_file, payload)
            last_payload = payload
            if tick >= safe_max_ticks:
                break
            if safe_interval > 0:
                sleeper(safe_interval)

        return {
            "mode": "daemon",
            "ticks_completed": int(tick),
            "state_file": _unix_path(state_file),
            "last_observation": last_payload,
            "stopped_by_request": bool(should_stop()),
        }

    @staticmethod
    def read_daemon_state(
        state_file: Path,
        *,
        now_ts: Optional[float] = None,
        stale_warning_seconds: float = 120.0,
        stale_critical_seconds: float = 300.0,
    ) -> Dict[str, Any]:
        path = Path(state_file)
        now = float(now_ts if now_ts is not None else time.time())
        if not path.exists():
            return {
                "state": "missing",
                "status": "unknown",
                "reason_code": "WATCHDOG_DAEMON_STATE_MISSING",
                "reason_text": "watchdog daemon state file is missing",
                "state_file": _unix_path(path),
            }
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "state": "invalid",
                "status": "warning",
                "reason_code": "WATCHDOG_DAEMON_STATE_INVALID",
                "reason_text": "watchdog daemon state payload is invalid",
                "state_file": _unix_path(path),
            }
        if not isinstance(payload, dict):
            return {
                "state": "invalid",
                "status": "warning",
                "reason_code": "WATCHDOG_DAEMON_STATE_INVALID",
                "reason_text": "watchdog daemon state payload is invalid",
                "state_file": _unix_path(path),
            }

        generated_at = str(payload.get("generated_at") or "")
        generated_ts = WatchdogDaemon._parse_iso_timestamp(generated_at)
        heartbeat_age_seconds: Optional[float] = None
        if generated_ts is not None:
            heartbeat_age_seconds = max(0.0, round(now - generated_ts, 3))
        action_payload = payload.get("action") if isinstance(payload.get("action"), dict) else {}
        snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else {}
        status = str(payload.get("status") or "unknown").strip().lower()
        reason_code = "WATCHDOG_DAEMON_OK"
        reason_text = "watchdog daemon heartbeat is healthy"
        state = "fresh"

        if generated_ts is None:
            status = "warning"
            reason_code = "WATCHDOG_DAEMON_TIMESTAMP_INVALID"
            reason_text = "watchdog daemon state timestamp is missing or invalid"
            state = "invalid_ts"
        elif heartbeat_age_seconds is not None and heartbeat_age_seconds > float(stale_critical_seconds):
            status = "critical"
            reason_code = "WATCHDOG_DAEMON_STALE_CRITICAL"
            reason_text = "watchdog daemon state is stale beyond critical threshold"
            state = "stale"
        elif heartbeat_age_seconds is not None and heartbeat_age_seconds > float(stale_warning_seconds):
            status = "warning"
            reason_code = "WATCHDOG_DAEMON_STALE_WARNING"
            reason_text = "watchdog daemon state is stale beyond warning threshold"
            state = "stale"
        elif action_payload:
            level = str(action_payload.get("level") or "").strip().lower()
            if level == "critical":
                status = "critical"
                reason_code = "WATCHDOG_DAEMON_THRESHOLD_CRITICAL"
                reason_text = "watchdog daemon reports critical threshold hit"
            elif level in {"warn", "warning"}:
                status = "warning"
                reason_code = "WATCHDOG_DAEMON_THRESHOLD_WARNING"
                reason_text = "watchdog daemon reports warning threshold hit"
            else:
                status = "ok"
                reason_code = "WATCHDOG_DAEMON_OK"
                reason_text = "watchdog daemon reports no blocking threshold"
        elif status not in {"ok", "warning", "critical"}:
            status = "warning"
            reason_code = "WATCHDOG_DAEMON_STATUS_UNKNOWN"
            reason_text = "watchdog daemon state status is unknown"

        return {
            "state": state,
            "status": status,
            "reason_code": reason_code,
            "reason_text": reason_text,
            "state_file": _unix_path(path),
            "generated_at": generated_at,
            "heartbeat_age_seconds": heartbeat_age_seconds,
            "stale_warning_seconds": float(stale_warning_seconds),
            "stale_critical_seconds": float(stale_critical_seconds),
            "tick": int(payload.get("tick") or 0),
            "pid": int(payload.get("pid") or 0),
            "mode": str(payload.get("mode") or ""),
            "warn_only": bool(payload.get("warn_only")),
            "threshold_hit": bool(payload.get("threshold_hit")),
            "snapshot": snapshot,
            "action": action_payload,
        }

    def observe_tool_call(
        self,
        *,
        task_id: str,
        tool_name: str,
        success: bool,
        call_cost: float = 0.0,
    ) -> Optional[Dict[str, Any]]:
        if self.loop_cost_guard is None:
            return None
        action = self.loop_cost_guard.observe_tool_call(
            task_id=task_id,
            tool_name=tool_name,
            success=success,
            call_cost=call_cost,
        )
        if action is None:
            return None
        payload = action.to_dict()
        self._emit("WatchdogLoopCostAction", payload)
        return payload

    def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self.event_emitter is None:
            return
        try:
            self.event_emitter.emit(event_type, payload)
        except Exception:
            return

    @staticmethod
    def _parse_iso_timestamp(value: str) -> Optional[float]:
        text = str(value or "").strip()
        if not text:
            return None
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            return datetime.fromisoformat(normalized).timestamp()
        except ValueError:
            return None

    @staticmethod
    def _write_state_file(path: Path, payload: Dict[str, Any]) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _default_metrics_provider(self) -> Dict[str, float]:
        now = time.time()
        elapsed = max(0.001, now - self._last_ts)

        io_now = psutil.disk_io_counters()
        read_bps = 0.0
        write_bps = 0.0
        if io_now is not None and self._last_io is not None:
            read_bps = max(0.0, float(io_now.read_bytes - self._last_io.read_bytes) / elapsed)
            write_bps = max(0.0, float(io_now.write_bytes - self._last_io.write_bytes) / elapsed)
        self._last_io = io_now
        self._last_ts = now

        cpu_percent = float(psutil.cpu_percent(interval=0.0))
        memory_percent = float(psutil.virtual_memory().percent)
        disk_percent = float(psutil.disk_usage("/").percent)
        # Lightweight local estimate for intervention thresholding.
        cost_per_hour = round((cpu_percent / 100.0) * 2.0 + (memory_percent / 100.0) * 2.0 + (disk_percent / 100.0), 3)
        return {
            "cpu_percent": cpu_percent,
            "memory_percent": memory_percent,
            "disk_percent": disk_percent,
            "io_read_bps": read_bps,
            "io_write_bps": write_bps,
            "cost_per_hour": cost_per_hour,
        }
