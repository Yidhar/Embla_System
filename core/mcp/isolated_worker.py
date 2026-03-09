"""Core MCP isolated worker primitives + runtime snapshot helper.

The old mcpserver.plugin_worker dependency has been removed.
Stub classes are provided for backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


# ── Backward-compatible stubs for removed mcpserver.plugin_worker ──

class PluginWorkerSpec:
    """Stub — previously from mcpserver.plugin_worker."""
    pass


class PluginWorkerProxy:
    """Stub — previously from mcpserver.plugin_worker."""
    pass


def get_plugin_worker_runtime_metrics() -> Dict[str, Any]:
    """Stub — returns empty metrics since mcpserver has been removed."""
    return {"services": {}}


# ── Dataclasses ──

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


@dataclass(frozen=True)
class MCPWorkerExecutionContext:
    call_id: str
    trace_id: str
    workflow_id: str
    session_id: str
    fencing_epoch: Optional[int]
    budget_remaining: Optional[float]
    timeout_ms: Optional[int]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "call_id": self.call_id,
            "trace_id": self.trace_id,
            "workflow_id": self.workflow_id,
            "session_id": self.session_id,
            "fencing_epoch": self.fencing_epoch,
            "budget_remaining": self.budget_remaining,
            "timeout_ms": self.timeout_ms,
        }


def extract_worker_execution_context(payload: Dict[str, Any]) -> MCPWorkerExecutionContext:
    data = dict(payload or {})
    return MCPWorkerExecutionContext(
        call_id=str(data.get("_tool_call_id") or data.get("call_id") or ""),
        trace_id=str(data.get("_trace_id") or data.get("trace_id") or ""),
        workflow_id=str(data.get("_workflow_id") or data.get("workflow_id") or ""),
        session_id=str(data.get("_session_id") or data.get("session_id") or ""),
        fencing_epoch=_parse_positive_int(data.get("_fencing_epoch"), fallback=data.get("fencing_epoch")),
        budget_remaining=_parse_non_negative_float(data.get("_budget_remaining"), fallback=data.get("budget_remaining")),
        timeout_ms=_parse_positive_int(data.get("mcp_tool_timeout_ms"), fallback=data.get("timeout_ms")),
    )


def validate_worker_execution_context(context: MCPWorkerExecutionContext) -> Dict[str, Any]:
    issues: List[str] = []
    if context.fencing_epoch is not None and int(context.fencing_epoch) <= 0:
        issues.append("fencing_epoch_must_be_positive")
    if context.budget_remaining is not None and float(context.budget_remaining) < 0:
        issues.append("budget_remaining_must_be_non_negative")
    if context.timeout_ms is not None and int(context.timeout_ms) <= 0:
        issues.append("timeout_ms_must_be_positive")
    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "context": context.to_dict(),
    }


def _parse_positive_int(value: Any, *, fallback: Any = None) -> Optional[int]:
    candidate = value if value is not None else fallback
    if candidate is None:
        return None
    try:
        parsed = int(candidate)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _parse_non_negative_float(value: Any, *, fallback: Any = None) -> Optional[float]:
    candidate = value if value is not None else fallback
    if candidate is None:
        return None
    try:
        parsed = float(candidate)
    except Exception:
        return None
    if parsed < 0:
        return 0.0
    return parsed


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


__all__ = [
    "PluginWorkerProxy",
    "PluginWorkerSpec",
    "IsolatedWorkerRuntime",
    "IsolatedWorkerRuntimeSnapshot",
    "MCPWorkerExecutionContext",
    "extract_worker_execution_context",
    "validate_worker_execution_context",
]
