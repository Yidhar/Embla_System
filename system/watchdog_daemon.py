"""WS18-004 watchdog daemon for resource monitoring and threshold actions."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol

import psutil


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    ) -> None:
        self.thresholds = thresholds or WatchdogThresholds()
        self.metrics_provider = metrics_provider or self._default_metrics_provider
        self.event_emitter = event_emitter
        self.warn_only = bool(warn_only)
        self._last_io = psutil.disk_io_counters()
        self._last_ts = time.time()

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

    def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self.event_emitter is None:
            return
        try:
            self.event_emitter.emit(event_type, payload)
        except Exception:
            return

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
