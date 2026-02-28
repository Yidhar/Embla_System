"""Compatibility exports for router engine.

Canonical implementation now lives in `agents.router_engine`.
"""

from agents.router_engine import RouterDecision, RouterRequest, TaskRouterEngine

__all__ = ["TaskRouterEngine", "RouterRequest", "RouterDecision"]
