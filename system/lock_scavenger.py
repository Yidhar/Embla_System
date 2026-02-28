"""
Periodic orphan lock scavenger wrapper for GlobalMutex.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from core.security import GlobalMutexManager, get_global_mutex_manager


class LockScavenger:
    def __init__(self, manager: Optional[GlobalMutexManager] = None, *, interval_seconds: float = 5.0) -> None:
        self.manager = manager or get_global_mutex_manager()
        self.interval_seconds = max(0.2, float(interval_seconds))

    async def run_once(self, *, reason: str = "periodic_scan") -> Dict[str, Any]:
        return await self.manager.scan_and_reap_expired(reason=reason)

    async def run_forever(
        self,
        *,
        stop_event: Optional[asyncio.Event] = None,
        reason_prefix: str = "periodic_scan",
    ) -> None:
        stop = stop_event or asyncio.Event()
        tick = 0
        while not stop.is_set():
            tick += 1
            await self.run_once(reason=f"{reason_prefix}:{tick}")
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue


__all__ = ["LockScavenger"]
