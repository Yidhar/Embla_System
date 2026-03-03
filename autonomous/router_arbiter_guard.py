"""Legacy shim for router arbiter guard.

Deprecated path: ``autonomous.router_arbiter_guard``.
Canonical path: ``agents.router_arbiter_guard``.
"""

from __future__ import annotations

from agents.router_arbiter_guard import RouterArbiterDecision, RouterArbiterGuard

__all__ = ["RouterArbiterDecision", "RouterArbiterGuard"]
