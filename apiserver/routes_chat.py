"""Chat-route domain — extracted from api_server.py (Phase 2).

Contains:
- Shell/Core route session state helpers
- Route-event emission and observability payload helpers
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

from agents.prompt_engine import PromptAssembler, PromptBlockNotFoundError, get_system_prompts_root
from agents.router_arbiter_guard import RouterArbiterGuard
from agents.llm_gateway import LLMGateway
from core.event_bus import EventStore
from apiserver.message_manager import message_manager as _default_message_manager
from agents.contract_runtime import trim_contract_text as trim_brain_contract_text
from apiserver.routes_ops import (
    _ops_build_route_quality_summary,
    _ops_build_route_quality_trend,
    _ops_repo_root,
    _ops_status_to_severity,
    _ops_utc_iso_now,
)

logger = logging.getLogger(__name__)
_ROUTE_PROMPT_ASSEMBLER = PromptAssembler(prompts_root=str(get_system_prompts_root()))
_CHAT_RUNTIME_CONTEXT: Dict[str, Any] = {
    "message_manager": None,
    "message_manager_getter": None,
    "config_getter": None,
    "route_arbiter_guard": None,
    "route_arbiter_guard_getter": None,
    "agent_session_store": None,
    "agent_session_store_getter": None,
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
    agent_session_store: Any = None,
    agent_session_store_getter: Any = None,
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
    if agent_session_store is not None:
        _CHAT_RUNTIME_CONTEXT["agent_session_store"] = agent_session_store
    if agent_session_store_getter is not None:
        _CHAT_RUNTIME_CONTEXT["agent_session_store_getter"] = agent_session_store_getter
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


def _get_agent_session_store() -> Any:
    getter = _CHAT_RUNTIME_CONTEXT.get("agent_session_store_getter")
    if callable(getter):
        try:
            injected = getter()
            if injected is not None:
                return injected
        except Exception:
            return None
    return _CHAT_RUNTIME_CONTEXT.get("agent_session_store")


def _empty_descendant_heartbeat_snapshot(root_session_id: str) -> Dict[str, Any]:
    return {
        "root_session_id": str(root_session_id or ""),
        "summary": {
            "root_session_id": str(root_session_id or ""),
            "session_count": 0,
            "sessions_with_heartbeats": 0,
            "task_count": 0,
            "fresh_count": 0,
            "warning_count": 0,
            "critical_count": 0,
            "blocked_count": 0,
            "max_stale_level": "none",
            "latest_generated_at": "",
            "latest_expires_at": "",
            "has_stale": False,
            "has_blocked": False,
        },
        "sessions": [],
        "heartbeats": [],
    }


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
    "_CHAT_ROUTE_GUARD_CACHE",
    "_CHAT_ROUTE_GUARD_CACHE_TTL_MS",
    "_CHAT_ROUTE_SHELL_CLARIFY_LIMIT",
    "_CHAT_ROUTE_STATE_KEY",
    "_apply_shell_core_session_state",
    "_build_chat_route_session_state_payload",
    "_build_chat_route_prompt_event_payload",
    "_build_chat_route_prompt_hints",
    "_build_chat_route_quality_guard_summary",
    "_bind_chat_runtime_context",
    "_build_route_model_override",
    "_collect_chat_route_session_state_events",
    "_emit_agentic_loop_completion_event",
    "_emit_core_child_spawn_deferred_event",
    "_emit_chat_route_arbiter_event",
    "_emit_chat_route_guard_event",
    "_emit_chat_route_prompt_event",
    "_ensure_chat_route_state",
    "_extract_agentic_execution_receipt_text",
    "_format_sse_payload_chunk_json",
    "_get_chat_route_event_store",
    "_get_chat_route_quality_guard_summary",
    "_merge_model_override",
    "_merge_route_quality_reason_codes",
    "_normalize_chat_text",
    "_read_chat_route_event_rows",
    "_sanitize_route_quality_reason_codes",
    "_sanitize_router_arbiter_reason_codes",
    "_trim_contract_text",
]

# ── Chat-route constants ──────────────────────────────────────
try:
    _CHAT_LLM_GATEWAY: Optional[LLMGateway] = LLMGateway()
except Exception:
    _CHAT_LLM_GATEWAY = None
_CHAT_ROUTE_EVENT_STORE: Optional[EventStore] = None
_CHAT_ROUTE_STATE_KEY = "_chat_route_state"
_CHAT_ROUTE_SHELL_CLARIFY_LIMIT = 1
_CHAT_ROUTE_GUARD_CACHE_TTL_MS = 5_000
_CHAT_ROUTE_GUARD_CACHE: Dict[str, Any] = {"expires_at_ms": 0, "summary": {}}
_CHAT_ROUTE_ARBITER_GUARD = RouterArbiterGuard(max_delegate_turns=3)

# ── Chat-route functions ─────────────────────────────────────
def _normalize_chat_text(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _normalize_route_semantic(route_semantic: Any) -> str:
    normalized = str(route_semantic or "").strip().lower()
    if normalized in {"shell_readonly", "shell_clarify", "core_execution"}:
        return normalized
    return "core_execution"


def _derive_route_semantic(route_meta: Dict[str, Any]) -> Dict[str, Any]:
    normalized_route_semantic = _normalize_route_semantic(route_meta.get("route_semantic"))
    if normalized_route_semantic == "core_execution":
        route_semantic = "core_execution"
        active_agent = "core"
        dispatch_to_core = True
    elif normalized_route_semantic == "shell_clarify":
        route_semantic = "shell_clarify"
        active_agent = "shell"
        dispatch_to_core = False
    else:
        route_semantic = "shell_readonly"
        active_agent = "shell"
        dispatch_to_core = False

    decision = route_meta.get("router_decision") if isinstance(route_meta.get("router_decision"), dict) else {}
    core_execution_route = str(
        route_meta.get("core_execution_route")
        or route_meta.get("core_route")
        or decision.get("core_route")
        or ""
    ).strip()
    if route_semantic != "core_execution":
        core_execution_route = ""

    return {
        "route_semantic": route_semantic,
        "active_agent": active_agent,
        "dispatch_to_core": dispatch_to_core,
        "handoff_tool": "dispatch_to_core" if dispatch_to_core else "",
        "core_execution_route": core_execution_route,
    }


def _apply_route_semantic_fields(route_meta: Dict[str, Any]) -> Dict[str, Any]:
    semantic = _derive_route_semantic(route_meta)
    route_meta["entry_agent"] = "shell"
    route_meta["route_semantic"] = str(semantic.get("route_semantic") or "shell_readonly")
    route_meta["active_agent"] = str(semantic.get("active_agent") or "shell")
    route_meta["dispatch_to_core"] = bool(semantic.get("dispatch_to_core"))
    route_meta["handoff_tool"] = str(semantic.get("handoff_tool") or "")
    core_execution_route = str(
        route_meta.get("core_execution_route")
        or semantic.get("core_execution_route")
        or ""
    ).strip()
    if core_execution_route:
        route_meta["core_execution_route"] = core_execution_route
    route_meta["shell_session_id"] = str(route_meta.get("shell_session_id") or "")
    route_meta["core_execution_session_id"] = str(route_meta.get("core_execution_session_id") or "")
    return route_meta


def _ensure_chat_route_state(session_id: str) -> Dict[str, Any]:
    session = _get_message_manager().get_session(session_id)
    if not isinstance(session, dict):
        return {"shell_clarify_turns": 0}
    state = session.get(_CHAT_ROUTE_STATE_KEY)
    if not isinstance(state, dict):
        state = {"shell_clarify_turns": 0}
        session[_CHAT_ROUTE_STATE_KEY] = state
    try:
        state["shell_clarify_turns"] = max(0, int(state.get("shell_clarify_turns", 0)))
    except Exception:
        state["shell_clarify_turns"] = 0

    core_execution_session_id = str(state.get("core_execution_session_id") or "").strip()
    fallback_route_semantic = "core_execution" if core_execution_session_id else "shell_readonly"
    state["last_route_semantic"] = _normalize_route_semantic(state.get("last_route_semantic") or fallback_route_semantic)
    state["last_active_agent"] = str(
        state.get("last_active_agent")
        or ("core" if state["last_route_semantic"] == "core_execution" else "shell")
    ).strip()
    state["last_dispatch_to_core"] = bool(
        state.get("last_dispatch_to_core")
        if state.get("last_dispatch_to_core") is not None
        else state["last_route_semantic"] == "core_execution"
    )
    state["last_handoff_tool"] = str(
        state.get("last_handoff_tool")
        or ("dispatch_to_core" if state["last_dispatch_to_core"] else "")
    ).strip()
    state["last_core_execution_route"] = str(state.get("last_core_execution_route") or "").strip()
    state["last_risk_level"] = str(
        state.get("last_risk_level")
        or ("write_repo" if state["last_route_semantic"] == "core_execution" else "read_only")
    ).strip()
    state["last_core_execution_session_id"] = str(
        state.get("last_core_execution_session_id") or core_execution_session_id
    ).strip()
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


def _persist_chat_route_snapshot_state(state: Dict[str, Any], route_meta: Dict[str, Any]) -> None:
    state["last_route_semantic"] = _normalize_route_semantic(route_meta.get("route_semantic"))
    state["last_active_agent"] = str(route_meta.get("active_agent") or "").strip()
    state["last_dispatch_to_core"] = bool(route_meta.get("dispatch_to_core"))
    state["last_handoff_tool"] = str(route_meta.get("handoff_tool") or "").strip()
    state["last_core_execution_route"] = str(route_meta.get("core_execution_route") or "").strip()
    state["last_risk_level"] = str(route_meta.get("risk_level") or state.get("last_risk_level") or "").strip()
    if str(state.get("core_execution_session_id") or "").strip():
        state["last_core_execution_session_id"] = str(state.get("core_execution_session_id") or "").strip()


def _apply_shell_core_session_state(route_meta: Dict[str, Any], *, shell_session_id: str) -> Dict[str, Any]:
    state = _ensure_chat_route_state(shell_session_id)
    route_semantic = _normalize_route_semantic(route_meta.get("route_semantic"))
    route_meta["route_semantic"] = route_semantic
    route_meta["shell_session_id"] = str(shell_session_id or "")
    route_meta["core_execution_session_id"] = str(state.get("core_execution_session_id") or "")
    route_meta["core_execution_session_created"] = False

    if route_semantic != "core_execution":
        existing_core_execution_session_id = str(state.get("core_execution_session_id") or "").strip()
        if existing_core_execution_session_id:
            state["last_core_execution_session_id"] = existing_core_execution_session_id
        applied = _apply_route_semantic_fields(route_meta)
        _persist_chat_route_snapshot_state(state, applied)
        return applied

    core_execution_session_id = str(state.get("core_execution_session_id") or "").strip()
    core_execution_session_created = False
    if not core_execution_session_id:
        core_execution_session_id = f"{str(shell_session_id or '')}__core"
    if not _get_message_manager().get_session(core_execution_session_id):
        shell_session = _get_message_manager().get_session(shell_session_id) or {}
        temporary = bool(shell_session.get("temporary", False))
        _get_message_manager().create_session(session_id=core_execution_session_id, temporary=temporary)
        core_execution_session_created = True

    state["core_execution_session_id"] = core_execution_session_id
    state["last_core_escalation_at_ms"] = int(time.time() * 1000)
    state["last_core_execution_session_id"] = core_execution_session_id

    route_meta["core_execution_session_id"] = core_execution_session_id
    route_meta["core_execution_session_created"] = core_execution_session_created
    applied = _apply_route_semantic_fields(route_meta)
    _persist_chat_route_snapshot_state(state, applied)
    return applied


def _build_route_model_override(route_semantic: str) -> Optional[Dict[str, str]]:
    """Build route-scoped LLM override for shell/core execution routes."""
    normalized_route_semantic = _normalize_route_semantic(route_semantic)
    target_key = "core" if normalized_route_semantic == "core_execution" else "shell"
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


def _render_chat_route_prompt_block(block_path: str, *, variables: Optional[Dict[str, Any]] = None) -> str:
    try:
        return _ROUTE_PROMPT_ASSEMBLER.render_block(block_path, variables=variables).strip()
    except PromptBlockNotFoundError:
        logger.warning("Chat route prompt block missing: %s", block_path)
        return ""


def _build_chat_route_prompt_hints(route_meta: Dict[str, Any]) -> str:
    route_semantic = _normalize_route_semantic(route_meta.get("route_semantic"))
    semantic = _derive_route_semantic(route_meta)
    decision = route_meta.get("router_decision") if isinstance(route_meta.get("router_decision"), dict) else {}
    dispatch_to_core = bool(
        route_meta.get("dispatch_to_core")
        if route_meta.get("dispatch_to_core") is not None
        else semantic.get("dispatch_to_core")
    )
    lines = [
        _render_chat_route_prompt_block(
            "agents/shell/blocks/shell_route_decision_base.md",
            variables={
                "route_semantic": route_semantic,
                "entry_agent": str(route_meta.get("entry_agent") or "shell"),
                "active_agent": str(route_meta.get("active_agent") or semantic.get("active_agent") or ""),
                "dispatch_to_core": dispatch_to_core,
                "prompt_profile": str(decision.get("prompt_profile") or ""),
                "injection_mode": str(decision.get("injection_mode") or ""),
                "delegation_intent": str(decision.get("delegation_intent") or ""),
            },
        )
    ]
    if bool(route_meta.get("route_quality_guard_applied")):
        lines.append(
            _render_chat_route_prompt_block(
                "agents/shell/blocks/shell_route_quality_guard.md",
                variables={
                    "route_quality_guard": (
                        f"{_ops_status_to_severity(str(route_meta.get('route_quality_guard_status') or 'unknown'))}:"
                        f"{str(route_meta.get('route_quality_guard_action') or 'none')}"
                    )
                },
            )
        )
    router_arbiter_status = _ops_status_to_severity(str(route_meta.get("router_arbiter_status") or "unknown"))
    if router_arbiter_status in {"warning", "critical"}:
        lines.append(
            _render_chat_route_prompt_block(
                "agents/shell/blocks/shell_router_arbiter_guard.md",
                variables={
                    "router_arbiter_guard": (
                        f"{router_arbiter_status}:{str(route_meta.get('router_arbiter_action') or 'none')}"
                    )
                },
            )
        )

    if route_semantic == "shell_readonly":
        lines.append(_render_chat_route_prompt_block("agents/shell/blocks/shell_route_policy_readonly.md"))
        available_tool_names_raw = route_meta.get("_shell_available_tool_names")
        available_tool_names: List[str] = []
        if isinstance(available_tool_names_raw, list):
            for item in available_tool_names_raw:
                text = str(item or "").strip()
                if text:
                    available_tool_names.append(text)
        available_tool_count = int(
            route_meta.get("_shell_available_tool_count") or len(available_tool_names)
        )
        if available_tool_names or available_tool_count > 0:
            lines.append(
                _render_chat_route_prompt_block(
                    "agents/shell/blocks/shell_runtime_available_tools.md",
                    variables={
                        "available_tool_count": available_tool_count,
                        "available_tool_names": ", ".join(available_tool_names) or "none",
                    },
                )
            )
    elif route_semantic == "shell_clarify":
        lines.append(_render_chat_route_prompt_block("agents/shell/blocks/shell_route_policy_clarify.md"))
    else:
        lines.append(_render_chat_route_prompt_block("agents/shell/blocks/shell_route_policy_core_execution.md"))
    return "\n".join(line for line in lines if str(line).strip())


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
    route_semantic = _normalize_route_semantic(route_meta.get("route_semantic"))
    semantic = _derive_route_semantic(route_meta)
    dispatch_to_core = bool(
        route_meta.get("dispatch_to_core")
        if route_meta.get("dispatch_to_core") is not None
        else semantic.get("dispatch_to_core")
    )
    delegation_intent = str(decision.get("delegation_intent") or "").strip()
    selected_layers = route_meta.get("_slice_selected_layers") or []
    selected_layer_counts = route_meta.get("_slice_selected_layer_counts") or {}
    dropped_slice_count = int(route_meta.get("_slice_dropped_count") or 0)
    dropped_conflict_count = int(route_meta.get("_slice_dropped_conflict_count") or dropped_slice_count)
    return {
        "task_type": str(decision.get("task_type") or ""),
        "severity": str(route_meta.get("risk_level") or ""),
        "trigger": route_semantic,
        "route_semantic": str(route_meta.get("route_semantic") or semantic.get("route_semantic") or route_semantic),
        "entry_agent": str(route_meta.get("entry_agent") or "shell"),
        "active_agent": str(route_meta.get("active_agent") or semantic.get("active_agent") or ""),
        "dispatch_to_core": dispatch_to_core,
        "handoff_tool": str(route_meta.get("handoff_tool") or semantic.get("handoff_tool") or ""),
        "core_execution_route": str(route_meta.get("core_execution_route") or decision.get("core_route") or ""),
        "prompt_profile": str(decision.get("prompt_profile") or ""),
        "injection_mode": str(decision.get("injection_mode") or ""),
        "delegation_intent": delegation_intent,
        "delegation_hit": delegation_intent.lower().startswith("delegate"),
        "shell_readonly_hit": bool(route_meta.get("shell_readonly_hit")),
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
        "shell_clarify_turns": int(route_meta.get("shell_clarify_turns") or 0),
        "shell_clarify_limit": int(route_meta.get("shell_clarify_limit") or _CHAT_ROUTE_SHELL_CLARIFY_LIMIT),
        "shell_clarify_limit_override": route_meta.get("shell_clarify_limit_override"),
        "shell_clarify_budget_escalated": bool(route_meta.get("shell_clarify_budget_escalated")),
        "shell_clarify_budget_reason": str(route_meta.get("shell_clarify_budget_reason") or ""),
        "route_quality_guard_status": _ops_status_to_severity(str(route_meta.get("route_quality_guard_status") or "unknown")),
        "route_quality_guard_applied": bool(route_meta.get("route_quality_guard_applied")),
        "route_quality_guard_action": str(route_meta.get("route_quality_guard_action") or ""),
        "route_quality_guard_reason": str(route_meta.get("route_quality_guard_reason") or ""),
        "route_quality_guard_reason_codes": _sanitize_route_quality_reason_codes(
            route_meta.get("route_quality_guard_reason_codes")
        ),
        "route_quality_guard_route_semantic_before": str(route_meta.get("route_quality_guard_route_semantic_before") or ""),
        "route_quality_guard_route_semantic_after": str(route_meta.get("route_quality_guard_route_semantic_after") or ""),
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
        "router_arbiter_route_semantic_before": str(route_meta.get("router_arbiter_route_semantic_before") or ""),
        "router_arbiter_route_semantic_after": str(route_meta.get("router_arbiter_route_semantic_after") or ""),
        "router_arbiter_delegate_turns": int(route_meta.get("router_arbiter_delegate_turns") or 0),
        "router_arbiter_max_delegate_turns": int(
            route_meta.get("router_arbiter_max_delegate_turns") or _router_arbiter_max_delegate_turns()
        ),
        "router_arbiter_conflict_ticket": str(route_meta.get("router_arbiter_conflict_ticket") or ""),
        "router_arbiter_freeze": bool(route_meta.get("router_arbiter_freeze")),
        "router_arbiter_hitl": bool(route_meta.get("router_arbiter_hitl")),
        "router_arbiter_escalated": bool(route_meta.get("router_arbiter_escalated")),
        "shell_session_id": str(route_meta.get("shell_session_id") or ""),
        "core_execution_session_id": str(route_meta.get("core_execution_session_id") or ""),
        "core_execution_session_created": bool(route_meta.get("core_execution_session_created")),
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
        "route_semantic_before": str(route_meta.get("route_quality_guard_route_semantic_before") or ""),
        "route_semantic_after": str(
            route_meta.get("route_quality_guard_route_semantic_after")
            or route_meta.get("route_semantic")
            or ""
        ),
        "final_route_semantic": str(route_meta.get("route_semantic") or ""),
        "risk_level": str(route_meta.get("risk_level") or ""),
        "route_quality_guard_status": guard_status,
        "route_quality_guard_action": str(route_meta.get("route_quality_guard_action") or ""),
        "route_quality_guard_reason": str(route_meta.get("route_quality_guard_reason") or ""),
        "route_quality_guard_reason_codes": _sanitize_route_quality_reason_codes(
            route_meta.get("route_quality_guard_reason_codes")
        ),
        "route_quality_guard_evaluated_at": str(route_meta.get("route_quality_guard_evaluated_at") or ""),
        "shell_session_id": str(route_meta.get("shell_session_id") or ""),
        "core_execution_session_id": str(route_meta.get("core_execution_session_id") or ""),
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
        "route_semantic_before": str(route_meta.get("router_arbiter_route_semantic_before") or ""),
        "route_semantic_after": str(
            route_meta.get("router_arbiter_route_semantic_after")
            or route_meta.get("route_semantic")
            or ""
        ),
        "final_route_semantic": str(route_meta.get("route_semantic") or ""),
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
        "shell_session_id": str(route_meta.get("shell_session_id") or ""),
        "core_execution_session_id": str(route_meta.get("core_execution_session_id") or ""),
    }
    store.emit(event_type, payload, source="apiserver.chat_stream")


def _emit_agentic_loop_completion_event(
    *,
    session_id: str,
    core_execution_session_id: str,
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
        "shell_session_id": str(route_meta.get("shell_session_id") or ""),
        "core_execution_session_id": str(core_execution_session_id or ""),
        "trace_id": str(decision.get("trace_id") or ""),
        "workflow_id": str(decision.get("task_id") or ""),
        "route_semantic": str(route_meta.get("route_semantic") or ""),
        "status": str(chunk_data.get("status") or ""),
        "reason": str(chunk_data.get("reason") or ""),
        "decision": str(chunk_data.get("decision") or ""),
        "round": int(chunk_data.get("round") or 0),
        "task_completed": bool(details.get("task_completed") is True),
        "submit_result_called": bool(details.get("submit_result_called") is True),
        "submit_result_round": int(details.get("submit_result_round") or 0),
    }
    store.emit(event_type, payload, source="apiserver.chat_stream")


def _emit_core_child_spawn_deferred_event(
    *,
    session_id: str,
    core_execution_session_id: str,
    route_meta: Dict[str, Any],
    chunk_data: Dict[str, Any],
) -> None:
    if not isinstance(chunk_data, dict):
        return
    if str(chunk_data.get("type") or "").strip().lower() != "child_spawn_deferred":
        return

    store = _get_chat_route_event_store()
    if store is None:
        return

    decision = route_meta.get("router_decision") if isinstance(route_meta.get("router_decision"), dict) else {}
    payload = {
        "session_id": str(session_id or ""),
        "shell_session_id": str(route_meta.get("shell_session_id") or ""),
        "core_execution_session_id": str(core_execution_session_id or ""),
        "trace_id": str(decision.get("trace_id") or ""),
        "workflow_id": str(decision.get("task_id") or ""),
        "route_semantic": str(route_meta.get("route_semantic") or ""),
        "pipeline_id": str(chunk_data.get("pipeline_id") or ""),
        "agent_id": str(chunk_data.get("agent_id") or ""),
        "role": str(chunk_data.get("role") or ""),
        "source": str(chunk_data.get("source") or ""),
        "reason": str(chunk_data.get("reason") or ""),
    }
    store.emit("CoreChildSpawnDeferred", payload, source="apiserver.chat_stream")


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


def _collect_chat_route_session_state_events(*, session_ids: List[str], limit: int = 20) -> List[Dict[str, Any]]:
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

        shell_session_id = str(payload.get("shell_session_id") or payload.get("session_id") or "").strip()
        core_execution_session_id = str(payload.get("core_execution_session_id") or "").strip()
        event_session_ids = {sid for sid in (shell_session_id, core_execution_session_id) if sid}
        if not (event_session_ids & ids):
            continue

        normalized_event_route_semantic = _normalize_route_semantic(payload.get("route_semantic"))
        normalized_event_trigger = _normalize_route_semantic(payload.get("trigger") or normalized_event_route_semantic)
        route_semantic = normalized_event_route_semantic
        active_agent = str(payload.get("active_agent") or "").strip()
        if not active_agent:
            active_agent = "core" if route_semantic == "core_execution" else "shell"
        dispatch_to_core = bool(payload.get("dispatch_to_core"))
        if not dispatch_to_core and route_semantic == "core_execution":
            dispatch_to_core = True

        matched.append(
            {
                "timestamp": str(row.get("timestamp") or ""),
                "event_type": "PromptInjectionComposed",
                "trigger": normalized_event_trigger,
                "route_semantic": route_semantic,
                "entry_agent": str(payload.get("entry_agent") or "shell"),
                "active_agent": active_agent,
                "dispatch_to_core": dispatch_to_core,
                "handoff_tool": str(
                    payload.get("handoff_tool") or ("dispatch_to_core" if dispatch_to_core else "")
                ),
                "core_execution_route": str(payload.get("core_execution_route") or ""),
                "delegation_intent": str(payload.get("delegation_intent") or ""),
                "prompt_profile": str(payload.get("prompt_profile") or ""),
                "injection_mode": str(payload.get("injection_mode") or ""),
                "shell_session_id": shell_session_id,
                "core_execution_session_id": core_execution_session_id,
                "shell_clarify_budget_escalated": bool(payload.get("shell_clarify_budget_escalated")),
                "shell_clarify_budget_reason": str(payload.get("shell_clarify_budget_reason") or ""),
                "shell_clarify_turns": int(payload.get("shell_clarify_turns") or 0),
                "shell_clarify_limit": int(payload.get("shell_clarify_limit") or _CHAT_ROUTE_SHELL_CLARIFY_LIMIT),
                "shell_clarify_limit_override": payload.get("shell_clarify_limit_override"),
                "route_quality_guard_status": _ops_status_to_severity(
                    str(payload.get("route_quality_guard_status") or "unknown")
                ),
                "route_quality_guard_applied": bool(payload.get("route_quality_guard_applied")),
                "route_quality_guard_action": str(payload.get("route_quality_guard_action") or ""),
                "route_quality_guard_reason": str(payload.get("route_quality_guard_reason") or ""),
                "route_quality_guard_reason_codes": _sanitize_route_quality_reason_codes(
                    payload.get("route_quality_guard_reason_codes")
                ),
                "route_quality_guard_route_semantic_before": str(payload.get("route_quality_guard_route_semantic_before") or ""),
                "route_quality_guard_route_semantic_after": str(payload.get("route_quality_guard_route_semantic_after") or ""),
                "router_arbiter_status": _ops_status_to_severity(
                    str(payload.get("router_arbiter_status") or "unknown")
                ),
                "router_arbiter_applied": bool(payload.get("router_arbiter_applied")),
                "router_arbiter_action": str(payload.get("router_arbiter_action") or ""),
                "router_arbiter_reason": str(payload.get("router_arbiter_reason") or ""),
                "router_arbiter_reason_codes": _sanitize_router_arbiter_reason_codes(
                    payload.get("router_arbiter_reason_codes")
                ),
                "router_arbiter_route_semantic_before": str(payload.get("router_arbiter_route_semantic_before") or ""),
                "router_arbiter_route_semantic_after": str(payload.get("router_arbiter_route_semantic_after") or ""),
                "router_arbiter_delegate_turns": int(payload.get("router_arbiter_delegate_turns") or 0),
                "router_arbiter_max_delegate_turns": int(
                    payload.get("router_arbiter_max_delegate_turns") or _router_arbiter_max_delegate_turns()
                ),
                "router_arbiter_conflict_ticket": str(payload.get("router_arbiter_conflict_ticket") or ""),
                "router_arbiter_freeze": bool(payload.get("router_arbiter_freeze")),
                "router_arbiter_hitl": bool(payload.get("router_arbiter_hitl")),
                "router_arbiter_escalated": bool(payload.get("router_arbiter_escalated")),
                "core_execution_session_created": bool(payload.get("core_execution_session_created")),
                "source": str(row.get("source") or ""),
            }
        )
        if len(matched) >= max(1, int(limit)):
            break
    matched.reverse()
    return matched


def _build_chat_route_session_state_snapshot_event(shell_session_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    core_execution_session_id = str(state.get("core_execution_session_id") or "").strip()
    route_semantic = _normalize_route_semantic(state.get("last_route_semantic"))
    route_meta = _apply_route_semantic_fields(
        {
            "route_semantic": route_semantic,
            "active_agent": str(state.get("last_active_agent") or "").strip(),
            "dispatch_to_core": bool(state.get("last_dispatch_to_core")),
            "handoff_tool": str(state.get("last_handoff_tool") or "").strip(),
            "core_execution_route": str(state.get("last_core_execution_route") or "").strip(),
            "shell_session_id": shell_session_id,
            "core_execution_session_id": core_execution_session_id,
        }
    )
    delegation_intent = {
        "core_execution": "core_execution",
        "shell_clarify": "shell_clarify",
        "shell_readonly": "read_only_exploration",
    }.get(route_meta["route_semantic"], "read_only_exploration")
    return {
        "timestamp": _ops_utc_iso_now(),
        "event_type": "RouteSessionStateSnapshot",
        "session_id": shell_session_id,
        "shell_session_id": shell_session_id,
        "core_execution_session_id": core_execution_session_id,
        "trigger": route_meta["route_semantic"],
        "route_semantic": route_meta["route_semantic"],
        "entry_agent": "shell",
        "active_agent": route_meta["active_agent"],
        "dispatch_to_core": bool(route_meta["dispatch_to_core"]),
        "handoff_tool": str(route_meta.get("handoff_tool") or ""),
        "core_execution_route": str(route_meta.get("core_execution_route") or ""),
        "risk_level": str(
            state.get("last_risk_level")
            or ("write_repo" if route_meta["route_semantic"] == "core_execution" else "read_only")
        ),
        "shell_readonly_hit": route_meta["route_semantic"] == "shell_readonly",
        "delegation_intent": delegation_intent,
        "prompt_profile": "",
        "injection_mode": "",
        "shell_clarify_budget_escalated": False,
        "shell_clarify_budget_reason": "",
        "shell_clarify_turns": int(state.get("shell_clarify_turns") or 0),
        "shell_clarify_limit": _CHAT_ROUTE_SHELL_CLARIFY_LIMIT,
        "shell_clarify_limit_override": None,
        "route_quality_guard_status": "unknown",
        "route_quality_guard_applied": False,
        "route_quality_guard_action": "",
        "route_quality_guard_reason": "",
        "route_quality_guard_reason_codes": [],
        "route_quality_guard_route_semantic_before": "",
        "route_quality_guard_route_semantic_after": "",
        "router_arbiter_status": "unknown",
        "router_arbiter_applied": False,
        "router_arbiter_action": "",
        "router_arbiter_reason": "",
        "router_arbiter_reason_codes": [],
        "router_arbiter_route_semantic_before": "",
        "router_arbiter_route_semantic_after": "",
        "router_arbiter_delegate_turns": 0,
        "router_arbiter_max_delegate_turns": int(_router_arbiter_max_delegate_turns() or 0),
        "router_arbiter_conflict_ticket": "",
        "router_arbiter_freeze": False,
        "router_arbiter_hitl": False,
        "router_arbiter_escalated": False,
        "core_execution_session_created": False,
        "source": "session_state_snapshot",
    }


def _build_chat_route_session_state_payload(session_id: str, *, limit: int = 20) -> Dict[str, Any]:
    session = _get_message_manager().get_session(session_id)
    if not isinstance(session, dict):
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")

    shell_session_id = str(session_id or "")
    state = _ensure_chat_route_state(session_id)
    core_execution_session_id = str(state.get("core_execution_session_id") or "").strip()
    last_core_execution_session_id = str(state.get("last_core_execution_session_id") or shell_session_id)
    session_ids = [shell_session_id]
    if core_execution_session_id:
        session_ids.append(core_execution_session_id)
    route_events = _collect_chat_route_session_state_events(session_ids=session_ids, limit=max(1, int(limit)))
    if not route_events:
        route_events = [_build_chat_route_session_state_snapshot_event(shell_session_id, state)]

    heartbeat_snapshot = _empty_descendant_heartbeat_snapshot(core_execution_session_id)
    if core_execution_session_id:
        agent_session_store = _get_agent_session_store()
        if agent_session_store is not None:
            try:
                snapshot = agent_session_store.get_descendant_heartbeat_snapshot(core_execution_session_id)
                if isinstance(snapshot, dict):
                    heartbeat_snapshot = {
                        "root_session_id": str(snapshot.get("root_session_id") or core_execution_session_id),
                        "summary": dict(snapshot.get("summary") or {}),
                        "sessions": list(snapshot.get("sessions") or []),
                        "heartbeats": list(snapshot.get("heartbeats") or []),
                    }
            except Exception as exc:
                logger.debug("构建 chat route child heartbeat snapshot 失败: %s", exc)

    return {
        "status": "success",
        "shell_session_id": shell_session_id,
        "core_execution_session_id": core_execution_session_id,
        "shell_session_exists": True,
        "core_execution_session_exists": bool(
            core_execution_session_id and _get_message_manager().get_session(core_execution_session_id)
        ),
        "child_heartbeat_summary": dict(heartbeat_snapshot.get("summary") or {}),
        "child_heartbeat_sessions": list(heartbeat_snapshot.get("sessions") or []),
        "child_heartbeats": list(heartbeat_snapshot.get("heartbeats") or []),
        "state": {
            "shell_clarify_turns": int(state.get("shell_clarify_turns") or 0),
            "shell_clarify_limit": _CHAT_ROUTE_SHELL_CLARIFY_LIMIT,
            "last_core_execution_session_id": last_core_execution_session_id,
            "last_core_escalation_at_ms": int(state.get("last_core_escalation_at_ms") or 0),
            "last_route_semantic": str(state.get("last_route_semantic") or ""),
            "last_active_agent": str(state.get("last_active_agent") or ""),
            "last_dispatch_to_core": bool(state.get("last_dispatch_to_core")),
            "last_handoff_tool": str(state.get("last_handoff_tool") or ""),
            "last_core_execution_route": str(state.get("last_core_execution_route") or ""),
            "last_risk_level": str(state.get("last_risk_level") or ""),
        },
        "recent_route_events": route_events,
    }


def _format_sse_payload_chunk_json(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(_json_safe_sse_payload(payload), ensure_ascii=False)}\n\n"


def _json_safe_sse_payload(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe_sse_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_sse_payload(item) for item in value]
    return f"<non-json:{value.__class__.__name__}>"
