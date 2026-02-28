"""Compatibility shim for policy firewall (migrated to core.security)."""

from __future__ import annotations

from core.security.policy_firewall import FirewallDecision, PolicyFirewall, get_policy_firewall

__all__ = ["FirewallDecision", "PolicyFirewall", "get_policy_firewall"]

