"""Compatibility shim for working memory manager.

Canonical implementation moved to `agents.memory.working_memory`.
"""

from agents.memory.working_memory import (
    MemoryWindowRebalanceResult,
    MemoryWindowThresholds,
    WorkingMemoryWindowManager,
)

__all__ = [
    "MemoryWindowThresholds",
    "MemoryWindowRebalanceResult",
    "WorkingMemoryWindowManager",
]
