"""Policy firewall under the core security namespace.

This module is no longer a thin import-only wrapper. It exposes the full
runtime firewall implementation and adds a strict helper API for callers that
prefer explicit exception flow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from system.policy_firewall import FirewallDecision, PolicyFirewall as _SystemPolicyFirewall


class PolicyFirewall(_SystemPolicyFirewall):
    """Core security firewall with strict helper for guardrail-first call sites."""

    def validate_or_raise(self, tool_name: str, call: Dict[str, Any]) -> FirewallDecision:
        decision = self.validate_native_call(tool_name, call)
        if not decision.allowed:
            raise PermissionError(f"{decision.rule_id}: {decision.reason}")
        return decision


_policy_firewall_singleton: PolicyFirewall | None = None


def get_policy_firewall(*, audit_file: Path | None = None) -> PolicyFirewall:
    global _policy_firewall_singleton
    if _policy_firewall_singleton is None:
        _policy_firewall_singleton = PolicyFirewall(audit_file=audit_file)
    return _policy_firewall_singleton


__all__ = ["FirewallDecision", "PolicyFirewall", "get_policy_firewall"]
