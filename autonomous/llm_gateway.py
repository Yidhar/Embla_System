"""Archived legacy shim for LLM gateway.

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

ARCHIVED_SHIM: bool = True
ARCHIVED_SINCE: str = "2026-03-04"
CANONICAL_MODULE: str = "agents.llm_gateway"

__all__ = [
    "ARCHIVED_SHIM",
    "ARCHIVED_SINCE",
    "CANONICAL_MODULE",
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
