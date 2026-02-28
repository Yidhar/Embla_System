"""Compatibility shim for global mutex lease (migrated to core.security)."""

from __future__ import annotations

import core.security.lease_fencing as _impl

from core.security.lease_fencing import (
    LeaseFencingController,
    LeaseFencingSnapshot,
    LeaseHandle,
    get_lease_fencing_controller,
)

# Keep module-level hooks for legacy monkeypatch-based tests.
time = _impl.time
get_process_lineage_registry = _impl.get_process_lineage_registry


class GlobalMutexManager(_impl.GlobalMutexManager):
    """Compatibility manager that mirrors patched hooks into core implementation."""

    @staticmethod
    def _sync_registry_hook() -> None:
        _impl.get_process_lineage_registry = get_process_lineage_registry

    async def acquire(self, *args, **kwargs):  # type: ignore[override]
        self._sync_registry_hook()
        return await super().acquire(*args, **kwargs)

    async def scan_and_reap_expired(self, *args, **kwargs):  # type: ignore[override]
        self._sync_registry_hook()
        return await super().scan_and_reap_expired(*args, **kwargs)


_global_mutex_manager: GlobalMutexManager | None = None


def get_global_mutex_manager() -> GlobalMutexManager:
    global _global_mutex_manager
    if _global_mutex_manager is None:
        _global_mutex_manager = GlobalMutexManager()
    return _global_mutex_manager

__all__ = [
    "LeaseHandle",
    "GlobalMutexManager",
    "get_global_mutex_manager",
    "LeaseFencingSnapshot",
    "LeaseFencingController",
    "get_lease_fencing_controller",
    "time",
    "get_process_lineage_registry",
]
