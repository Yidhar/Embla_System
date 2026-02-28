"""Compatibility shim for brainstem supervisor (migrated to core.supervisor)."""

from __future__ import annotations

import core.supervisor.brainstem_supervisor as _impl

from core.supervisor.brainstem_supervisor import (
    BrainstemServiceSpec,
    BrainstemServiceState,
    BrainstemSupervisor,
    SupervisorAction,
)

# Keep module-level hooks for legacy monkeypatch-based tests.
shutil = _impl.shutil
subprocess = _impl.subprocess

__all__ = [
    "BrainstemServiceSpec",
    "BrainstemServiceState",
    "SupervisorAction",
    "BrainstemSupervisor",
    "shutil",
    "subprocess",
]
