"""
Global mutex lease with TTL/heartbeat/fencing token.

WS14-003:
- lock renew + expiration reclaim
- fencing epoch monotonic increment
- stale owner reap hook for process lineage
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from system.process_lineage import get_process_lineage_registry


@dataclass(frozen=True)
class LeaseHandle:
    lease_id: str
    owner_id: str
    job_id: str
    fencing_epoch: int
    expires_at: float
    ttl_seconds: float


class GlobalMutexManager:
    PROJECT_ROOT = Path(__file__).resolve().parents[1]

    def __init__(self, state_file: Optional[Path] = None, audit_file: Optional[Path] = None) -> None:
        runtime_dir = self.PROJECT_ROOT / "logs" / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = state_file or (runtime_dir / "global_mutex_lease.json")
        self.audit_file = audit_file or (runtime_dir / "global_mutex_events.jsonl")
        self._io_lock = asyncio.Lock()

    def _read_state(self) -> Optional[Dict[str, Any]]:
        if not self.state_file.exists():
            return None
        try:
            payload = json.loads(self.state_file.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None

    def _write_state(self, payload: Dict[str, Any]) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _delete_state(self) -> None:
        try:
            if self.state_file.exists():
                self.state_file.unlink()
        except Exception:
            pass

    def _append_audit_event(self, event: Dict[str, Any]) -> None:
        payload = {"ts": time.time(), **event}
        try:
            with self.audit_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass

    @staticmethod
    def _is_expired(state: Dict[str, Any], now_ts: float) -> bool:
        try:
            exp = float(state.get("expires_at") or 0.0)
        except Exception:
            exp = 0.0
        return exp <= now_ts

    @staticmethod
    def _state_to_handle(state: Dict[str, Any]) -> LeaseHandle:
        return LeaseHandle(
            lease_id=str(state.get("lease_id") or ""),
            owner_id=str(state.get("owner_id") or ""),
            job_id=str(state.get("job_id") or ""),
            fencing_epoch=int(state.get("fencing_epoch") or 0),
            expires_at=float(state.get("expires_at") or 0.0),
            ttl_seconds=float(state.get("ttl_seconds") or 0.0),
        )

    async def acquire(
        self,
        *,
        owner_id: str,
        job_id: str,
        ttl_seconds: float = 10.0,
        wait_timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.2,
    ) -> LeaseHandle:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")

        start_ts = time.time()
        deadline = start_ts + max(0.1, float(wait_timeout_seconds))
        owner = (owner_id or "").strip() or "unknown_owner"
        job = (job_id or "").strip() or f"job_{uuid.uuid4().hex[:8]}"

        while True:
            now_ts = time.time()
            async with self._io_lock:
                state = self._read_state()

                # No lease, expired lease, or lease for same owner+job -> claim/renew.
                can_claim = state is None or self._is_expired(state, now_ts)
                same_holder = (
                    state is not None
                    and str(state.get("owner_id") or "") == owner
                    and str(state.get("job_id") or "") == job
                )
                if can_claim or same_holder:
                    prev_epoch = int(state.get("fencing_epoch") or 0) if state else 0
                    next_epoch = prev_epoch + 1 if can_claim else max(1, prev_epoch)
                    lease_id = f"lease_{uuid.uuid4().hex[:16]}" if can_claim else str(state.get("lease_id") or "")
                    if not lease_id:
                        lease_id = f"lease_{uuid.uuid4().hex[:16]}"
                    expires_at = now_ts + float(ttl_seconds)
                    new_state = {
                        "lease_id": lease_id,
                        "owner_id": owner,
                        "job_id": job,
                        "fencing_epoch": next_epoch,
                        "issued_at": now_ts,
                        "expires_at": expires_at,
                        "ttl_seconds": float(ttl_seconds),
                    }
                    self._write_state(new_state)

                    # Fencing takeover: clear old-epoch running process lineage.
                    if can_claim and prev_epoch > 0 and next_epoch > prev_epoch:
                        try:
                            get_process_lineage_registry().reap_by_fencing_epoch(prev_epoch)
                        except Exception:
                            pass

                    return self._state_to_handle(new_state)

            if now_ts >= deadline:
                raise TimeoutError("global mutex acquire timeout")
            await asyncio.sleep(max(0.05, min(1.0, poll_interval_seconds)))

    async def renew(self, handle: LeaseHandle) -> LeaseHandle:
        now_ts = time.time()
        async with self._io_lock:
            state = self._read_state()
            if state is None:
                raise TimeoutError("lease lost: no state")
            if str(state.get("lease_id") or "") != handle.lease_id:
                raise TimeoutError("lease lost: lease_id mismatch")
            if str(state.get("owner_id") or "") != handle.owner_id:
                raise TimeoutError("lease lost: owner mismatch")
            if int(state.get("fencing_epoch") or 0) != int(handle.fencing_epoch):
                raise TimeoutError("lease lost: fencing epoch mismatch")

            ttl = max(0.5, float(handle.ttl_seconds))
            prev_expires = float(state.get("expires_at") or 0.0)
            # Keep expires_at strictly monotonic to avoid same-tick renew equality.
            new_expires = max(prev_expires + 1e-3, now_ts + ttl)
            state["expires_at"] = new_expires
            state["ttl_seconds"] = ttl
            self._write_state(state)
            return self._state_to_handle(state)

    async def release(self, handle: LeaseHandle) -> bool:
        async with self._io_lock:
            state = self._read_state()
            if state is None:
                return True
            if str(state.get("lease_id") or "") != handle.lease_id:
                return False
            if str(state.get("owner_id") or "") != handle.owner_id:
                return False
            self._delete_state()
            return True

    async def reap_expired(self) -> bool:
        report = await self.scan_and_reap_expired(reason="legacy_reap_expired")
        return bool(report.get("reclaimed_count"))

    async def scan_and_reap_expired(self, *, reason: str = "periodic_scan") -> Dict[str, Any]:
        """
        NGA-WS14-004 orphan lock scavenger entry.
        Safe to call periodically and idempotent for the same lease state.
        """
        now_ts = time.time()
        report: Dict[str, Any] = {
            "reason": reason,
            "scanned_at": now_ts,
            "reclaimed_count": 0,
            "skip_reason": "",
            "cleanup_mode": "none",
            "lineage_reaped_count": 0,
            "fencing_epoch": None,
        }

        async with self._io_lock:
            state = self._read_state()
            if not state:
                report["skip_reason"] = "no_lease"
            elif not self._is_expired(state, now_ts):
                report["skip_reason"] = "lease_active"
            else:
                try:
                    epoch = int(state.get("fencing_epoch")) if state.get("fencing_epoch") is not None else None
                except Exception:
                    epoch = None
                report["fencing_epoch"] = epoch if epoch is not None and epoch > 0 else None
                self._delete_state()
                report["reclaimed_count"] = 1

        if int(report["reclaimed_count"]) > 0:
            try:
                cleanup = get_process_lineage_registry().reap_for_lock_scavenge(
                    fencing_epoch=report["fencing_epoch"],
                    reason=f"mutex_expired:{reason}",
                )
                report["cleanup_mode"] = str(cleanup.get("cleanup_mode") or "none")
                report["lineage_reaped_count"] = int(cleanup.get("reaped_count") or 0)
            except Exception as exc:
                report["cleanup_mode"] = "cleanup_error"
                report["cleanup_error"] = type(exc).__name__

        self._append_audit_event(
            {
                "event": "scan_and_reap_expired",
                "reason": report["reason"],
                "reclaimed_count": int(report["reclaimed_count"]),
                "skip_reason": report["skip_reason"],
                "cleanup_mode": report["cleanup_mode"],
                "lineage_reaped_count": int(report["lineage_reaped_count"]),
                "fencing_epoch": report["fencing_epoch"],
            }
        )
        return report

    async def inspect(self) -> Optional[LeaseHandle]:
        async with self._io_lock:
            state = self._read_state()
            if not state:
                return None
            return self._state_to_handle(state)


_global_mutex_manager: Optional[GlobalMutexManager] = None


def get_global_mutex_manager() -> GlobalMutexManager:
    global _global_mutex_manager
    if _global_mutex_manager is None:
        _global_mutex_manager = GlobalMutexManager()
    return _global_mutex_manager


__all__ = ["LeaseHandle", "GlobalMutexManager", "get_global_mutex_manager"]
