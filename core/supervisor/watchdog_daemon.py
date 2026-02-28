"""Core namespace exports for watchdog daemon primitives."""

from __future__ import annotations

from system.watchdog_daemon import WatchdogAction, WatchdogDaemon, WatchdogSnapshot, WatchdogThresholds

__all__ = ["WatchdogAction", "WatchdogDaemon", "WatchdogSnapshot", "WatchdogThresholds"]
