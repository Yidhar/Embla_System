"""Core MCP isolated worker primitives + runtime snapshot helper."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from mcpserver.plugin_worker import (
    PluginWorkerProxy,
    PluginWorkerSpec,
    get_plugin_worker_runtime_metrics,
)


@dataclass(frozen=True)
class IsolatedWorkerRuntimeSnapshot:
    status: str
    service_count: int
    timeout_total: int
    circuit_open_total: int
    payload_reject_total: int
    output_budget_reject_total: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "service_count": self.service_count,
            "timeout_total": self.timeout_total,
            "circuit_open_total": self.circuit_open_total,
            "payload_reject_total": self.payload_reject_total,
            "output_budget_reject_total": self.output_budget_reject_total,
        }


class IsolatedWorkerRuntime:
    """Read aggregate runtime health for isolated plugin workers."""

    def snapshot(self) -> IsolatedWorkerRuntimeSnapshot:
        metrics = get_plugin_worker_runtime_metrics()
        services = metrics.get("services") if isinstance(metrics.get("services"), dict) else {}

        timeout_total = 0
        circuit_open_total = 0
        payload_reject_total = 0
        output_budget_reject_total = 0
        for row in services.values():
            if not isinstance(row, dict):
                continue
            timeout_total += int(row.get("timeout_total") or 0)
            circuit_open_total += int(row.get("circuit_open_total") or 0)
            payload_reject_total += int(row.get("payload_reject_total") or 0)
            output_budget_reject_total += int(row.get("output_budget_reject_total") or 0)

        if circuit_open_total > 0:
            status = "critical"
        elif timeout_total > 0 or payload_reject_total > 0 or output_budget_reject_total > 0:
            status = "warning"
        else:
            status = "ok"

        return IsolatedWorkerRuntimeSnapshot(
            status=status,
            service_count=len(services),
            timeout_total=timeout_total,
            circuit_open_total=circuit_open_total,
            payload_reject_total=payload_reject_total,
            output_budget_reject_total=output_budget_reject_total,
        )


__all__ = ["PluginWorkerProxy", "PluginWorkerSpec", "IsolatedWorkerRuntime", "IsolatedWorkerRuntimeSnapshot"]
