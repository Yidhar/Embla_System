"""Autonomous SDLC skeleton package."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from autonomous.daily_checkpoint import DailyCheckpointConfig, DailyCheckpointEngine, DailyCheckpointReport
from autonomous.llm_gateway import (
    GatewayPlan,
    GatewayPlanMetrics,
    GatewayRouteDecision,
    GatewayRouteRequest,
    LLMGateway,
    PromptCacheOutcome,
    PromptEnvelope,
    PromptEnvelopeInput,
)
from agents.meta_agent import Goal, MetaAgentRuntime, SubTask, TaskFeedback
from agents.router_engine import RouterDecision, RouterRequest, TaskRouterEngine
from agents.memory.working_memory import (
    MemoryWindowRebalanceResult,
    MemoryWindowThresholds,
    WorkingMemoryWindowManager,
)
from autonomous.router_arbiter_guard import RouterArbiterDecision, RouterArbiterGuard

if TYPE_CHECKING:
    from autonomous.system_agent import SystemAgent

__all__ = [
    "SystemAgent",
    "MetaAgentRuntime",
    "Goal",
    "SubTask",
    "TaskFeedback",
    "TaskRouterEngine",
    "RouterRequest",
    "RouterDecision",
    "RouterArbiterGuard",
    "RouterArbiterDecision",
    "DailyCheckpointConfig",
    "DailyCheckpointEngine",
    "DailyCheckpointReport",
    "LLMGateway",
    "GatewayRouteRequest",
    "GatewayRouteDecision",
    "PromptEnvelopeInput",
    "PromptEnvelope",
    "PromptCacheOutcome",
    "GatewayPlanMetrics",
    "GatewayPlan",
    "MemoryWindowThresholds",
    "MemoryWindowRebalanceResult",
    "WorkingMemoryWindowManager",
]


def __getattr__(name: str) -> Any:
    if name == "SystemAgent":
        from autonomous.system_agent import SystemAgent as _SystemAgent

        return _SystemAgent
    raise AttributeError(f"module 'autonomous' has no attribute {name!r}")
