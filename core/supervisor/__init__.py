"""Core supervisor namespace wrappers."""

from .brainstem_supervisor import BrainstemSupervisor
from .watchdog_daemon import WatchdogDaemon

__all__ = ["BrainstemSupervisor", "WatchdogDaemon"]
