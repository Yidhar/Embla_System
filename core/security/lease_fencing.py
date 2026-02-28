"""Lease fencing controller under core security namespace.

This module provides a stable brainstem-facing API for single-active lease
coordination (TTL + fencing epoch) while reusing the proven runtime manager.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from system.global_mutex import GlobalMutexManager, LeaseHandle, get_global_mutex_manager


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


@dataclass(frozen=True)
class LeaseFencingSnapshot:
    lease_id: str
    owner_id: str
    job_id: str
    fencing_epoch: int
    expires_at: float
    ttl_seconds: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lease_id": self.lease_id,
            "owner_id": self.owner_id,
            "job_id": self.job_id,
            "fencing_epoch": int(self.fencing_epoch),
            "expires_at": float(self.expires_at),
            "ttl_seconds": float(self.ttl_seconds),
        }

    @classmethod
    def from_handle(cls, handle: LeaseHandle) -> "LeaseFencingSnapshot":
        return cls(
            lease_id=str(handle.lease_id or ""),
            owner_id=str(handle.owner_id or ""),
            job_id=str(handle.job_id or ""),
            fencing_epoch=int(handle.fencing_epoch),
            expires_at=float(handle.expires_at),
            ttl_seconds=float(handle.ttl_seconds),
        )


class LeaseFencingController:
    """Facade around global mutex with explicit lease-fencing semantics."""

    def __init__(self, *, manager: Optional[GlobalMutexManager] = None) -> None:
        self.manager = manager or get_global_mutex_manager()

    @property
    def state_file(self) -> Path:
        return Path(getattr(self.manager, "state_file", Path("logs/runtime/global_mutex_lease.json")))

    @property
    def audit_file(self) -> Path:
        return Path(getattr(self.manager, "audit_file", Path("logs/runtime/global_mutex_events.jsonl")))

    def ensure_initialized(self, *, ttl_seconds: float = 10.0) -> Dict[str, Any]:
        state = self.manager.ensure_initialized(ttl_seconds=float(ttl_seconds))
        payload = dict(state if isinstance(state, dict) else {})
        payload.setdefault("state_file", _to_unix(self.state_file))
        payload.setdefault("audit_file", _to_unix(self.audit_file))
        return payload

    async def acquire(
        self,
        *,
        owner_id: str,
        job_id: str,
        ttl_seconds: float = 10.0,
        wait_timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.2,
    ) -> LeaseFencingSnapshot:
        handle = await self.manager.acquire(
            owner_id=owner_id,
            job_id=job_id,
            ttl_seconds=float(ttl_seconds),
            wait_timeout_seconds=float(wait_timeout_seconds),
            poll_interval_seconds=float(poll_interval_seconds),
        )
        return LeaseFencingSnapshot.from_handle(handle)

    async def renew(self, snapshot: LeaseFencingSnapshot) -> LeaseFencingSnapshot:
        handle = await self.manager.renew(self._to_handle(snapshot))
        return LeaseFencingSnapshot.from_handle(handle)

    async def release(self, snapshot: LeaseFencingSnapshot) -> bool:
        return bool(await self.manager.release(self._to_handle(snapshot)))

    async def inspect(self) -> Optional[LeaseFencingSnapshot]:
        handle = await self.manager.inspect()
        if handle is None:
            return None
        return LeaseFencingSnapshot.from_handle(handle)

    async def scan_and_reap_expired(self, *, reason: str = "core_lease_fencing_scan") -> Dict[str, Any]:
        report = await self.manager.scan_and_reap_expired(reason=str(reason or "core_lease_fencing_scan"))
        payload = dict(report if isinstance(report, dict) else {})
        payload.setdefault("state_file", _to_unix(self.state_file))
        payload.setdefault("audit_file", _to_unix(self.audit_file))
        return payload

    def read_state(self) -> Dict[str, Any]:
        path = self.state_file
        if not path.exists():
            return {
                "status": "missing",
                "state_file": _to_unix(path),
                "reason_code": "LEASE_STATE_MISSING",
                "reason_text": "lease state file is missing",
            }
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "status": "invalid",
                "state_file": _to_unix(path),
                "reason_code": "LEASE_STATE_INVALID",
                "reason_text": "lease state payload is invalid",
            }
        if not isinstance(payload, dict):
            return {
                "status": "invalid",
                "state_file": _to_unix(path),
                "reason_code": "LEASE_STATE_INVALID",
                "reason_text": "lease state payload is invalid",
            }
        payload["state_file"] = _to_unix(path)
        payload["audit_file"] = _to_unix(self.audit_file)
        payload["status"] = "ok"
        return payload

    @staticmethod
    def _to_handle(snapshot: LeaseFencingSnapshot) -> LeaseHandle:
        return LeaseHandle(
            lease_id=str(snapshot.lease_id or ""),
            owner_id=str(snapshot.owner_id or ""),
            job_id=str(snapshot.job_id or ""),
            fencing_epoch=int(snapshot.fencing_epoch),
            expires_at=float(snapshot.expires_at),
            ttl_seconds=float(snapshot.ttl_seconds),
        )


_lease_fencing_controller: LeaseFencingController | None = None


def get_lease_fencing_controller() -> LeaseFencingController:
    global _lease_fencing_controller
    if _lease_fencing_controller is None:
        _lease_fencing_controller = LeaseFencingController()
    return _lease_fencing_controller


__all__ = ["LeaseFencingController", "LeaseFencingSnapshot", "get_lease_fencing_controller"]

