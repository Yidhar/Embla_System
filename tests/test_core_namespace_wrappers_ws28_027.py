from __future__ import annotations

from core.event_bus import EventStore, TopicEventBus
from core.mcp import MCPCallInput, MCPCallOutput
from core.security import ApprovalGate, AuditLedger, BudgetGuardController, KillSwitchController, PolicyFirewall
from core.supervisor import BrainstemSupervisor, ProcessGuardDaemon, WatchdogDaemon


def test_core_namespace_exports_resolve() -> None:
    assert EventStore.__name__ == "EventStore"
    assert TopicEventBus.__name__ == "TopicEventBus"
    assert BrainstemSupervisor.__name__ == "BrainstemSupervisor"
    assert WatchdogDaemon.__name__ == "WatchdogDaemon"
    assert ProcessGuardDaemon.__name__ == "ProcessGuardDaemon"
    assert ApprovalGate.__name__ == "ApprovalGate"
    assert AuditLedger.__name__ == "AuditLedger"
    assert PolicyFirewall.__name__ == "PolicyFirewall"
    assert BudgetGuardController.__name__ == "BudgetGuardController"
    assert KillSwitchController.__name__ == "KillSwitchController"


def test_core_mcp_contract_models_construct() -> None:
    req = MCPCallInput(tool_name="ping", arguments={"message": "hello"})
    resp = MCPCallOutput(status="success", service_name="demo", tool_name="ping", result={"ok": True})
    assert req.tool_name == "ping"
    assert resp.status == "success"
