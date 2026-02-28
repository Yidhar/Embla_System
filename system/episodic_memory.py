"""Compatibility shim for episodic memory.

Canonical implementation moved to `agents.memory.episodic_memory`.
"""

from agents.memory.episodic_memory import (
    EpisodicMemoryArchive,
    EpisodicRecord,
    EpisodicSearchHit,
    archive_tool_results_for_session,
    build_reinjection_context,
    get_episodic_memory,
)

__all__ = [
    "EpisodicRecord",
    "EpisodicSearchHit",
    "EpisodicMemoryArchive",
    "archive_tool_results_for_session",
    "build_reinjection_context",
    "get_episodic_memory",
]
