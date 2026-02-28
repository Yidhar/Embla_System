"""Compatibility shim for watchdog daemon (migrated to core.supervisor)."""

from __future__ import annotations

from core.supervisor.watchdog_daemon import WatchdogAction, WatchdogDaemon, WatchdogSnapshot, WatchdogThresholds

__all__ = ["WatchdogThresholds", "WatchdogSnapshot", "WatchdogAction", "WatchdogDaemon"]

