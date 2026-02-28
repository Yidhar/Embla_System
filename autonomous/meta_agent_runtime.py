"""Compatibility exports for meta-agent runtime.

Canonical implementation now lives in `agents.meta_agent`.
"""

from agents.meta_agent import (
    DispatchReceipt,
    Goal,
    MetaAgentRuntime,
    ReflectionResult,
    SubTask,
    TaskFeedback,
)

__all__ = [
    "MetaAgentRuntime",
    "Goal",
    "SubTask",
    "TaskFeedback",
    "ReflectionResult",
    "DispatchReceipt",
]
