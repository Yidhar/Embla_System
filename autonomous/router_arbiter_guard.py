"""Archived legacy shim for router arbiter guard.

Deprecated path: ``autonomous.router_arbiter_guard``.
Canonical path: ``agents.router_arbiter_guard``.
"""

from __future__ import annotations

from agents.router_arbiter_guard import RouterArbiterDecision, RouterArbiterGuard

ARCHIVED_SHIM: bool = True
ARCHIVED_SINCE: str = "2026-03-04"
CANONICAL_MODULE: str = "agents.router_arbiter_guard"

__all__ = [
    "ARCHIVED_SHIM",
    "ARCHIVED_SINCE",
    "CANONICAL_MODULE",
    "RouterArbiterDecision",
    "RouterArbiterGuard",
]
