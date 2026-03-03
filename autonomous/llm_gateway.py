"""Legacy shim for LLM gateway.

Deprecated path: ``autonomous.llm_gateway``.
Canonical path: ``agents.llm_gateway``.
"""

from __future__ import annotations

from agents.llm_gateway import (
    GatewayPlan,
    GatewayPlanMetrics,
    GatewayRouteDecision,
    GatewayRouteRequest,
    LLMGateway,
    PromptCacheOutcome,
    PromptComposeDecision,
    PromptEnvelope,
    PromptEnvelopeInput,
    PromptSlice,
)

__all__ = [
    "GatewayRouteRequest",
    "GatewayRouteDecision",
    "PromptEnvelopeInput",
    "PromptSlice",
    "PromptComposeDecision",
    "PromptEnvelope",
    "PromptCacheOutcome",
    "GatewayPlanMetrics",
    "GatewayPlan",
    "LLMGateway",
]
