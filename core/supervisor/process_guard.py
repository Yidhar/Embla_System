"""Process guard daemon for zombie/orphan process containment."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol

from system.process_lineage import ProcessLineageRegistry, get_process_lineage_registry


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _pid_alive(pid: int) -> bool:
    if int(pid) <= 0:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class EventEmitter(Protocol):
    def emit(self, event_type: str, payload: Dict[str, Any], **kwargs: Any) -> None:
        ...


@dataclass(frozen=True)
class ProcessGuardThresholds:
    stale_job_seconds: float = 180.0
    stale_warning_seconds: float = 120.0
    stale_critical_seconds: float = 300.0


@dataclass(frozen=True)
class ProcessGuardSnapshot:
    generated_at: str
    running_jobs: int
    orphan_jobs: int
    stale_jobs: int
    orphan_job_ids: List[str] = field(default_factory=list)
    stale_job_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ProcessGuardDaemon:
    """Monitors process lineage and reaps orphan running jobs."""

    def __init__(
        self,
        *,
        registry: Optional[ProcessLineageRegistry] = None,
        thresholds: Optional[ProcessGuardThresholds] = None,
        event_emitter: Optional[EventEmitter] = None,
    ) -> None:
        self.registry = registry or get_process_lineage_registry()
        self.thresholds = thresholds or ProcessGuardThresholds()
        self.event_emitter = event_emitter
        self._last_observation: Dict[str, Any] = {}

    def sample(self) -> ProcessGuardSnapshot:
        now = time.time()
        running = list(self.registry.list_running())
        orphan_ids: List[str] = []
        stale_ids: List[str] = []
        for record in running:
            pid = int(record.root_pid or 0)
            if pid <= 0 or not _pid_alive(pid):
                orphan_ids.append(str(record.job_root_id))
            started_at = float(record.started_at or 0.0)
            if started_at > 0 and (now - started_at) >= float(self.thresholds.stale_job_seconds):
                stale_ids.append(str(record.job_root_id))
        return ProcessGuardSnapshot(
            generated_at=_utc_iso(),
            running_jobs=len(running),
            orphan_jobs=len(orphan_ids),
            stale_jobs=len(stale_ids),
            orphan_job_ids=sorted({x for x in orphan_ids if x}),
            stale_job_ids=sorted({x for x in stale_ids if x}),
        )

    def run_once(
        self,
        *,
        auto_reap: bool = True,
        max_epoch: Optional[int] = None,
    ) -> Dict[str, Any]:
        snapshot = self.sample()
        orphan_reaped = 0
        if auto_reap and int(snapshot.orphan_jobs) > 0:
            orphan_reaped = int(
                self.registry.reap_orphaned_running_jobs(
                    reason="process_guard_scan",
                    max_epoch=max_epoch,
                )
            )

        if int(snapshot.orphan_jobs) > 0 and orphan_reaped < int(snapshot.orphan_jobs):
            status = "critical"
            reason_code = "PROCESS_GUARD_ORPHAN_RUNNING_JOBS"
            reason_text = "Detected orphan running jobs and auto-reap did not clean all of them."
        elif int(snapshot.orphan_jobs) > 0:
            status = "warning"
            reason_code = "PROCESS_GUARD_ORPHAN_REAPED"
            reason_text = "Detected orphan running jobs and process guard reaped them."
        elif int(snapshot.stale_jobs) > 0:
            status = "warning"
            reason_code = "PROCESS_GUARD_STALE_RUNNING_JOBS"
            reason_text = "Detected stale running jobs exceeding configured age threshold."
        else:
            status = "ok"
            reason_code = "OK"
            reason_text = "No orphan/stale running jobs detected."

        payload: Dict[str, Any] = {
            "generated_at": snapshot.generated_at,
            "pid": int(os.getpid()),
            "status": status,
            "reason_code": reason_code,
            "reason_text": reason_text,
            "running_jobs": int(snapshot.running_jobs),
            "orphan_jobs": int(snapshot.orphan_jobs),
            "stale_jobs": int(snapshot.stale_jobs),
            "orphan_job_ids": list(snapshot.orphan_job_ids),
            "stale_job_ids": list(snapshot.stale_job_ids),
            "orphan_reaped_count": int(orphan_reaped),
            "thresholds": {
                "stale_job_seconds": float(self.thresholds.stale_job_seconds),
                "stale_warning_seconds": float(self.thresholds.stale_warning_seconds),
                "stale_critical_seconds": float(self.thresholds.stale_critical_seconds),
            },
        }
        self._last_observation = payload
        self._emit_events(payload)
        return payload

    def run_daemon(
        self,
        *,
        state_file: Path,
        interval_seconds: float = 5.0,
        max_ticks: int = 1000000000,
        auto_reap: bool = True,
        sleep_fn: Optional[Callable[[float], None]] = None,
    ) -> Dict[str, Any]:
        tick = 0
        safe_interval = max(0.0, float(interval_seconds))
        safe_ticks = max(1, int(max_ticks))
        sleeper = sleep_fn or time.sleep
        state_path = Path(state_file)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        last_payload: Dict[str, Any] = {}

        while tick < safe_ticks:
            tick += 1
            payload = self.run_once(auto_reap=auto_reap)
            payload["mode"] = "daemon"
            payload["tick"] = int(tick)
            state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            last_payload = payload
            if tick >= safe_ticks:
                break
            if safe_interval > 0:
                sleeper(safe_interval)

        return {
            "mode": "daemon",
            "ticks_completed": int(tick),
            "state_file": _to_unix(state_path),
            "last_observation": last_payload,
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
        if not path.exists():
            return {
                "status": "unknown",
                "reason_code": "PROCESS_GUARD_STATE_MISSING",
                "reason_text": "process guard state file is missing",
                "state_file": _to_unix(path),
            }
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "status": "warning",
                "reason_code": "PROCESS_GUARD_STATE_INVALID",
                "reason_text": "process guard state payload is invalid",
                "state_file": _to_unix(path),
            }
        if not isinstance(payload, dict):
            return {
                "status": "warning",
                "reason_code": "PROCESS_GUARD_STATE_INVALID",
                "reason_text": "process guard state payload is invalid",
                "state_file": _to_unix(path),
            }

        now = float(now_ts if now_ts is not None else time.time())
        generated_at = str(payload.get("generated_at") or "")
        generated_ts = ProcessGuardDaemon._parse_iso(generated_at)
        heartbeat_age_seconds = None
        if generated_ts is not None:
            heartbeat_age_seconds = max(0.0, round(now - generated_ts, 3))

        status = str(payload.get("status") or "unknown").strip().lower()
        reason_code = str(payload.get("reason_code") or "")
        reason_text = str(payload.get("reason_text") or "")
        if generated_ts is None:
            status = "warning"
            reason_code = "PROCESS_GUARD_TIMESTAMP_INVALID"
            reason_text = "process guard state timestamp is invalid"
        elif heartbeat_age_seconds is not None and heartbeat_age_seconds > float(stale_critical_seconds):
            status = "critical"
            reason_code = "PROCESS_GUARD_STATE_STALE_CRITICAL"
            reason_text = "process guard state is stale beyond critical threshold"
        elif heartbeat_age_seconds is not None and heartbeat_age_seconds > float(stale_warning_seconds):
            status = "warning"
            reason_code = "PROCESS_GUARD_STATE_STALE_WARNING"
            reason_text = "process guard state is stale beyond warning threshold"

        return {
            **payload,
            "status": status,
            "reason_code": reason_code,
            "reason_text": reason_text,
            "state_file": _to_unix(path),
            "heartbeat_age_seconds": heartbeat_age_seconds,
            "stale_warning_seconds": float(stale_warning_seconds),
            "stale_critical_seconds": float(stale_critical_seconds),
        }

    @staticmethod
    def _parse_iso(value: str) -> Optional[float]:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            return datetime.fromisoformat(text).timestamp()
        except ValueError:
            return None

    def _emit_events(self, payload: Dict[str, Any]) -> None:
        if self.event_emitter is None:
            return
        try:
            self.event_emitter.emit("ProcessGuardSampled", payload, source="core.supervisor.process_guard")
            if int(payload.get("orphan_jobs") or 0) > 0:
                self.event_emitter.emit("ProcessGuardZombieDetected", payload, source="core.supervisor.process_guard")
            if int(payload.get("orphan_reaped_count") or 0) > 0:
                self.event_emitter.emit("ProcessGuardOrphanReaped", payload, source="core.supervisor.process_guard")
        except Exception:
            return


__all__ = ["ProcessGuardDaemon", "ProcessGuardSnapshot", "ProcessGuardThresholds"]
