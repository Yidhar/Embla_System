from __future__ import annotations

from typing import Any, Dict, List

import apiserver.api_server as api_server
import pytest

pytestmark = pytest.mark.skip(reason="archived route-semantic guard tests")


class _CaptureStore:
    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []

    def emit(self, event_type: str, payload: Dict[str, Any], source: str = "") -> None:
        self.rows.append(
            {
                "event_type": event_type,
                "payload": dict(payload),
                "source": source,
            }
        )


def test_route_quality_warning_guard_sets_shell_clarify_override_and_escalates_budget(monkeypatch) -> None:
    session = {"messages": []}
    monkeypatch.setattr(api_server.message_manager, "get_session", lambda _sid: session)
    monkeypatch.setattr(
        api_server,
        "_get_chat_route_quality_guard_summary",
        lambda force_refresh=False: {
            "status": "warning",
            "reason_codes": ["SHELL_CLARIFY_BUDGET_ESCALATION_WARNING"],
            "reason_text": "warning",
            "trend": {"status": "warning", "direction": "degrading", "sample_count": 32},
            "evaluated_at": "2026-02-26T00:00:00+00:00",
        },
    )

    route_meta = {
        "route_semantic": "shell_clarify",
        "risk_level": "unknown",
        "shell_readonly_hit": False,
        "dispatch_to_core": False,
        "router_decision": {
            "delegation_intent": "general_assistance",
            "prompt_profile": "shell_readonly_general",
            "injection_mode": "normal",
        },
    }

    guarded = api_server._apply_chat_route_quality_guard(dict(route_meta))
    assert guarded["route_semantic"] == "shell_clarify"
    assert guarded["route_quality_guard_applied"] is True
    assert guarded["shell_clarify_limit_override"] == 0
    assert guarded["route_quality_guard_action"] == "tighten_shell_clarify_limit_zero"

    updated = api_server._apply_shell_clarify_budget(dict(guarded), session_id="sess-ws28-012-warning")
    assert updated["route_semantic"] == "core_execution"
    assert updated["shell_clarify_budget_escalated"] is True
    assert updated["shell_clarify_budget_reason"] == "clarify_budget_guard_override_auto_escalate_core"


def test_route_quality_critical_guard_forces_suspicious_route_semantic_to_core(monkeypatch) -> None:
    monkeypatch.setattr(
        api_server,
        "_get_chat_route_quality_guard_summary",
        lambda force_refresh=False: {
            "status": "critical",
            "reason_codes": ["READONLY_WRITE_EXPOSURE_CRITICAL", "ROUTE_QUALITY_TREND_CRITICAL"],
            "reason_text": "critical",
            "trend": {"status": "critical", "direction": "degrading", "sample_count": 88},
            "evaluated_at": "2026-02-26T00:00:00+00:00",
        },
    )

    route_meta = {
        "route_semantic": "shell_readonly",
        "risk_level": "write_repo",
        "shell_readonly_hit": True,
        "dispatch_to_core": False,
        "router_decision": {
            "delegation_intent": "read_only_exploration",
            "prompt_profile": "shell_readonly_general",
            "injection_mode": "minimal",
        },
    }

    guarded = api_server._apply_chat_route_quality_guard(dict(route_meta))

    assert guarded["route_semantic"] == "core_execution"
    assert guarded["dispatch_to_core"] is True
    assert guarded["shell_readonly_hit"] is False
    assert guarded["route_quality_guard_applied"] is True
    assert guarded["route_quality_guard_action"] == "force_core_execution"
    assert "ROUTE_QUALITY_CRITICAL_FORCE_CORE" in guarded["route_quality_guard_reason_codes"]


def test_route_quality_critical_guard_keeps_readonly_route_semantic_when_only_trend_critical(monkeypatch) -> None:
    monkeypatch.setattr(
        api_server,
        "_get_chat_route_quality_guard_summary",
        lambda force_refresh=False: {
            "status": "critical",
            "reason_codes": ["SHELL_CLARIFY_BUDGET_ESCALATION_CRITICAL", "ROUTE_QUALITY_TREND_CRITICAL"],
            "reason_text": "critical",
            "trend": {"status": "critical", "direction": "stable", "sample_count": 42},
            "evaluated_at": "2026-02-27T00:00:00+00:00",
        },
    )

    route_meta = {
        "route_semantic": "shell_readonly",
        "risk_level": "read_only",
        "shell_readonly_hit": True,
        "dispatch_to_core": False,
        "router_decision": {
            "delegation_intent": "read_only_exploration",
            "prompt_profile": "shell_readonly_general",
            "injection_mode": "minimal",
        },
    }

    guarded = api_server._apply_chat_route_quality_guard(dict(route_meta))

    assert guarded["route_semantic"] == "shell_readonly"
    assert guarded["shell_readonly_hit"] is True
    assert guarded["dispatch_to_core"] is False
    assert guarded["route_quality_guard_applied"] is False
    assert guarded["route_quality_guard_action"] == "none"


def test_emit_chat_route_guard_event_uses_warning_event_type() -> None:
    original_store = api_server._CHAT_ROUTE_EVENT_STORE
    capture = _CaptureStore()
    api_server._CHAT_ROUTE_EVENT_STORE = capture
    try:
        route_meta = {
            "route_semantic": "core_execution",
            "risk_level": "unknown",
            "route_quality_guard_applied": True,
            "route_quality_guard_status": "warning",
            "route_quality_guard_action": "tighten_shell_clarify_limit_zero",
            "route_quality_guard_reason": "route_quality_warning_tighten_shell_clarify_budget",
            "route_quality_guard_reason_codes": ["ROUTE_QUALITY_WARNING_SHELL_CLARIFY_LIMIT_ZERO"],
            "route_quality_guard_route_semantic_before": "shell_clarify",
            "route_quality_guard_route_semantic_after": "core_execution",
            "shell_session_id": "shell-a",
            "core_execution_session_id": "shell-a__core",
            "execution_session_id": "shell-a__core",
            "router_decision": {"trace_id": "trace-a", "task_id": "task-a"},
        }
        api_server._emit_chat_route_guard_event(route_meta, session_id="shell-a")

        assert len(capture.rows) == 1
        row = capture.rows[0]
        assert row["event_type"] == "RouteQualityGuardEscalatedWarning"
        assert row["payload"]["route_semantic_before"] == "shell_clarify"
        assert row["payload"]["route_semantic_after"] == "core_execution"
    finally:
        api_server._CHAT_ROUTE_EVENT_STORE = original_store


def test_emit_chat_route_guard_event_skips_when_guard_not_applied() -> None:
    original_store = api_server._CHAT_ROUTE_EVENT_STORE
    capture = _CaptureStore()
    api_server._CHAT_ROUTE_EVENT_STORE = capture
    try:
        api_server._emit_chat_route_guard_event(
            {
                "route_semantic": "shell_readonly",
                "route_quality_guard_applied": False,
                "route_quality_guard_status": "warning",
            },
            session_id="shell-b",
        )
        assert capture.rows == []
    finally:
        api_server._CHAT_ROUTE_EVENT_STORE = original_store


def test_route_prompt_event_payload_contains_guard_fields() -> None:
    payload = api_server._build_chat_route_prompt_event_payload(
        {
            "route_semantic": "core_execution",
            "risk_level": "write_repo",
            "shell_readonly_hit": False,
            "dispatch_to_core": True,
            "shell_clarify_turns": 0,
            "shell_clarify_limit": 0,
            "shell_clarify_limit_override": 0,
            "shell_clarify_budget_escalated": True,
            "shell_clarify_budget_reason": "clarify_budget_guard_override_auto_escalate_core",
            "route_quality_guard_status": "warning",
            "route_quality_guard_applied": True,
            "route_quality_guard_action": "tighten_shell_clarify_limit_zero",
            "route_quality_guard_reason": "route_quality_warning_tighten_shell_clarify_budget",
            "route_quality_guard_reason_codes": ["ROUTE_QUALITY_WARNING_SHELL_CLARIFY_LIMIT_ZERO"],
            "route_quality_guard_route_semantic_before": "shell_clarify",
            "route_quality_guard_route_semantic_after": "core_execution",
            "route_quality_guard_evaluated_at": "2026-02-26T00:00:00+00:00",
            "route_quality_guard_trend_status": "warning",
            "route_quality_guard_trend_direction": "degrading",
            "route_quality_guard_trend_sample_count": 20,
            "router_decision": {
                "delegation_intent": "core_execution",
                "prompt_profile": "core_exec_general",
                "injection_mode": "normal",
            },
        }
    )

    assert payload["shell_clarify_limit_override"] == 0
    assert payload["route_quality_guard_status"] == "warning"
    assert payload["route_quality_guard_applied"] is True
    assert payload["route_quality_guard_action"] == "tighten_shell_clarify_limit_zero"
    assert payload["route_quality_guard_route_semantic_before"] == "shell_clarify"
    assert payload["route_quality_guard_route_semantic_after"] == "core_execution"


def test_collect_route_bridge_events_includes_guard_fields(monkeypatch) -> None:
    shell_session_id = "ws28-012-shell"
    core_execution_session_id = "ws28-012-shell__core"
    monkeypatch.setattr(
        api_server,
        "_read_chat_route_event_rows",
        lambda limit=2000: [
            {
                "timestamp": "2026-02-26T00:00:00+00:00",
                "event_type": "PromptInjectionComposed",
                "source": "apiserver.chat_stream",
                "payload": {
                    "session_id": shell_session_id,
                    "shell_session_id": shell_session_id,
                    "core_execution_session_id": core_execution_session_id,
                    "execution_session_id": core_execution_session_id,
                    "route_semantic": "core_execution",
                    "trigger": "core_execution",
                    "delegation_intent": "core_execution",
                    "prompt_profile": "core_exec_general",
                    "injection_mode": "normal",
                    "shell_clarify_turns": 0,
                    "shell_clarify_limit": 0,
                    "shell_clarify_limit_override": 0,
                    "shell_clarify_budget_escalated": True,
                    "shell_clarify_budget_reason": "clarify_budget_guard_override_auto_escalate_core",
                    "route_quality_guard_status": "warning",
                    "route_quality_guard_applied": True,
                    "route_quality_guard_action": "tighten_shell_clarify_limit_zero",
                    "route_quality_guard_reason": "route_quality_warning_tighten_shell_clarify_budget",
                    "route_quality_guard_reason_codes": ["ROUTE_QUALITY_WARNING_SHELL_CLARIFY_LIMIT_ZERO"],
                    "route_quality_guard_route_semantic_before": "shell_clarify",
                    "route_quality_guard_route_semantic_after": "core_execution",
                    "core_execution_session_created": True,
                },
            }
        ],
    )

    events = api_server._collect_chat_route_session_state_events(
        session_ids=[shell_session_id],
        limit=5,
    )

    assert len(events) == 1
    event = events[0]
    assert event["route_quality_guard_status"] == "warning"
    assert event["route_quality_guard_applied"] is True
    assert event["route_quality_guard_action"] == "tighten_shell_clarify_limit_zero"
    assert event["shell_clarify_limit_override"] == 0
