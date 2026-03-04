"""Chat-route domain — extracted from api_server.py (Phase 2).

Contains:
- Chat route resolution, quality guard, budget/bridge logic
- Event store management and emission
- Router arbiter guard integration
- Model override and prompt hints
"""
from __future__ import annotations

import json
import logging
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from agents.shell_agent import ShellAgent
from agents.router_arbiter_guard import RouterArbiterGuard
from agents.llm_gateway import LLMGateway
from core.event_bus import EventStore
from apiserver.message_manager import message_manager as _default_message_manager
from system.coding_intent import (
    contains_direct_coding_signal,
    has_recent_coding_context,
    is_coding_followup,
)
from agents.contract_runtime import trim_contract_text as trim_brain_contract_text
from apiserver.routes_ops import (
    _ops_build_route_quality_summary,
    _ops_build_route_quality_trend,
    _ops_repo_root,
    _ops_status_to_severity,
    _ops_utc_iso_now,
)

logger = logging.getLogger(__name__)
_CHAT_RUNTIME_CONTEXT: Dict[str, Any] = {
    "message_manager": None,
    "message_manager_getter": None,
    "config_getter": None,
    "route_arbiter_guard": None,
    "route_arbiter_guard_getter": None,
    "event_store": None,
    "event_store_getter": None,
    "event_store_factory": None,
    "quality_guard_summary_getter": None,
    "event_rows_reader": None,
}


def _bind_chat_runtime_context(
    *,
    message_manager: Any = None,
    message_manager_getter: Any = None,
    config_getter: Any = None,
    route_arbiter_guard: Any = None,
    route_arbiter_guard_getter: Any = None,
    event_store: Any = None,
    event_store_getter: Any = None,
    event_store_factory: Any = None,
    quality_guard_summary_getter: Any = None,
    event_rows_reader: Any = None,
) -> None:
    """Bind runtime dependencies to reduce cross-module import coupling."""
    if message_manager is not None:
        _CHAT_RUNTIME_CONTEXT["message_manager"] = message_manager
    if message_manager_getter is not None:
        _CHAT_RUNTIME_CONTEXT["message_manager_getter"] = message_manager_getter
    if config_getter is not None:
        _CHAT_RUNTIME_CONTEXT["config_getter"] = config_getter
    if route_arbiter_guard is not None:
        _CHAT_RUNTIME_CONTEXT["route_arbiter_guard"] = route_arbiter_guard
    if route_arbiter_guard_getter is not None:
        _CHAT_RUNTIME_CONTEXT["route_arbiter_guard_getter"] = route_arbiter_guard_getter
    if event_store is not None:
        _CHAT_RUNTIME_CONTEXT["event_store"] = event_store
    if event_store_getter is not None:
        _CHAT_RUNTIME_CONTEXT["event_store_getter"] = event_store_getter
    if event_store_factory is not None:
        _CHAT_RUNTIME_CONTEXT["event_store_factory"] = event_store_factory
    if quality_guard_summary_getter is not None:
        _CHAT_RUNTIME_CONTEXT["quality_guard_summary_getter"] = quality_guard_summary_getter
    if event_rows_reader is not None:
        _CHAT_RUNTIME_CONTEXT["event_rows_reader"] = event_rows_reader


# ── Lazy cross-module accessors (avoid circular import) ──────
def _get_message_manager():
    """Accessor for message_manager with runtime context binding."""
    manager = _CHAT_RUNTIME_CONTEXT.get("message_manager")
    if manager is not None:
        return manager
    getter = _CHAT_RUNTIME_CONTEXT.get("message_manager_getter")
    if callable(getter):
        resolved = getter()
        if resolved is not None:
            return resolved
    return _default_message_manager

def _get_config():
    """Accessor for get_config with runtime context binding."""
    getter = _CHAT_RUNTIME_CONTEXT.get("config_getter")
    if callable(getter):
        return getter()

    from system.config import get_config as _gc

    return _gc()


def _get_chat_route_arbiter_guard() -> Optional[RouterArbiterGuard]:
    """Resolve router arbiter guard with runtime context binding."""
    getter = _CHAT_RUNTIME_CONTEXT.get("route_arbiter_guard_getter")
    if callable(getter):
        injected = getter()
        if injected is not None:
            return injected
    injected_ctx = _CHAT_RUNTIME_CONTEXT.get("route_arbiter_guard")
    if injected_ctx is not None:
        return injected_ctx
    return _CHAT_ROUTE_ARBITER_GUARD


def _router_arbiter_max_delegate_turns() -> int:
    guard = _get_chat_route_arbiter_guard()
    if guard is None:
        return 0
    try:
        return int(getattr(guard, "max_delegate_turns", 0) or 0)
    except Exception:
        return 0

__all__ = [
    "_CHAT_ROUTE_ARBITER_GUARD",
    "_CHAT_ROUTE_EVENT_STORE",
    "_CHAT_ROUTE_FOLLOWUP_MARKERS",
    "_CHAT_ROUTE_GREETING_MARKERS",
    "_CHAT_ROUTE_GUARD_CACHE",
    "_CHAT_ROUTE_GUARD_CACHE_TTL_MS",
    "_CHAT_ROUTE_HIGH_RISK_MARKERS",
    "_CHAT_ROUTE_PATH_B_CLARIFY_LIMIT",
    "_CHAT_ROUTE_READONLY_MARKERS",
    "_CHAT_ROUTE_STATE_KEY",
    "_SHELL_AGENT",
    "_apply_chat_route_quality_guard",
    "_apply_chat_route_router_arbiter_guard",
    "_apply_outer_core_session_bridge",
    "_apply_path_b_clarify_budget",
    "_build_chat_route_bridge_payload",
    "_build_chat_route_prompt_event_payload",
    "_build_chat_route_prompt_hints",
    "_build_chat_route_quality_guard_summary",
    "_bind_chat_runtime_context",
    "_build_path_model_override",
    "_collect_chat_route_bridge_events",
    "_emit_agentic_loop_completion_event",
    "_emit_chat_route_arbiter_event",
    "_emit_chat_route_guard_event",
    "_emit_chat_route_prompt_event",
    "_ensure_chat_route_state",
    "_extract_agentic_execution_receipt_text",
    "_force_route_to_pipeline",
    "_format_sse_payload_chunk_json",
    "_get_chat_route_event_store",
    "_get_chat_route_quality_guard_summary",
    "_infer_chat_route_complexity",
    "_infer_chat_route_risk_level",
    "_merge_model_override",
    "_merge_route_quality_reason_codes",
    "_normalize_chat_text",
    "_read_chat_route_event_rows",
    "_resolve_chat_stream_route",
    "_sanitize_route_quality_reason_codes",
    "_sanitize_router_arbiter_reason_codes",
    "_trim_contract_text",
]

# ── Chat-route constants ──────────────────────────────────────
# _CHAT_PATH_ROUTER removed: routing now handled by _SHELL_AGENT (ShellAgent wrapping TaskRouterEngine)
try:
    _CHAT_LLM_GATEWAY: Optional[LLMGateway] = LLMGateway()
except Exception:
    _CHAT_LLM_GATEWAY = None
_CHAT_ROUTE_EVENT_STORE: Optional[EventStore] = None
_CHAT_ROUTE_STATE_KEY = "_chat_route_state"
_CHAT_ROUTE_PATH_B_CLARIFY_LIMIT = 1
_CHAT_ROUTE_GUARD_CACHE_TTL_MS = 5_000
_CHAT_ROUTE_GUARD_CACHE: Dict[str, Any] = {"expires_at_ms": 0, "summary": {}}
_CHAT_ROUTE_ARBITER_GUARD = RouterArbiterGuard(max_delegate_turns=3)
_CHAT_ROUTE_HIGH_RISK_MARKERS = (
    "deploy",
    "rollback",
    "release",
    "上线",
    "回滚",
    "发布",
    "生产",
    "权限",
    "删除",
    "批量改写",
)
_CHAT_ROUTE_READONLY_MARKERS = (
    "explain",
    "summary",
    "summarize",
    "analysis",
    "analyse",
    "read",
    "check",
    "状态",
    "现状",
    "总结",
    "解释",
    "分析",
    "查看",
)
_CHAT_ROUTE_GREETING_MARKERS = (
    "hello",
    "hi",
    "hey",
    "你好",
    "嗨",
)
_CHAT_ROUTE_FOLLOWUP_MARKERS = (
    "continue",
    "go on",
    "继续",
    "接着",
    "然后",
)

# ── Chat-route functions ─────────────────────────────────────
def _normalize_chat_text(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _infer_chat_route_risk_level(message: str, *, recent_messages: Optional[List[Dict[str, Any]]] = None) -> str:
    normalized = _normalize_chat_text(message)
    if not normalized:
        return "read_only"

    if recent_messages and is_coding_followup(message) and has_recent_coding_context(recent_messages):
        return "write_repo"

    if len(normalized) <= 24 and any(marker in normalized for marker in _CHAT_ROUTE_FOLLOWUP_MARKERS):
        return "unknown"

    if any(marker in normalized for marker in _CHAT_ROUTE_HIGH_RISK_MARKERS):
        return "deploy"

    if any(marker in normalized for marker in _CHAT_ROUTE_GREETING_MARKERS):
        return "read_only"

    if any(marker in normalized for marker in _CHAT_ROUTE_READONLY_MARKERS):
        return "read_only"

    if contains_direct_coding_signal(message):
        return "write_repo"

    if "?" in normalized or "？" in str(message):
        return "read_only"

    return "unknown"


def _infer_chat_route_complexity(message: str) -> str:
    raw = str(message or "")
    length = len(raw)
    if contains_direct_coding_signal(raw) or length >= 220:
        return "high"
    if length >= 80:
        return "medium"
    return "low"


# ── ShellAgent singleton for routing ──────────────────────────
_SHELL_AGENT = ShellAgent()


def _resolve_chat_stream_route(message: str, *, session_id: str) -> Dict[str, Any]:
    """Route user message via ShellAgent.

    Returns route_meta with delegation_intent (no path-a/b/c classification).
    """
    normalized_message = str(message or "")
    recent_messages = _get_message_manager().get_recent_messages(session_id, count=10)
    risk_level = _infer_chat_route_risk_level(normalized_message, recent_messages=recent_messages)
    complexity = _infer_chat_route_complexity(normalized_message)
    decision = _SHELL_AGENT.route(
        normalized_message,
        session_id=session_id,
        risk_level=risk_level,
        complexity=complexity,
    )
    needs_core = _SHELL_AGENT.should_dispatch(decision)
    intent = str(decision.delegation_intent or "")

    # backward-compat keys for guard functions and observability
    if needs_core:
        compat_path = "path-c"
    elif intent == "read_only_exploration":
        compat_path = "path-a"
    else:
        compat_path = "path-b"

    return {
        "delegation_intent": decision.delegation_intent,
        "needs_core": needs_core,
        "risk_level": risk_level,
        "router_decision": decision.to_dict(),
        # backward-compat (consumed by guard functions / observability)
        "path": compat_path,
        "outer_readonly_hit": compat_path == "path-a",
        "core_escalation": needs_core,
    }


def _ensure_chat_route_state(session_id: str) -> Dict[str, Any]:
    session = _get_message_manager().get_session(session_id)
    if not isinstance(session, dict):
        return {"path_b_clarify_turns": 0}
    state = session.get(_CHAT_ROUTE_STATE_KEY)
    if not isinstance(state, dict):
        state = {"path_b_clarify_turns": 0}
        session[_CHAT_ROUTE_STATE_KEY] = state
    try:
        state["path_b_clarify_turns"] = max(0, int(state.get("path_b_clarify_turns", 0)))
    except Exception:
        state["path_b_clarify_turns"] = 0
    return state


def _sanitize_route_quality_reason_codes(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    cleaned: List[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _merge_route_quality_reason_codes(existing: Any, extra: List[str]) -> List[str]:
    merged = _sanitize_route_quality_reason_codes(existing)
    for code in extra:
        text = str(code or "").strip()
        if text and text not in merged:
            merged.append(text)
    return merged


def _sanitize_router_arbiter_reason_codes(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    cleaned: List[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _build_chat_route_quality_guard_summary() -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "status": "unknown",
        "reason_codes": ["ROUTE_QUALITY_SIGNAL_UNKNOWN"],
        "reason_text": "Route-quality signals are insufficient.",
        "trend": {},
    }
    try:
        from scripts.export_slo_snapshot import build_snapshot

        repo_root = _ops_repo_root()
        events_file = repo_root / "logs" / "autonomous" / "events.jsonl"
        route_quality_trend = _ops_build_route_quality_trend(events_file, window_size=20, max_windows=6)
        snapshot = build_snapshot(repo_root=repo_root, events_limit=4000)
        snapshot_metrics = snapshot.get("metrics") if isinstance(snapshot.get("metrics"), dict) else {}
        summary = _ops_build_route_quality_summary(snapshot_metrics, trend=route_quality_trend)
    except Exception as exc:
        logger.debug(f"构建 chat route quality guard summary 失败，降级 unknown: {exc}")

    summary["evaluated_at"] = _ops_utc_iso_now()
    summary["cache_ttl_ms"] = int(_CHAT_ROUTE_GUARD_CACHE_TTL_MS)
    summary["reason_codes"] = _sanitize_route_quality_reason_codes(summary.get("reason_codes"))
    if not summary["reason_codes"]:
        summary["reason_codes"] = ["ROUTE_QUALITY_SIGNAL_UNKNOWN"]
    summary["status"] = _ops_status_to_severity(str(summary.get("status") or "unknown"))
    summary["reason_text"] = str(summary.get("reason_text") or "")
    trend = summary.get("trend") if isinstance(summary.get("trend"), dict) else {}
    summary["trend"] = {
        "status": _ops_status_to_severity(str(trend.get("status") or "unknown")),
        "direction": str(trend.get("direction") or "unknown"),
        "sample_count": int(trend.get("sample_count") or 0),
    }
    return summary


def _get_chat_route_quality_guard_summary(*, force_refresh: bool = False) -> Dict[str, Any]:
    override = _CHAT_RUNTIME_CONTEXT.get("quality_guard_summary_getter")
    if callable(override):
        try:
            payload = override(force_refresh=force_refresh)
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass

    now_ms = int(time.time() * 1000)
    cached = _CHAT_ROUTE_GUARD_CACHE
    expires_at = int(cached.get("expires_at_ms") or 0)
    cached_summary = cached.get("summary") if isinstance(cached.get("summary"), dict) else {}
    if not force_refresh and now_ms < expires_at and cached_summary:
        return dict(cached_summary)

    summary = _build_chat_route_quality_guard_summary()
    _CHAT_ROUTE_GUARD_CACHE["expires_at_ms"] = now_ms + int(_CHAT_ROUTE_GUARD_CACHE_TTL_MS)
    _CHAT_ROUTE_GUARD_CACHE["summary"] = dict(summary)
    return summary


def _force_route_to_pipeline(route_meta: Dict[str, Any], *, reason: str) -> Dict[str, Any]:
    """Force-escalate to Core execution pipeline."""
    decision = route_meta.get("router_decision") if isinstance(route_meta.get("router_decision"), dict) else {}
    effective_decision = dict(decision)
    effective_decision["delegation_intent"] = "core_execution"
    prompt_profile = str(effective_decision.get("prompt_profile") or "").strip()
    if not prompt_profile.startswith("core_exec"):
        effective_decision["prompt_profile"] = "core_exec_general"
    injection_mode = str(effective_decision.get("injection_mode") or "").strip().lower()
    if injection_mode in {"", "minimal"}:
        effective_decision["injection_mode"] = "normal"

    route_meta["delegation_intent"] = "core_execution"
    route_meta["needs_core"] = True
    route_meta["router_decision"] = effective_decision
    route_meta["route_forced_to_core_reason"] = str(reason or "")
    # backward-compat keys for guard functions
    route_meta["path"] = "path-c"
    route_meta["outer_readonly_hit"] = False
    route_meta["core_escalation"] = True
    return route_meta


def _apply_chat_route_quality_guard(route_meta: Dict[str, Any]) -> Dict[str, Any]:
    summary = _get_chat_route_quality_guard_summary()
    guard_status = _ops_status_to_severity(str(summary.get("status") or "unknown"))
    reason_codes = _sanitize_route_quality_reason_codes(summary.get("reason_codes"))
    reason_text = str(summary.get("reason_text") or "")
    trend = summary.get("trend") if isinstance(summary.get("trend"), dict) else {}
    guard_path_before = str(route_meta.get("path") or "path-c")

    route_meta["route_quality_guard_status"] = guard_status
    route_meta["route_quality_guard_reason_codes"] = reason_codes
    route_meta["route_quality_guard_reason"] = reason_text
    route_meta["route_quality_guard_applied"] = False
    route_meta["route_quality_guard_action"] = "none"
    route_meta["route_quality_guard_path_before"] = guard_path_before
    route_meta["route_quality_guard_path_after"] = guard_path_before
    route_meta["route_quality_guard_evaluated_at"] = str(summary.get("evaluated_at") or "")
    route_meta["route_quality_guard_trend_status"] = _ops_status_to_severity(str(trend.get("status") or "unknown"))
    route_meta["route_quality_guard_trend_direction"] = str(trend.get("direction") or "unknown")
    route_meta["route_quality_guard_trend_sample_count"] = int(trend.get("sample_count") or 0)

    if guard_status == "warning" and guard_path_before == "path-b":
        route_meta["path_b_clarify_limit_override"] = 0
        route_meta["route_quality_guard_applied"] = True
        route_meta["route_quality_guard_action"] = "tighten_path_b_clarify_limit_zero"
        route_meta["route_quality_guard_reason"] = "route_quality_warning_tighten_path_b_budget"
        route_meta["route_quality_guard_reason_codes"] = _merge_route_quality_reason_codes(
            reason_codes,
            ["ROUTE_QUALITY_WARNING_PATH_B_LIMIT_ZERO"],
        )
    elif guard_status == "critical":
        risk_level = str(route_meta.get("risk_level") or "").strip().lower()
        path = str(route_meta.get("path") or "path-c")
        reason_code_set = set(reason_codes)
        suspicious_path_a = path == "path-a" and (
            risk_level in {"write_repo", "deploy"}
            or "READONLY_WRITE_EXPOSURE_CRITICAL" in reason_code_set
        )
        high_risk_non_core = path in {"path-a", "path-b"} and risk_level in {"write_repo", "deploy"}
        if suspicious_path_a or high_risk_non_core:
            route_meta = _force_route_to_pipeline(
                route_meta,
                reason="route_quality_guard_critical_auto_escalate_core",
            )
            route_meta["route_quality_guard_applied"] = True
            route_meta["route_quality_guard_action"] = "force_core_path"
            route_meta["route_quality_guard_reason"] = "route_quality_critical_force_core"
            route_meta["route_quality_guard_reason_codes"] = _merge_route_quality_reason_codes(
                reason_codes,
                [
                    "ROUTE_QUALITY_CRITICAL_FORCE_CORE",
                    "ROUTE_QUALITY_CRITICAL_HIGH_RISK_NON_CORE" if high_risk_non_core else "",
                    "ROUTE_QUALITY_CRITICAL_SUSPICIOUS_PATH_A" if suspicious_path_a else "",
                ],
            )
        elif path == "path-b":
            route_meta["path_b_clarify_limit_override"] = 0
            route_meta["route_quality_guard_applied"] = True
            route_meta["route_quality_guard_action"] = "force_path_b_zero_budget"
            route_meta["route_quality_guard_reason"] = "route_quality_critical_force_path_b_zero_budget"
            route_meta["route_quality_guard_reason_codes"] = _merge_route_quality_reason_codes(
                reason_codes,
                ["ROUTE_QUALITY_CRITICAL_PATH_B_LIMIT_ZERO"],
            )

    route_meta["route_quality_guard_path_after"] = str(route_meta.get("path") or guard_path_before)
    return route_meta


def _apply_path_b_clarify_budget(route_meta: Dict[str, Any], *, session_id: str) -> Dict[str, Any]:
    state = _ensure_chat_route_state(session_id)
    path = str(route_meta.get("path") or "path-c")
    clarify_turns = max(0, int(state.get("path_b_clarify_turns", 0)))
    limit_override: Optional[int] = None
    if route_meta.get("path_b_clarify_limit_override") is not None:
        try:
            limit_override = max(0, int(route_meta.get("path_b_clarify_limit_override")))
        except Exception:
            limit_override = 0
    clarify_limit = limit_override if limit_override is not None else _CHAT_ROUTE_PATH_B_CLARIFY_LIMIT

    route_meta["path_b_clarify_limit"] = clarify_limit
    route_meta["path_b_clarify_limit_override"] = limit_override
    route_meta["path_b_budget_escalated"] = False
    route_meta["path_b_budget_reason"] = ""
    route_meta["path_b_clarify_turns"] = clarify_turns

    if path != "path-b":
        state["path_b_clarify_turns"] = 0
        route_meta["path_b_clarify_turns"] = 0
        return route_meta

    if clarify_turns >= clarify_limit:
        budget_reason = "clarify_budget_exceeded_auto_escalate_core"
        if limit_override is not None:
            budget_reason = "clarify_budget_guard_override_auto_escalate_core"
        route_meta = _force_route_to_pipeline(route_meta, reason=budget_reason)
        route_meta["path_b_budget_escalated"] = True
        route_meta["path_b_budget_reason"] = budget_reason
        route_meta["path_b_clarify_turns"] = clarify_turns
        state["path_b_clarify_turns"] = 0
        return route_meta

    state["path_b_clarify_turns"] = clarify_turns + 1
    route_meta["path_b_clarify_turns"] = int(state["path_b_clarify_turns"])
    return route_meta


def _apply_chat_route_router_arbiter_guard(route_meta: Dict[str, Any], *, session_id: str) -> Dict[str, Any]:
    state = _ensure_chat_route_state(session_id)
    current_path = str(route_meta.get("path") or "path-c")
    previous_path = str(state.get("last_router_path") or "").strip()

    route_meta["router_arbiter_status"] = "ok"
    route_meta["router_arbiter_applied"] = False
    route_meta["router_arbiter_action"] = "none"
    route_meta["router_arbiter_reason"] = ""
    route_meta["router_arbiter_reason_codes"] = []
    route_meta["router_arbiter_path_before"] = previous_path
    route_meta["router_arbiter_path_after"] = current_path
    route_meta["router_arbiter_delegate_turns"] = 0
    guard_for_limit = _get_chat_route_arbiter_guard()
    route_meta["router_arbiter_max_delegate_turns"] = int(
        guard_for_limit.max_delegate_turns if guard_for_limit is not None else 0
    )
    route_meta["router_arbiter_conflict_ticket"] = ""
    route_meta["router_arbiter_freeze"] = False
    route_meta["router_arbiter_hitl"] = False
    route_meta["router_arbiter_escalated"] = False

    guard = _get_chat_route_arbiter_guard()
    if guard is None:
        state["last_router_path"] = str(route_meta.get("path") or current_path)
        return route_meta

    summary_before = guard.build_conflict_summary(session_id)
    frozen_before = bool(summary_before.get("freeze"))
    if frozen_before and current_path != "path-c":
        route_meta = _force_route_to_pipeline(route_meta, reason="router_arbiter_frozen_to_core")
        route_meta["router_arbiter_status"] = "critical"
        route_meta["router_arbiter_applied"] = True
        route_meta["router_arbiter_action"] = "freeze_to_core_latched"
        route_meta["router_arbiter_reason"] = "router_arbiter_frozen_to_core"
        route_meta["router_arbiter_reason_codes"] = ["ROUTER_ARBITER_FREEZE_LATCHED"]
        route_meta["router_arbiter_path_after"] = str(route_meta.get("path") or "path-c")
        route_meta["router_arbiter_delegate_turns"] = int(summary_before.get("delegate_turns") or 0)
        route_meta["router_arbiter_max_delegate_turns"] = int(guard.max_delegate_turns)
        route_meta["router_arbiter_conflict_ticket"] = str(summary_before.get("conflict_ticket") or "")
        route_meta["router_arbiter_freeze"] = True
        route_meta["router_arbiter_hitl"] = bool(summary_before.get("hitl"))
        route_meta["router_arbiter_escalated"] = True
        state["last_router_path"] = str(route_meta.get("path") or "path-c")
        return route_meta

    if previous_path and previous_path != current_path:
        transition_pair = "|".join(sorted([previous_path, current_path]))
        decision = guard.register_delegate_turn(
            task_id=session_id,
            from_agent=previous_path,
            to_agent=current_path,
            reason="chat_route_path_switch",
            conflict_ticket=f"chat_route_ping_pong::{transition_pair}",
            candidate_decisions=[previous_path, current_path],
        )
        decision_payload = decision.to_dict()
        route_meta["router_arbiter"] = decision_payload
        route_meta["router_arbiter_delegate_turns"] = int(decision.delegate_turns)
        route_meta["router_arbiter_max_delegate_turns"] = int(decision.max_delegate_turns)
        route_meta["router_arbiter_conflict_ticket"] = str(decision.conflict_ticket or "")
        route_meta["router_arbiter_freeze"] = bool(decision.freeze)
        route_meta["router_arbiter_hitl"] = bool(decision.hitl)
        route_meta["router_arbiter_escalated"] = bool(decision.escalated)

        if decision.escalated or decision.freeze:
            route_meta = _force_route_to_pipeline(route_meta, reason="router_arbiter_ping_pong_freeze_core")
            route_meta["router_arbiter_status"] = "critical"
            route_meta["router_arbiter_applied"] = True
            route_meta["router_arbiter_action"] = "freeze_to_core"
            route_meta["router_arbiter_reason"] = "router_arbiter_ping_pong_freeze_core"
            route_meta["router_arbiter_reason_codes"] = [
                "ROUTER_ARBITER_PING_PONG_FREEZE_CORE",
                "ROUTER_ARBITER_HITL_REQUIRED" if bool(decision.hitl) else "",
            ]
            route_meta["router_arbiter_path_after"] = str(route_meta.get("path") or "path-c")
        else:
            route_meta["router_arbiter_status"] = "warning"
            route_meta["router_arbiter_action"] = "observe_ping_pong"
            route_meta["router_arbiter_reason"] = "router_arbiter_path_switch_observed"
            route_meta["router_arbiter_reason_codes"] = ["ROUTER_ARBITER_PATH_SWITCH_OBSERVED"]

    route_meta["router_arbiter_reason_codes"] = _sanitize_router_arbiter_reason_codes(
        route_meta.get("router_arbiter_reason_codes")
    )
    route_meta["router_arbiter_path_after"] = str(route_meta.get("path") or current_path)
    state["last_router_path"] = str(route_meta.get("path") or current_path)
    return route_meta


def _apply_outer_core_session_bridge(route_meta: Dict[str, Any], *, outer_session_id: str) -> Dict[str, Any]:
    state = _ensure_chat_route_state(outer_session_id)
    path = str(route_meta.get("path") or "path-c")
    route_meta["outer_session_id"] = str(outer_session_id or "")
    route_meta["core_session_id"] = str(state.get("core_session_id") or "")
    route_meta["execution_session_id"] = str(outer_session_id or "")
    route_meta["core_session_created"] = False

    if path != "path-c":
        state["last_execution_session_id"] = str(outer_session_id or "")
        return route_meta

    core_session_id = str(state.get("core_session_id") or "").strip()
    core_session_created = False
    if not core_session_id:
        core_session_id = f"{str(outer_session_id or '')}__core"
    if not _get_message_manager().get_session(core_session_id):
        outer_session = _get_message_manager().get_session(outer_session_id) or {}
        temporary = bool(outer_session.get("temporary", False))
        _get_message_manager().create_session(session_id=core_session_id, temporary=temporary)
        core_session_created = True

    state["core_session_id"] = core_session_id
    state["last_core_escalation_at_ms"] = int(time.time() * 1000)
    state["last_execution_session_id"] = core_session_id

    route_meta["core_session_id"] = core_session_id
    route_meta["execution_session_id"] = core_session_id
    route_meta["core_session_created"] = core_session_created
    return route_meta


def _build_path_model_override(path: str) -> Optional[Dict[str, str]]:
    """Build route-scoped LLM override for outer/core execution paths."""
    normalized_path = str(path or "").strip().lower()
    target_key = "core" if normalized_path == "path-c" else "outer"
    cfg = _get_config()
    api_cfg = getattr(cfg, "api", None)
    routing_cfg = getattr(api_cfg, "routing", None) if api_cfg is not None else None
    target_cfg = getattr(routing_cfg, target_key, None) if routing_cfg is not None else None
    if target_cfg is None:
        return None

    override: Dict[str, str] = {}
    for source_key, target_field in (
        ("api_key", "api_key"),
        ("base_url", "api_base"),
        ("model", "model"),
        ("provider", "provider"),
        ("protocol", "protocol"),
    ):
        value = str(getattr(target_cfg, source_key, "") or "").strip()
        if value:
            override[target_field] = value

    route_reasoning_effort = str(
        getattr(target_cfg, "reasoning_effort", "") or getattr(target_cfg, "thinking_intensity", "") or ""
    ).strip()
    if route_reasoning_effort:
        override["reasoning_effort"] = route_reasoning_effort

    return override or None


def _merge_model_override(
    base: Optional[Dict[str, str]],
    high_priority: Optional[Dict[str, str]],
) -> Optional[Dict[str, str]]:
    """Merge model override dictionaries with high-priority values taking precedence."""
    merged: Dict[str, str] = {}
    if isinstance(base, dict):
        for key, value in base.items():
            text = str(value or "").strip()
            if text:
                merged[str(key)] = text
    if isinstance(high_priority, dict):
        for key, value in high_priority.items():
            text = str(value or "").strip()
            if text:
                merged[str(key)] = text
    return merged or None


def _build_chat_route_prompt_hints(route_meta: Dict[str, Any]) -> str:
    path = str(route_meta.get("path") or "path-c")
    decision = route_meta.get("router_decision") if isinstance(route_meta.get("router_decision"), dict) else {}
    lines = [
        "[PromptRouteDecision]",
        f"path={path}",
        f"prompt_profile={str(decision.get('prompt_profile') or '')}",
        f"injection_mode={str(decision.get('injection_mode') or '')}",
        f"delegation_intent={str(decision.get('delegation_intent') or '')}",
    ]
    if bool(route_meta.get("route_quality_guard_applied")):
        lines.append(
            "route_quality_guard="
            f"{_ops_status_to_severity(str(route_meta.get('route_quality_guard_status') or 'unknown'))}:"
            f"{str(route_meta.get('route_quality_guard_action') or 'none')}"
        )
    router_arbiter_status = _ops_status_to_severity(str(route_meta.get("router_arbiter_status") or "unknown"))
    if router_arbiter_status in {"warning", "critical"}:
        lines.append(
            "router_arbiter_guard="
            f"{router_arbiter_status}:{str(route_meta.get('router_arbiter_action') or 'none')}"
        )

    if path == "path-a":
        lines.append("Route policy: Outer Direct Read-Only. Do not call tools. Reply directly with analysis.")
    elif path == "path-b":
        lines.append("Route policy: Outer Clarify. Ask at most one clarifying question before any execution escalation.")
    else:
        lines.append("Route policy: Core Execution. You may plan and execute through the tool loop.")
    return "\n".join(lines)


def _trim_contract_text(value: Any, *, limit: int = 240) -> str:
    return trim_brain_contract_text(value, limit=limit)



def _get_chat_route_event_store() -> Optional[EventStore]:
    global _CHAT_ROUTE_EVENT_STORE
    getter = _CHAT_RUNTIME_CONTEXT.get("event_store_getter")
    if callable(getter):
        try:
            injected = getter()
            if injected is not None:
                _CHAT_ROUTE_EVENT_STORE = injected
                _CHAT_RUNTIME_CONTEXT["event_store"] = injected
                return _CHAT_ROUTE_EVENT_STORE
        except Exception:
            pass

    bound_store = _CHAT_RUNTIME_CONTEXT.get("event_store")
    if bound_store is not None:
        _CHAT_ROUTE_EVENT_STORE = bound_store
        return _CHAT_ROUTE_EVENT_STORE

    if _CHAT_ROUTE_EVENT_STORE is not None:
        return _CHAT_ROUTE_EVENT_STORE
    try:
        event_file = Path(__file__).resolve().parent.parent / "logs" / "autonomous" / "events.jsonl"
        factory = _CHAT_RUNTIME_CONTEXT.get("event_store_factory")
        if callable(factory):
            try:
                _CHAT_ROUTE_EVENT_STORE = factory(file_path=event_file)
            except TypeError:
                _CHAT_ROUTE_EVENT_STORE = factory(event_file)
        else:
            _CHAT_ROUTE_EVENT_STORE = EventStore(file_path=event_file)
        _CHAT_RUNTIME_CONTEXT["event_store"] = _CHAT_ROUTE_EVENT_STORE
    except Exception as exc:
        logger.debug(f"初始化 chat route event store 失败: {exc}")
        return None
    return _CHAT_ROUTE_EVENT_STORE


def _build_chat_route_prompt_event_payload(route_meta: Dict[str, Any]) -> Dict[str, Any]:
    decision = route_meta.get("router_decision") if isinstance(route_meta.get("router_decision"), dict) else {}
    path = str(route_meta.get("path") or "path-c")
    delegation_intent = str(decision.get("delegation_intent") or "").strip()
    selected_layers = route_meta.get("_slice_selected_layers") or []
    selected_layer_counts = route_meta.get("_slice_selected_layer_counts") or {}
    dropped_slice_count = int(route_meta.get("_slice_dropped_count") or 0)
    dropped_conflict_count = int(route_meta.get("_slice_dropped_conflict_count") or dropped_slice_count)
    return {
        "task_type": str(decision.get("task_type") or ""),
        "severity": str(route_meta.get("risk_level") or ""),
        "path": path,
        "trigger": path,
        "prompt_profile": str(decision.get("prompt_profile") or ""),
        "injection_mode": str(decision.get("injection_mode") or ""),
        "delegation_intent": delegation_intent,
        "delegation_hit": delegation_intent.lower().startswith("delegate"),
        "outer_readonly_hit": bool(route_meta.get("outer_readonly_hit")),
        "core_escalation": bool(route_meta.get("core_escalation")),
        "readonly_write_tool_exposed": False,
        "readonly_write_tool_candidate_count": 0,
        "readonly_write_tool_selected_count": 0,
        "readonly_write_tool_dropped_count": 0,
        "readonly_write_tool_selected_slices": [],
        "readonly_write_tool_dropped_slices": [],
        "selected_slices": route_meta.get("_slice_selected") or [],
        "dropped_slices": route_meta.get("_slice_dropped") or [],
        "selected_slice_count": int(route_meta.get("_slice_selected_count") or 0),
        "dropped_slice_count": dropped_slice_count,
        "dropped_conflict_count": dropped_conflict_count,
        "selected_layers": selected_layers,
        "selected_layer_counts": selected_layer_counts,
        "recovery_hit": bool(route_meta.get("_slice_recovery_hit")),
        "prefix_hash": str(route_meta.get("_slice_prefix_hash") or ""),
        "tail_hash": str(route_meta.get("_slice_tail_hash") or ""),
        "prefix_cache_hit": bool(route_meta.get("_slice_prefix_cache_hit")),
        "block1_cache_hit": bool(route_meta.get("_slice_block1_cache_hit")),
        "block2_cache_hit": bool(route_meta.get("_slice_block2_cache_hit")),
        "token_budget_before": int(route_meta.get("_slice_token_budget_before") or 0),
        "token_budget_after": int(route_meta.get("_slice_token_budget_after") or 0),
        "model_tier": str(route_meta.get("_slice_model_tier") or decision.get("selected_model_tier") or ""),
        "model_id": str(route_meta.get("_slice_model_id") or ""),
        "path_b_clarify_turns": int(route_meta.get("path_b_clarify_turns") or 0),
        "path_b_clarify_limit": int(route_meta.get("path_b_clarify_limit") or _CHAT_ROUTE_PATH_B_CLARIFY_LIMIT),
        "path_b_clarify_limit_override": route_meta.get("path_b_clarify_limit_override"),
        "path_b_budget_escalated": bool(route_meta.get("path_b_budget_escalated")),
        "path_b_budget_reason": str(route_meta.get("path_b_budget_reason") or ""),
        "route_quality_guard_status": _ops_status_to_severity(str(route_meta.get("route_quality_guard_status") or "unknown")),
        "route_quality_guard_applied": bool(route_meta.get("route_quality_guard_applied")),
        "route_quality_guard_action": str(route_meta.get("route_quality_guard_action") or ""),
        "route_quality_guard_reason": str(route_meta.get("route_quality_guard_reason") or ""),
        "route_quality_guard_reason_codes": _sanitize_route_quality_reason_codes(
            route_meta.get("route_quality_guard_reason_codes")
        ),
        "route_quality_guard_path_before": str(route_meta.get("route_quality_guard_path_before") or ""),
        "route_quality_guard_path_after": str(route_meta.get("route_quality_guard_path_after") or ""),
        "route_quality_guard_evaluated_at": str(route_meta.get("route_quality_guard_evaluated_at") or ""),
        "route_quality_guard_trend_status": _ops_status_to_severity(
            str(route_meta.get("route_quality_guard_trend_status") or "unknown")
        ),
        "route_quality_guard_trend_direction": str(route_meta.get("route_quality_guard_trend_direction") or "unknown"),
        "route_quality_guard_trend_sample_count": int(route_meta.get("route_quality_guard_trend_sample_count") or 0),
        "router_arbiter_status": _ops_status_to_severity(str(route_meta.get("router_arbiter_status") or "unknown")),
        "router_arbiter_applied": bool(route_meta.get("router_arbiter_applied")),
        "router_arbiter_action": str(route_meta.get("router_arbiter_action") or ""),
        "router_arbiter_reason": str(route_meta.get("router_arbiter_reason") or ""),
        "router_arbiter_reason_codes": _sanitize_router_arbiter_reason_codes(
            route_meta.get("router_arbiter_reason_codes")
        ),
        "router_arbiter_path_before": str(route_meta.get("router_arbiter_path_before") or ""),
        "router_arbiter_path_after": str(route_meta.get("router_arbiter_path_after") or ""),
        "router_arbiter_delegate_turns": int(route_meta.get("router_arbiter_delegate_turns") or 0),
        "router_arbiter_max_delegate_turns": int(
            route_meta.get("router_arbiter_max_delegate_turns") or _router_arbiter_max_delegate_turns()
        ),
        "router_arbiter_conflict_ticket": str(route_meta.get("router_arbiter_conflict_ticket") or ""),
        "router_arbiter_freeze": bool(route_meta.get("router_arbiter_freeze")),
        "router_arbiter_hitl": bool(route_meta.get("router_arbiter_hitl")),
        "router_arbiter_escalated": bool(route_meta.get("router_arbiter_escalated")),
        "outer_session_id": str(route_meta.get("outer_session_id") or ""),
        "core_session_id": str(route_meta.get("core_session_id") or ""),
        "execution_session_id": str(route_meta.get("execution_session_id") or ""),
        "core_session_created": bool(route_meta.get("core_session_created")),
    }


def _emit_chat_route_prompt_event(route_meta: Dict[str, Any], *, session_id: str) -> None:
    store = _get_chat_route_event_store()
    if store is None:
        return

    payload = _build_chat_route_prompt_event_payload(route_meta)
    decision = route_meta.get("router_decision") if isinstance(route_meta.get("router_decision"), dict) else {}
    payload["session_id"] = str(session_id or "")
    payload["trace_id"] = str(decision.get("trace_id") or "")
    payload["workflow_id"] = str(decision.get("task_id") or "")
    store.emit("PromptInjectionComposed", payload, source="apiserver.chat_stream")


def _emit_chat_route_guard_event(route_meta: Dict[str, Any], *, session_id: str) -> None:
    if not bool(route_meta.get("route_quality_guard_applied")):
        return

    store = _get_chat_route_event_store()
    if store is None:
        return

    guard_status = _ops_status_to_severity(str(route_meta.get("route_quality_guard_status") or "unknown"))
    if guard_status == "critical":
        event_type = "RouteQualityGuardEscalatedCritical"
    elif guard_status == "warning":
        event_type = "RouteQualityGuardEscalatedWarning"
    else:
        return

    decision = route_meta.get("router_decision") if isinstance(route_meta.get("router_decision"), dict) else {}
    payload = {
        "session_id": str(session_id or ""),
        "trace_id": str(decision.get("trace_id") or ""),
        "workflow_id": str(decision.get("task_id") or ""),
        "path_before": str(route_meta.get("route_quality_guard_path_before") or ""),
        "path_after": str(route_meta.get("route_quality_guard_path_after") or route_meta.get("path") or ""),
        "final_path": str(route_meta.get("path") or ""),
        "risk_level": str(route_meta.get("risk_level") or ""),
        "route_quality_guard_status": guard_status,
        "route_quality_guard_action": str(route_meta.get("route_quality_guard_action") or ""),
        "route_quality_guard_reason": str(route_meta.get("route_quality_guard_reason") or ""),
        "route_quality_guard_reason_codes": _sanitize_route_quality_reason_codes(
            route_meta.get("route_quality_guard_reason_codes")
        ),
        "route_quality_guard_evaluated_at": str(route_meta.get("route_quality_guard_evaluated_at") or ""),
        "outer_session_id": str(route_meta.get("outer_session_id") or ""),
        "core_session_id": str(route_meta.get("core_session_id") or ""),
        "execution_session_id": str(route_meta.get("execution_session_id") or ""),
    }
    store.emit(event_type, payload, source="apiserver.chat_stream")


def _emit_chat_route_arbiter_event(route_meta: Dict[str, Any], *, session_id: str) -> None:
    if not bool(route_meta.get("router_arbiter_applied")):
        return

    store = _get_chat_route_event_store()
    if store is None:
        return

    arbiter_status = _ops_status_to_severity(str(route_meta.get("router_arbiter_status") or "unknown"))
    if arbiter_status == "critical":
        event_type = "RouteArbiterGuardEscalatedCritical"
    elif arbiter_status == "warning":
        event_type = "RouteArbiterGuardEscalatedWarning"
    else:
        return

    decision = route_meta.get("router_decision") if isinstance(route_meta.get("router_decision"), dict) else {}
    payload = {
        "session_id": str(session_id or ""),
        "trace_id": str(decision.get("trace_id") or ""),
        "workflow_id": str(decision.get("task_id") or ""),
        "path_before": str(route_meta.get("router_arbiter_path_before") or ""),
        "path_after": str(route_meta.get("router_arbiter_path_after") or route_meta.get("path") or ""),
        "final_path": str(route_meta.get("path") or ""),
        "risk_level": str(route_meta.get("risk_level") or ""),
        "router_arbiter_status": arbiter_status,
        "router_arbiter_action": str(route_meta.get("router_arbiter_action") or ""),
        "router_arbiter_reason": str(route_meta.get("router_arbiter_reason") or ""),
        "router_arbiter_reason_codes": _sanitize_router_arbiter_reason_codes(
            route_meta.get("router_arbiter_reason_codes")
        ),
        "router_arbiter_conflict_ticket": str(route_meta.get("router_arbiter_conflict_ticket") or ""),
        "router_arbiter_delegate_turns": int(route_meta.get("router_arbiter_delegate_turns") or 0),
        "router_arbiter_max_delegate_turns": int(
            route_meta.get("router_arbiter_max_delegate_turns") or _router_arbiter_max_delegate_turns()
        ),
        "router_arbiter_freeze": bool(route_meta.get("router_arbiter_freeze")),
        "router_arbiter_hitl": bool(route_meta.get("router_arbiter_hitl")),
        "router_arbiter_escalated": bool(route_meta.get("router_arbiter_escalated")),
        "outer_session_id": str(route_meta.get("outer_session_id") or ""),
        "core_session_id": str(route_meta.get("core_session_id") or ""),
        "execution_session_id": str(route_meta.get("execution_session_id") or ""),
    }
    store.emit(event_type, payload, source="apiserver.chat_stream")


def _emit_agentic_loop_completion_event(
    *,
    session_id: str,
    execution_session_id: str,
    route_meta: Dict[str, Any],
    chunk_data: Dict[str, Any],
) -> None:
    if not isinstance(chunk_data, dict):
        return
    if str(chunk_data.get("type") or "").strip().lower() != "tool_stage":
        return
    if str(chunk_data.get("phase") or "").strip().lower() != "verify":
        return

    reason = str(chunk_data.get("reason") or "").strip().lower()
    if reason == "submitted_completion":
        event_type = "AgenticLoopCompletionSubmitted"
    elif reason == "completion_not_submitted":
        event_type = "AgenticLoopCompletionNotSubmitted"
    else:
        return

    store = _get_chat_route_event_store()
    if store is None:
        return

    decision = route_meta.get("router_decision") if isinstance(route_meta.get("router_decision"), dict) else {}
    details = chunk_data.get("details") if isinstance(chunk_data.get("details"), dict) else {}
    payload = {
        "session_id": str(session_id or ""),
        "execution_session_id": str(execution_session_id or ""),
        "outer_session_id": str(route_meta.get("outer_session_id") or ""),
        "core_session_id": str(route_meta.get("core_session_id") or ""),
        "trace_id": str(decision.get("trace_id") or ""),
        "workflow_id": str(decision.get("task_id") or ""),
        "path": str(route_meta.get("path") or ""),
        "status": str(chunk_data.get("status") or ""),
        "reason": str(chunk_data.get("reason") or ""),
        "decision": str(chunk_data.get("decision") or ""),
        "round": int(chunk_data.get("round") or 0),
        "task_completed": bool(details.get("task_completed") is True),
        "submit_result_called": bool(details.get("submit_result_called") is True),
        "submit_result_round": int(details.get("submit_result_round") or 0),
    }
    store.emit(event_type, payload, source="apiserver.chat_stream")


def _extract_agentic_execution_receipt_text(chunk_data: Dict[str, Any]) -> str:
    """Extract user-facing completion text from structured agentic execution receipt."""
    if not isinstance(chunk_data, dict):
        return ""
    if str(chunk_data.get("type") or "").strip().lower() != "execution_receipt":
        return ""
    agent_state = chunk_data.get("agent_state")
    if not isinstance(agent_state, dict):
        return ""

    final_answer = str(agent_state.get("final_answer") or "").strip()
    if final_answer:
        return final_answer

    completion_summary = str(agent_state.get("completion_summary") or "").strip()
    if completion_summary:
        return completion_summary

    deliverables = agent_state.get("deliverables")
    if isinstance(deliverables, list):
        cleaned = [str(item).strip() for item in deliverables if str(item).strip()]
        if cleaned:
            return "\n".join(cleaned[:8])

    return ""


def _read_chat_route_event_rows(*, limit: int = 2000) -> List[Dict[str, Any]]:
    override = _CHAT_RUNTIME_CONTEXT.get("event_rows_reader")
    if callable(override):
        try:
            rows = override(limit=limit)
            if isinstance(rows, list):
                return rows
        except Exception:
            pass

    event_file = Path(__file__).resolve().parent.parent / "logs" / "autonomous" / "events.jsonl"
    if not event_file.exists() or limit <= 0:
        return []
    try:
        lines = event_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []

    rows: List[Dict[str, Any]] = []
    for line in lines[-max(1, int(limit)) :]:
        text = str(line or "").strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _collect_chat_route_bridge_events(*, session_ids: List[str], limit: int = 20) -> List[Dict[str, Any]]:
    ids = {str(item or "").strip() for item in session_ids if str(item or "").strip()}
    if not ids:
        return []

    rows = _read_chat_route_event_rows(limit=max(200, int(limit) * 200))
    matched: List[Dict[str, Any]] = []
    for row in reversed(rows):
        if str(row.get("event_type") or "").strip() != "PromptInjectionComposed":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue

        outer_session_id = str(payload.get("outer_session_id") or payload.get("session_id") or "").strip()
        core_session_id = str(payload.get("core_session_id") or "").strip()
        execution_session_id = str(payload.get("execution_session_id") or "").strip()
        event_session_ids = {sid for sid in (outer_session_id, core_session_id, execution_session_id) if sid}
        if not (event_session_ids & ids):
            continue

        matched.append(
            {
                "timestamp": str(row.get("timestamp") or ""),
                "event_type": "PromptInjectionComposed",
                "path": str(payload.get("path") or ""),
                "trigger": str(payload.get("trigger") or ""),
                "delegation_intent": str(payload.get("delegation_intent") or ""),
                "prompt_profile": str(payload.get("prompt_profile") or ""),
                "injection_mode": str(payload.get("injection_mode") or ""),
                "outer_session_id": outer_session_id,
                "core_session_id": core_session_id,
                "execution_session_id": execution_session_id,
                "path_b_budget_escalated": bool(payload.get("path_b_budget_escalated")),
                "path_b_budget_reason": str(payload.get("path_b_budget_reason") or ""),
                "path_b_clarify_turns": int(payload.get("path_b_clarify_turns") or 0),
                "path_b_clarify_limit": int(payload.get("path_b_clarify_limit") or _CHAT_ROUTE_PATH_B_CLARIFY_LIMIT),
                "path_b_clarify_limit_override": payload.get("path_b_clarify_limit_override"),
                "route_quality_guard_status": _ops_status_to_severity(
                    str(payload.get("route_quality_guard_status") or "unknown")
                ),
                "route_quality_guard_applied": bool(payload.get("route_quality_guard_applied")),
                "route_quality_guard_action": str(payload.get("route_quality_guard_action") or ""),
                "route_quality_guard_reason": str(payload.get("route_quality_guard_reason") or ""),
                "route_quality_guard_reason_codes": _sanitize_route_quality_reason_codes(
                    payload.get("route_quality_guard_reason_codes")
                ),
                "route_quality_guard_path_before": str(payload.get("route_quality_guard_path_before") or ""),
                "route_quality_guard_path_after": str(payload.get("route_quality_guard_path_after") or ""),
                "router_arbiter_status": _ops_status_to_severity(
                    str(payload.get("router_arbiter_status") or "unknown")
                ),
                "router_arbiter_applied": bool(payload.get("router_arbiter_applied")),
                "router_arbiter_action": str(payload.get("router_arbiter_action") or ""),
                "router_arbiter_reason": str(payload.get("router_arbiter_reason") or ""),
                "router_arbiter_reason_codes": _sanitize_router_arbiter_reason_codes(
                    payload.get("router_arbiter_reason_codes")
                ),
                "router_arbiter_path_before": str(payload.get("router_arbiter_path_before") or ""),
                "router_arbiter_path_after": str(payload.get("router_arbiter_path_after") or ""),
                "router_arbiter_delegate_turns": int(payload.get("router_arbiter_delegate_turns") or 0),
                "router_arbiter_max_delegate_turns": int(
                    payload.get("router_arbiter_max_delegate_turns") or _router_arbiter_max_delegate_turns()
                ),
                "router_arbiter_conflict_ticket": str(payload.get("router_arbiter_conflict_ticket") or ""),
                "router_arbiter_freeze": bool(payload.get("router_arbiter_freeze")),
                "router_arbiter_hitl": bool(payload.get("router_arbiter_hitl")),
                "router_arbiter_escalated": bool(payload.get("router_arbiter_escalated")),
                "core_session_created": bool(payload.get("core_session_created")),
                "source": str(row.get("source") or ""),
            }
        )
        if len(matched) >= max(1, int(limit)):
            break
    matched.reverse()
    return matched


def _build_chat_route_bridge_payload(session_id: str, *, limit: int = 20) -> Dict[str, Any]:
    session = _get_message_manager().get_session(session_id)
    if not isinstance(session, dict):
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")

    state = _ensure_chat_route_state(session_id)
    core_session_id = str(state.get("core_session_id") or "").strip()
    execution_session_id = str(state.get("last_execution_session_id") or session_id)
    session_ids = [session_id]
    if core_session_id:
        session_ids.append(core_session_id)
    route_events = _collect_chat_route_bridge_events(session_ids=session_ids, limit=max(1, int(limit)))

    return {
        "status": "success",
        "outer_session_id": str(session_id),
        "core_session_id": core_session_id,
        "execution_session_id": execution_session_id,
        "outer_session_exists": True,
        "core_session_exists": bool(core_session_id and _get_message_manager().get_session(core_session_id)),
        "state": {
            "path_b_clarify_turns": int(state.get("path_b_clarify_turns") or 0),
            "path_b_clarify_limit": _CHAT_ROUTE_PATH_B_CLARIFY_LIMIT,
            "last_execution_session_id": execution_session_id,
            "last_core_escalation_at_ms": int(state.get("last_core_escalation_at_ms") or 0),
        },
        "recent_route_events": route_events,
    }


def _format_sse_payload_chunk_json(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
