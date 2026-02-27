#!/usr/bin/env python3
"""
NagaAgent API服务器
提供RESTful API接口访问NagaAgent功能
"""

import asyncio
import base64
import json
import sys
import traceback
import os
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, AsyncGenerator, Any, Callable

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import shutil
from pathlib import Path
from system.coding_intent import contains_direct_coding_signal, has_recent_coding_context, is_coding_followup
from system.watchdog_daemon import WatchdogDaemon
from autonomous.event_log.event_store import EventStore
from autonomous.router_engine import RouterRequest, TaskRouterEngine
from autonomous.router_arbiter_guard import RouterArbiterGuard
from autonomous.llm_gateway import (
    GatewayRouteRequest,
    LLMGateway,
    PromptEnvelopeInput,
)

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .message_manager import message_manager  # noqa: E402 - keep script-mode compatibility path setup

from .llm_service import get_llm_service, llm_app  # noqa: E402 - mounted below
from . import naga_auth  # noqa: E402 - keep script-mode compatibility path setup

# 记录哪些会话曾发送过图片，后续消息继续走 VLM 直到新会话
_vlm_sessions: set = set()

# 导入配置系统
try:
    from system.config import get_config, build_system_prompt, build_system_prompt_for_path  # 使用新的配置系统
    from system.config_manager import get_config_snapshot, update_config  # 导入配置管理
except ImportError:
    import sys
    import os

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from system.config import get_config  # 使用新的配置系统
    from system.config import build_system_prompt, build_system_prompt_for_path  # 导入提示词仓库
    from system.config_manager import get_config_snapshot, update_config  # 导入配置管理
from apiserver.response_util import extract_message  # noqa: E402 - imported after fallback config setup

# 在导入其他模块后设置HTTP库日志级别
logging.getLogger("httpcore.http11").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore.connection").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# 对话核心功能已集成到apiserver


# 统一后台意图分析触发函数 - 已整合到message_manager
def _trigger_background_analysis(session_id: str):
    """统一触发后台意图分析 - 委托给message_manager"""
    message_manager.trigger_background_analysis(session_id)


# 统一保存对话与日志函数 - 已整合到message_manager
def _save_conversation_and_logs(session_id: str, user_message: str, assistant_response: str):
    """统一保存对话历史与日志 - 委托给message_manager"""
    message_manager.save_conversation_and_logs(session_id, user_message, assistant_response)


_CHAT_PATH_ROUTER = TaskRouterEngine()
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

_BRAINSTEM_AUTOSTART_ENV = "NAGA_BRAINSTEM_AUTOSTART"
_BRAINSTEM_AUTOSTOP_ENV = "NAGA_BRAINSTEM_AUTOSTOP_ON_API_SHUTDOWN"
_BRAINSTEM_AUTOSTART_TIMEOUT_ENV = "NAGA_BRAINSTEM_AUTOSTART_TIMEOUT_SECONDS"
_BRAINSTEM_BOOTSTRAP_OWNER_ENV = "NAGA_BRAINSTEM_BOOTSTRAP_OWNER"
_BRAINSTEM_BOOTSTRAP_OWNER_API = "api"
_BRAINSTEM_AUTOSTART_DEFAULT = True
_BRAINSTEM_AUTOSTART_OUTPUT = Path("scratch/reports/brainstem_control_plane_autostart_ws28_017.json")
_BRAINSTEM_AUTOSTOP_OUTPUT = Path("scratch/reports/brainstem_control_plane_autostop_ws28_017.json")
_GLOBAL_MUTEX_BOOTSTRAP_TTL_SECONDS = 10.0
_IMMUTABLE_DNA_PREFLIGHT_REQUIRED_ENV = "NAGA_IMMUTABLE_DNA_PREFLIGHT_REQUIRED"


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(str(name))
    if raw is None:
        return bool(default)
    normalized = str(raw).strip().lower()
    if not normalized:
        return bool(default)
    return normalized in {"1", "true", "yes", "on", "y"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(str(name))
    if raw is None:
        return float(default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _brainstem_bootstrap_owner() -> str:
    return str(os.environ.get(_BRAINSTEM_BOOTSTRAP_OWNER_ENV) or "").strip().lower()


def _brainstem_bootstrap_owned_by_external() -> tuple[bool, str]:
    owner = _brainstem_bootstrap_owner()
    if not owner:
        return False, ""
    if owner in {_BRAINSTEM_BOOTSTRAP_OWNER_API, "apiserver"}:
        return False, owner
    return True, owner


def _should_bootstrap_brainstem_control_plane() -> tuple[bool, str]:
    external_owned, owner = _brainstem_bootstrap_owned_by_external()
    if external_owned:
        return False, f"owned_by_{owner}"
    explicit = os.environ.get(_BRAINSTEM_AUTOSTART_ENV)
    if explicit is None and os.environ.get("PYTEST_CURRENT_TEST"):
        return False, "pytest_default_skip"
    enabled = _env_flag(_BRAINSTEM_AUTOSTART_ENV, _BRAINSTEM_AUTOSTART_DEFAULT)
    if not enabled:
        return False, "env_disabled"
    return True, "enabled"


def _bootstrap_brainstem_control_plane_startup(
    *,
    manager: Optional[Callable[..., Dict[str, Any]]] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    enabled, reason = _should_bootstrap_brainstem_control_plane()
    root = (repo_root or _ops_repo_root()).resolve()
    report: Dict[str, Any] = {
        "enabled": enabled,
        "reason": reason,
        "repo_root": str(root).replace("\\", "/"),
        "env": {
            "autostart_env": _BRAINSTEM_AUTOSTART_ENV,
            "autostop_env": _BRAINSTEM_AUTOSTOP_ENV,
            "autostart_timeout_env": _BRAINSTEM_AUTOSTART_TIMEOUT_ENV,
        },
    }
    if not enabled:
        return report

    run_manager = manager
    if run_manager is None:
        from scripts.manage_brainstem_control_plane_ws28_017 import run_manage_brainstem_control_plane_ws28_017

        run_manager = run_manage_brainstem_control_plane_ws28_017

    timeout_seconds = max(2.0, _env_float(_BRAINSTEM_AUTOSTART_TIMEOUT_ENV, 8.0))
    try:
        startup_report = run_manager(
            repo_root=root,
            action="start",
            output_file=_BRAINSTEM_AUTOSTART_OUTPUT,
            start_timeout_seconds=timeout_seconds,
            force_restart=False,
        )
        report["passed"] = bool(startup_report.get("passed"))
        report["startup_report"] = startup_report
        if bool(startup_report.get("passed")):
            logger.info("[brainstem_bootstrap] control plane startup ensured")
        else:
            logger.warning("[brainstem_bootstrap] control plane startup failed")
    except Exception as exc:
        report["passed"] = False
        report["error"] = f"{type(exc).__name__}:{exc}"
        logger.error(f"[brainstem_bootstrap] startup error: {exc}")
    return report


def _bootstrap_brainstem_control_plane_shutdown(
    *,
    manager: Optional[Callable[..., Dict[str, Any]]] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    external_owned, owner = _brainstem_bootstrap_owned_by_external()
    enabled = _env_flag(_BRAINSTEM_AUTOSTOP_ENV, False)
    root = (repo_root or _ops_repo_root()).resolve()
    report: Dict[str, Any] = {
        "enabled": enabled,
        "repo_root": str(root).replace("\\", "/"),
        "env": {
            "autostop_env": _BRAINSTEM_AUTOSTOP_ENV,
            "owner_env": _BRAINSTEM_BOOTSTRAP_OWNER_ENV,
        },
    }
    if external_owned:
        report["enabled"] = False
        report["reason"] = f"owned_by_{owner}"
        return report
    if not enabled:
        report["reason"] = "env_disabled"
        return report

    run_manager = manager
    if run_manager is None:
        from scripts.manage_brainstem_control_plane_ws28_017 import run_manage_brainstem_control_plane_ws28_017

        run_manager = run_manage_brainstem_control_plane_ws28_017

    try:
        shutdown_report = run_manager(
            repo_root=root,
            action="stop",
            output_file=_BRAINSTEM_AUTOSTOP_OUTPUT,
        )
        report["passed"] = bool(shutdown_report.get("passed"))
        report["shutdown_report"] = shutdown_report
        if bool(shutdown_report.get("passed")):
            logger.info("[brainstem_bootstrap] control plane stop completed")
        else:
            logger.warning("[brainstem_bootstrap] control plane stop reported failures")
    except Exception as exc:
        report["passed"] = False
        report["error"] = f"{type(exc).__name__}:{exc}"
        logger.error(f"[brainstem_bootstrap] shutdown error: {exc}")
    return report


def _bootstrap_global_mutex_lease_state(
    *,
    manager_factory: Optional[Callable[[], Any]] = None,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "enabled": True,
        "ttl_seconds": float(_GLOBAL_MUTEX_BOOTSTRAP_TTL_SECONDS),
    }
    try:
        if manager_factory is None:
            from system.global_mutex import get_global_mutex_manager

            manager = get_global_mutex_manager()
        else:
            manager = manager_factory()

        state = manager.ensure_initialized(ttl_seconds=float(_GLOBAL_MUTEX_BOOTSTRAP_TTL_SECONDS))
        state_file = Path(str(getattr(manager, "state_file", "") or "")).resolve()
        report["state_file"] = str(state_file).replace("\\", "/")
        report["state"] = str(state.get("lease_state") or state.get("state") or "")
        report["fencing_epoch"] = int(state.get("fencing_epoch") or 0)
        report["passed"] = state_file.exists()
        if report["passed"]:
            logger.info("[global_mutex_bootstrap] lease state initialized")
        else:
            logger.warning("[global_mutex_bootstrap] state file missing after bootstrap")
    except Exception as exc:
        report["passed"] = False
        report["error"] = f"{type(exc).__name__}:{exc}"
        logger.error(f"[global_mutex_bootstrap] bootstrap error: {exc}")
    return report


def _bootstrap_immutable_dna_preflight() -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "enabled": True,
        "required": _env_flag(_IMMUTABLE_DNA_PREFLIGHT_REQUIRED_ENV, True),
    }
    try:
        llm = get_llm_service()
        preflight = llm.immutable_dna_preflight()
        report.update(preflight if isinstance(preflight, dict) else {})
        report["passed"] = bool(report.get("passed", False))
        if bool(report.get("passed", False)):
            logger.info("[immutable_dna_bootstrap] preflight passed")
        else:
            logger.error("[immutable_dna_bootstrap] preflight failed: %s", report.get("reason", "unknown"))
    except Exception as exc:
        report["passed"] = False
        report["reason"] = "immutable_dna_preflight_exception"
        report["error"] = f"{type(exc).__name__}:{exc}"
        logger.error("[immutable_dna_bootstrap] preflight exception: %s", exc)
    return report


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


def _resolve_chat_stream_route(message: str, *, session_id: str) -> Dict[str, Any]:
    normalized_message = str(message or "")
    recent_messages = message_manager.get_recent_messages(session_id, count=10)
    risk_level = _infer_chat_route_risk_level(normalized_message, recent_messages=recent_messages)
    request = RouterRequest(
        task_id=f"chat_stream_{int(time.time() * 1000)}",
        description=normalized_message,
        estimated_complexity=_infer_chat_route_complexity(normalized_message),
        risk_level=risk_level,
        trace_id=f"chat_route_{uuid.uuid4().hex[:12]}",
        session_id=str(session_id or ""),
    )
    decision = _CHAT_PATH_ROUTER.route(request)
    intent = str(decision.delegation_intent or "").strip().lower()
    if intent == "read_only_exploration":
        path = "path-a"
    elif intent in {"core_execution", "explicit_role_delegate"}:
        path = "path-c"
    else:
        path = "path-b"

    return {
        "path": path,
        "risk_level": risk_level,
        "outer_readonly_hit": path == "path-a",
        "core_escalation": path == "path-c",
        "router_decision": decision.to_dict(),
    }


def _ensure_chat_route_state(session_id: str) -> Dict[str, Any]:
    session = message_manager.get_session(session_id)
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


def _force_route_to_core_execution(route_meta: Dict[str, Any], *, reason: str) -> Dict[str, Any]:
    decision = route_meta.get("router_decision") if isinstance(route_meta.get("router_decision"), dict) else {}
    effective_decision = dict(decision)
    effective_decision["delegation_intent"] = "core_execution"
    prompt_profile = str(effective_decision.get("prompt_profile") or "").strip()
    if not prompt_profile.startswith("core_exec"):
        effective_decision["prompt_profile"] = "core_exec_general"
    injection_mode = str(effective_decision.get("injection_mode") or "").strip().lower()
    if injection_mode in {"", "minimal"}:
        effective_decision["injection_mode"] = "normal"

    route_meta["path"] = "path-c"
    route_meta["outer_readonly_hit"] = False
    route_meta["core_escalation"] = True
    route_meta["router_decision"] = effective_decision
    route_meta["route_forced_to_core_reason"] = str(reason or "")
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
            route_meta = _force_route_to_core_execution(
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
        route_meta = _force_route_to_core_execution(route_meta, reason=budget_reason)
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
    route_meta["router_arbiter_max_delegate_turns"] = int(_CHAT_ROUTE_ARBITER_GUARD.max_delegate_turns)
    route_meta["router_arbiter_conflict_ticket"] = ""
    route_meta["router_arbiter_freeze"] = False
    route_meta["router_arbiter_hitl"] = False
    route_meta["router_arbiter_escalated"] = False

    guard = _CHAT_ROUTE_ARBITER_GUARD
    if guard is None:
        state["last_router_path"] = str(route_meta.get("path") or current_path)
        return route_meta

    summary_before = guard.build_conflict_summary(session_id)
    frozen_before = bool(summary_before.get("freeze"))
    if frozen_before and current_path != "path-c":
        route_meta = _force_route_to_core_execution(route_meta, reason="router_arbiter_frozen_to_core")
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
            route_meta = _force_route_to_core_execution(route_meta, reason="router_arbiter_ping_pong_freeze_core")
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
    if not message_manager.get_session(core_session_id):
        outer_session = message_manager.get_session(outer_session_id) or {}
        temporary = bool(outer_session.get("temporary", False))
        message_manager.create_session(session_id=core_session_id, temporary=temporary)
        core_session_created = True

    state["core_session_id"] = core_session_id
    state["last_core_escalation_at_ms"] = int(time.time() * 1000)
    state["last_execution_session_id"] = core_session_id

    route_meta["core_session_id"] = core_session_id
    route_meta["execution_session_id"] = core_session_id
    route_meta["core_session_created"] = core_session_created
    return route_meta


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
    text = " ".join(str(value or "").strip().split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _build_core_execution_contract_payload(
    *,
    session_id: str,
    current_message: str,
    recent_messages: List[Dict[str, Any]],
) -> Dict[str, Any]:
    latest_user_history: List[str] = []
    latest_assistant_history: List[str] = []
    for item in reversed(list(recent_messages or [])):
        role = str(item.get("role") or "").strip().lower()
        content = _trim_contract_text(item.get("content", ""))
        if not content:
            continue
        if role == "user" and len(latest_user_history) < 3:
            latest_user_history.append(content)
        elif role == "assistant" and len(latest_assistant_history) < 2:
            latest_assistant_history.append(content)
        if len(latest_user_history) >= 3 and len(latest_assistant_history) >= 2:
            break

    latest_user_history.reverse()
    latest_assistant_history.reverse()
    goal = _trim_contract_text(current_message, limit=320)
    scope_hint = latest_user_history[-1] if latest_user_history else goal
    acceptance_hint = "输出可验证的执行证据（含结果与报告路径），必要时附失败根因与下一步。"
    assumptions: List[str] = []
    if not latest_user_history:
        assumptions.append("历史上下文为空，按当前请求建立新执行契约。")
    if len(goal) <= 24 and any(marker in goal.lower() for marker in _CHAT_ROUTE_FOLLOWUP_MARKERS):
        assumptions.append("用户输入可能是续写指令，需结合 recent_user_history 推断目标。")

    # Outer 上下文摘要：Core 唯一的历史感知来源
    outer_context_summary = ""
    if latest_user_history:
        outer_context_summary = " → ".join(latest_user_history[-2:])
    if latest_assistant_history:
        last_assistant = latest_assistant_history[-1]
        if outer_context_summary:
            outer_context_summary += f" [assistant: {last_assistant[:120]}]"
        else:
            outer_context_summary = f"[assistant: {last_assistant[:120]}]"

    return {
        "contract_stage": "seed",
        "session_id": str(session_id or ""),
        "goal": goal,
        "scope_hint": scope_hint,
        "acceptance_hint": acceptance_hint,
        "outer_context_summary": outer_context_summary,
        "recent_user_history": latest_user_history,
        "recent_assistant_history": latest_assistant_history,
        "assumptions": assumptions,
        "evidence_path_hint": "scratch/reports/",
    }


def _build_core_execution_messages(
    *,
    session_id: str,
    core_system_prompt: str,
    current_message: str,
) -> List[Dict[str, Any]]:
    """构建 Core 执行代理的消息列表。

    Core 消息列表仅包含三条：
    1. system: 已裁剪的 Core 身份 prompt（由 build_system_prompt_for_path('path-c') 生成）
    2. system: [ExecutionContractInput] JSON（Outer 上下文摘要 + 目标 + 证据约束）
    3. user: 当前用户请求

    不注入 Outer 闲聊历史，实现上下文隔离。
    """
    recent_messages = message_manager.get_recent_messages(session_id, count=10)
    contract_payload = _build_core_execution_contract_payload(
        session_id=session_id,
        current_message=current_message,
        recent_messages=recent_messages,
    )
    contract_text = "[ExecutionContractInput]\n" + json.dumps(contract_payload, ensure_ascii=False, sort_keys=True)
    return [
        {"role": "system", "content": core_system_prompt},
        {"role": "system", "content": contract_text},
        {"role": "user", "content": current_message},
    ]


def _get_chat_route_event_store() -> Optional[EventStore]:
    global _CHAT_ROUTE_EVENT_STORE
    if _CHAT_ROUTE_EVENT_STORE is not None:
        return _CHAT_ROUTE_EVENT_STORE
    try:
        event_file = Path(__file__).resolve().parent.parent / "logs" / "autonomous" / "events.jsonl"
        _CHAT_ROUTE_EVENT_STORE = EventStore(file_path=event_file)
    except Exception as exc:
        logger.debug(f"初始化 chat route event store 失败: {exc}")
        return None
    return _CHAT_ROUTE_EVENT_STORE


def _build_chat_route_prompt_event_payload(route_meta: Dict[str, Any]) -> Dict[str, Any]:
    decision = route_meta.get("router_decision") if isinstance(route_meta.get("router_decision"), dict) else {}
    path = str(route_meta.get("path") or "path-c")
    delegation_intent = str(decision.get("delegation_intent") or "").strip()
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
        "dropped_slice_count": int(route_meta.get("_slice_dropped_count") or 0),
        "dropped_conflict_count": 0,
        "selected_layers": route_meta.get("_slice_selected_layers") or [],
        "selected_layer_counts": {},
        "recovery_hit": False,
        "prefix_hash": str(route_meta.get("_slice_prefix_hash") or ""),
        "tail_hash": str(route_meta.get("_slice_tail_hash") or ""),
        "prefix_cache_hit": False,
        "block1_cache_hit": False,
        "block2_cache_hit": False,
        "token_budget_before": 0,
        "token_budget_after": 0,
        "model_tier": str(decision.get("selected_model_tier") or ""),
        "model_id": "",
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
            route_meta.get("router_arbiter_max_delegate_turns") or _CHAT_ROUTE_ARBITER_GUARD.max_delegate_turns
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
            route_meta.get("router_arbiter_max_delegate_turns") or _CHAT_ROUTE_ARBITER_GUARD.max_delegate_turns
        ),
        "router_arbiter_freeze": bool(route_meta.get("router_arbiter_freeze")),
        "router_arbiter_hitl": bool(route_meta.get("router_arbiter_hitl")),
        "router_arbiter_escalated": bool(route_meta.get("router_arbiter_escalated")),
        "outer_session_id": str(route_meta.get("outer_session_id") or ""),
        "core_session_id": str(route_meta.get("core_session_id") or ""),
        "execution_session_id": str(route_meta.get("execution_session_id") or ""),
    }
    store.emit(event_type, payload, source="apiserver.chat_stream")


def _read_chat_route_event_rows(*, limit: int = 2000) -> List[Dict[str, Any]]:
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
                    payload.get("router_arbiter_max_delegate_turns") or _CHAT_ROUTE_ARBITER_GUARD.max_delegate_turns
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
    session = message_manager.get_session(session_id)
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
        "core_session_exists": bool(core_session_id and message_manager.get_session(core_session_id)),
        "state": {
            "path_b_clarify_turns": int(state.get("path_b_clarify_turns") or 0),
            "path_b_clarify_limit": _CHAT_ROUTE_PATH_B_CLARIFY_LIMIT,
            "last_execution_session_id": execution_session_id,
            "last_core_escalation_at_ms": int(state.get("last_core_escalation_at_ms") or 0),
        },
        "recent_route_events": route_events,
    }


def _format_sse_payload_chunk(payload: Dict[str, Any]) -> str:
    b64 = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
    return f"data: {b64}\n\n"


# 历史流式文本切分器已移除，流式处理统一由 chat_stream 主循环管理


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    try:
        print("[INFO] 正在初始化API服务器...")
        mutex_bootstrap = _bootstrap_global_mutex_lease_state()
        app.state.global_mutex_bootstrap = mutex_bootstrap
        if not bool(mutex_bootstrap.get("passed", False)):
            print("[WARN] Global mutex 启动初始化未通过，锁状态可能显示 missing/unknown")
        immutable_dna_preflight = _bootstrap_immutable_dna_preflight()
        app.state.immutable_dna_preflight = immutable_dna_preflight
        immutable_dna_required = bool(immutable_dna_preflight.get("required", True))
        immutable_dna_enabled = bool(immutable_dna_preflight.get("enabled", True))
        immutable_dna_passed = bool(immutable_dna_preflight.get("passed", False))
        if immutable_dna_required and immutable_dna_enabled and not immutable_dna_passed:
            raise RuntimeError(
                "Immutable DNA startup preflight failed: "
                f"{str(immutable_dna_preflight.get('reason') or 'unknown')}"
            )
        # 对话核心功能已集成到apiserver
        brainstem_bootstrap = _bootstrap_brainstem_control_plane_startup()
        app.state.brainstem_bootstrap = brainstem_bootstrap
        if bool(brainstem_bootstrap.get("enabled")) and not bool(brainstem_bootstrap.get("passed", True)):
            print("[WARN] Brainstem 控制面自动托管未通过，运行态势可能显示 unknown/missing")
        print("[SUCCESS] API服务器初始化完成")
        yield
    except Exception as e:
        print(f"[ERROR] API服务器初始化失败: {e}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        print("[INFO] 正在清理资源...")
        # MCP服务现在由mcpserver独立管理，无需清理
        app.state.brainstem_shutdown = _bootstrap_brainstem_control_plane_shutdown()


# 创建FastAPI应用
app = FastAPI(title="NagaAgent API", description="智能对话助手API服务", version="5.0.0", lifespan=lifespan)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境建议限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_DEFAULT_VERSION = "v1"
API_CONTRACT_VERSION = "2026-02-24"
API_COMPATIBILITY_WINDOW_DAYS = 180
API_SUPPORTED_VERSIONS = [API_DEFAULT_VERSION]
_UNVERSIONED_ROUTE_DEPRECATIONS: Dict[str, Dict[str, str]] = {
    "/health": {
        "sunset": "2026-08-24",
        "replacement": "/v1/health",
    },
    "/system/info": {
        "sunset": "2026-08-24",
        "replacement": "/v1/system/info",
    },
    "/chat": {
        "sunset": "2026-08-24",
        "replacement": "/v1/chat",
    },
    "/chat/stream": {
        "sunset": "2026-08-24",
        "replacement": "/v1/chat/stream",
    },
}


def _resolve_api_deprecation_policy(path: str) -> Optional[Dict[str, str]]:
    return _UNVERSIONED_ROUTE_DEPRECATIONS.get(str(path or ""))


def _build_api_contract_snapshot() -> Dict[str, Any]:
    return {
        "api_version": API_DEFAULT_VERSION,
        "contract_version": API_CONTRACT_VERSION,
        "supported_versions": list(API_SUPPORTED_VERSIONS),
        "compatibility_window_days": API_COMPATIBILITY_WINDOW_DAYS,
        "deprecations": {
            route: {
                "sunset": meta["sunset"],
                "replacement": meta["replacement"],
            }
            for route, meta in _UNVERSIONED_ROUTE_DEPRECATIONS.items()
        },
    }


@app.middleware("http")
async def sync_auth_token(request: Request, call_next):
    """每次请求自动同步前端 token 到后端认证状态，避免 token 刷新后后端仍持有旧 token"""
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if token and token != naga_auth.get_access_token():
            naga_auth.restore_token(token)
    response = await call_next(request)
    return response


@app.middleware("http")
async def inject_api_contract_headers(request: Request, call_next):
    response = await call_next(request)
    snapshot = _build_api_contract_snapshot()
    response.headers.setdefault("X-NagaAgent-Api-Version", str(snapshot["api_version"]))
    response.headers.setdefault("X-NagaAgent-Contract-Version", str(snapshot["contract_version"]))

    deprecation = _resolve_api_deprecation_policy(request.url.path)
    if isinstance(deprecation, dict):
        response.headers["Deprecation"] = "true"
        response.headers["Sunset"] = str(deprecation.get("sunset") or "")
        replacement = str(deprecation.get("replacement") or "").strip()
        if replacement:
            response.headers["Link"] = f"<{replacement}>; rel=\"successor-version\""
    return response


# 挂载静态文件
# ============ 内部服务代理 ============


async def _call_agentserver(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    timeout_seconds: float = 15.0,
) -> Any:
    """调用 agentserver 内部接口"""
    import httpx
    from system.config import get_server_port

    port = get_server_port("agent_server")
    url = f"http://127.0.0.1:{port}{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, trust_env=False) as client:
            resp = await client.request(method, url, params=params, json=json_body)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"agentserver 不可达: {e}")
    if resp.status_code >= 400:
        detail = resp.text
        try:
            detail = resp.json()
        except Exception:
            pass
        raise HTTPException(status_code=resp.status_code, detail=detail)
    try:
        return resp.json()
    except Exception:
        return resp.text


# [已禁用] MCP Server 已从 main.py 启动流程中移除，此代理函数不再有效，调用必定 503
# async def _call_mcpserver(
#     method: str,
#     path: str,
#     params: Optional[Dict[str, Any]] = None,
#     timeout_seconds: float = 10.0,
# ) -> Any:
#     """调用 MCP Server 内部接口"""
#     import httpx
#     from system.config import get_server_port
#
#     port = get_server_port("mcp_server")
#     url = f"http://127.0.0.1:{port}{path}"
#     try:
#         async with httpx.AsyncClient(timeout=timeout_seconds, trust_env=False) as client:
#             resp = await client.request(method, url, params=params)
#     except Exception as e:
#         raise HTTPException(status_code=503, detail=f"MCP Server 不可达: {e}")
#     if resp.status_code >= 400:
#         detail = resp.text
#         try:
#             detail = resp.json()
#         except Exception:
#             pass
#         raise HTTPException(status_code=resp.status_code, detail=detail)
#     try:
#         return resp.json()
#     except Exception:
#         return resp.text


# ============ Skill Storage ============

SKILLS_TEMPLATE_DIR = Path(__file__).resolve().parent / "skills_templates"
LOCAL_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
LOCAL_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
MCPORTER_DIR = Path.home() / ".mcporter"
MCPORTER_CONFIG_PATH = MCPORTER_DIR / "config.json"


def _write_skill_file(skill_name: str, content: str) -> Path:
    skill_dir = LOCAL_SKILLS_DIR / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(content, encoding="utf-8")
    return skill_path

class ChatRequest(BaseModel):
    message: str
    stream: bool = False
    session_id: Optional[str] = None
    skip_intent_analysis: bool = False  # 新增：跳过意图分析
    skill: Optional[str] = None  # 用户主动选择的技能名称，注入完整指令到系统提示词
    images: Optional[List[str]] = None  # 截屏图片 base64 数据列表（data:image/png;base64,...）
    temporary: bool = False  # 临时会话标记，临时会话不持久化到磁盘


class ChatResponse(BaseModel):
    response: str
    reasoning_content: Optional[str] = None  # COT 思考过程内容
    session_id: Optional[str] = None
    status: str = "success"


class SystemInfoResponse(BaseModel):
    version: str
    status: str
    available_services: List[str]
    api_key_configured: bool


class FileUploadResponse(BaseModel):
    filename: str
    file_path: str
    file_size: int
    file_type: str
    upload_time: str
    status: str = "success"
    message: str = "文件上传成功"


class DocumentProcessRequest(BaseModel):
    file_path: str
    action: str = "read"  # read, analyze, summarize
    session_id: Optional[str] = None


# ============ Local-only auth compatibility endpoints ============

AUTH_DISABLED_DETAIL = "Remote authentication is disabled in local-only mode"


@app.post("/auth/login")
async def auth_login(body: dict):
    raise HTTPException(status_code=410, detail=AUTH_DISABLED_DETAIL)


@app.get("/auth/me")
async def auth_me(request: Request):
    return {"user": None, "memory_url": None, "local_mode": True}


@app.post("/auth/logout")
async def auth_logout():
    naga_auth.logout()
    return {"success": True, "local_mode": True}


@app.post("/auth/register")
async def auth_register(body: dict):
    raise HTTPException(status_code=410, detail=AUTH_DISABLED_DETAIL)


@app.get("/auth/captcha")
async def auth_captcha():
    raise HTTPException(status_code=410, detail=AUTH_DISABLED_DETAIL)


@app.post("/auth/send-verification")
async def auth_send_verification(body: dict):
    raise HTTPException(status_code=410, detail=AUTH_DISABLED_DETAIL)


@app.post("/auth/refresh")
async def auth_refresh(request: Request):
    raise HTTPException(status_code=410, detail=AUTH_DISABLED_DETAIL)


# API路由
@app.get("/", response_model=Dict[str, str])
async def root():
    """API根路径"""
    system_version = str(getattr(get_config().system, "version", "5.0.0"))
    return {
        "name": "NagaAgent API",
        "version": system_version,
        "api_version": API_DEFAULT_VERSION,
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy", "agent_ready": True, "timestamp": str(asyncio.get_event_loop().time())}


@app.get("/v1/health")
async def health_check_v1():
    return await health_check()


@app.get("/system/api-contract")
async def get_api_contract():
    """返回当前 API 契约版本、兼容窗口与弃用策略。"""
    return {"status": "success", **_build_api_contract_snapshot()}


@app.get("/v1/system/api-contract")
async def get_api_contract_v1():
    return await get_api_contract()


# ============ Utility APIs ============

@app.get("/system/info", response_model=SystemInfoResponse)
async def get_system_info():
    """获取系统信息"""
    system_version = str(getattr(get_config().system, "version", "5.0.0"))

    return SystemInfoResponse(
        version=system_version,
        status="running",
        available_services=[],  # MCP服务现在由mcpserver独立管理
        api_key_configured=bool(get_config().api.api_key and get_config().api.api_key != "sk-placeholder-key-not-set"),
    )


@app.get("/v1/system/info", response_model=SystemInfoResponse)
async def get_system_info_v1():
    return await get_system_info()


@app.get("/system/config")
async def get_system_config():
    """获取完整系统配置"""
    try:
        config_data = get_config_snapshot()
        return {"status": "success", "config": config_data}
    except Exception as e:
        logger.error(f"获取系统配置失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@app.post("/system/config")
async def update_system_config(payload: Dict[str, Any]):
    """更新系统配置"""
    try:
        success = update_config(payload)
        if success:
            return {"status": "success", "message": "配置更新成功"}
        else:
            raise HTTPException(status_code=500, detail="配置更新失败")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新系统配置失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")


@app.get("/system/prompt")
async def get_system_prompt(include_skills: bool = False):
    """获取系统提示词（默认只返回人格提示词，不包含技能列表）"""
    try:
        prompt = build_system_prompt(include_skills=include_skills)
        return {"status": "success", "prompt": prompt}
    except Exception as e:
        logger.error(f"获取系统提示词失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取系统提示词失败: {str(e)}")


@app.post("/system/prompt")
async def update_system_prompt(payload: Dict[str, Any]):
    """更新系统提示词"""
    try:
        content = payload.get("content")
        if not content:
            raise HTTPException(status_code=400, detail="缺少content参数")
        from system.config import save_prompt, evaluate_prompt_acl

        approval_ticket = str(payload.get("approval_ticket") or "").strip()
        change_reason = str(payload.get("change_reason") or "").strip()
        acl_decision = evaluate_prompt_acl(
            prompt_name="conversation_style_prompt",
            approval_ticket=approval_ticket,
            change_reason=change_reason,
        )
        if bool(acl_decision.get("blocked")):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": acl_decision.get("reason_code"),
                    "message": acl_decision.get("reason"),
                    "acl": acl_decision,
                },
            )
        save_prompt("conversation_style_prompt", content)
        return {
            "status": "success",
            "message": "提示词更新成功",
            "acl": acl_decision,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新系统提示词失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"更新系统提示词失败: {str(e)}")


def _normalize_prompt_template_name(name: str) -> str:
    normalized = str(name or "").strip()
    if normalized.lower().endswith(".txt"):
        normalized = normalized[:-4]
    if not normalized:
        raise HTTPException(status_code=400, detail="提示词名称不能为空")
    if len(normalized) > 128:
        raise HTTPException(status_code=400, detail="提示词名称过长")
    if not all(ch.isalnum() or ch == "_" for ch in normalized):
        raise HTTPException(status_code=400, detail="提示词名称仅允许字母、数字、下划线")
    return normalized


def _build_prompt_template_meta(path: Path) -> Dict[str, Any]:
    from datetime import datetime, timezone

    stat = path.stat()
    return {
        "name": path.stem,
        "filename": path.name,
        "size_bytes": int(stat.st_size),
        "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def _list_prompt_template_metas() -> List[Dict[str, Any]]:
    from system.config import get_prompt_manager

    manager = get_prompt_manager()
    prompts_dir = Path(manager.prompts_dir)
    prompts_dir.mkdir(parents=True, exist_ok=True)
    items: List[Dict[str, Any]] = []
    for item in sorted(prompts_dir.glob("*.txt"), key=lambda p: p.name.lower()):
        if not item.is_file():
            continue
        items.append(_build_prompt_template_meta(item))
    return items


@app.get("/system/prompts")
async def list_system_prompts():
    try:
        return {"status": "success", "prompts": _list_prompt_template_metas()}
    except Exception as e:
        logger.error(f"读取提示词列表失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"读取提示词列表失败: {str(e)}")


@app.get("/v1/system/prompts")
async def list_system_prompts_v1():
    return await list_system_prompts()


@app.get("/system/prompts/{name}")
async def get_system_prompt_template(name: str):
    try:
        from system.config import get_prompt_manager

        normalized = _normalize_prompt_template_name(name)
        manager = get_prompt_manager()
        prompt_file = Path(manager.prompts_dir) / f"{normalized}.txt"
        if not prompt_file.exists():
            raise HTTPException(status_code=404, detail=f"提示词不存在: {normalized}")
        content = prompt_file.read_text(encoding="utf-8")
        return {
            "status": "success",
            "name": normalized,
            "content": content,
            "meta": _build_prompt_template_meta(prompt_file),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"读取提示词失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"读取提示词失败: {str(e)}")


@app.get("/v1/system/prompts/{name}")
async def get_system_prompt_template_v1(name: str):
    return await get_system_prompt_template(name)


@app.post("/system/prompts/{name}")
async def update_system_prompt_template(name: str, payload: Dict[str, Any]):
    try:
        from system.config import save_prompt, evaluate_prompt_acl

        normalized = _normalize_prompt_template_name(name)
        content = payload.get("content")
        if not isinstance(content, str):
            raise HTTPException(status_code=400, detail="缺少content参数或类型错误")
        approval_ticket = str(payload.get("approval_ticket") or "").strip()
        change_reason = str(payload.get("change_reason") or "").strip()
        acl_decision = evaluate_prompt_acl(
            prompt_name=normalized,
            approval_ticket=approval_ticket,
            change_reason=change_reason,
        )
        if bool(acl_decision.get("blocked")):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": acl_decision.get("reason_code"),
                    "message": acl_decision.get("reason"),
                    "acl": acl_decision,
                },
            )
        save_prompt(normalized, content)
        return {
            "status": "success",
            "message": "提示词更新成功",
            "name": normalized,
            "acl": acl_decision,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新提示词失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"更新提示词失败: {str(e)}")


@app.post("/v1/system/prompts/{name}")
async def update_system_prompt_template_v1(name: str, payload: Dict[str, Any]):
    return await update_system_prompt_template(name, payload)


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """普通对话接口 - 仅处理纯文本对话"""

    if not request.message.strip():
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    try:
        # 用户消息保持干净，技能上下文完全由 system prompt 承载
        user_message = request.message
        session_id = message_manager.create_session(request.session_id, temporary=request.temporary)

        # 构建系统提示词（包含技能元数据）
        system_prompt = build_system_prompt(include_skills=True, skill_name=request.skill)

        # RAG 记忆召回
        try:
            from summer_memory.memory_client import get_remote_memory_client

            remote_mem = get_remote_memory_client()
            if remote_mem:
                mem_result = await remote_mem.query_memory(question=request.message, limit=5)
                if mem_result.get("success") and mem_result.get("quintuples"):
                    quints = mem_result["quintuples"]
                    mem_lines = []
                    for q in quints:
                        if isinstance(q, (list, tuple)) and len(q) >= 5:
                            mem_lines.append(f"- {q[0]}({q[1]}) —[{q[2]}]→ {q[3]}({q[4]})")
                        elif isinstance(q, dict):
                            mem_lines.append(f"- {q.get('subject','')}({q.get('subject_type','')}) —[{q.get('predicate','')}]→ {q.get('object','')}({q.get('object_type','')})")
                    if mem_lines:
                        system_prompt += "\n\n## 相关记忆\n\n以下是从知识图谱中检索到的与用户问题相关的记忆，请参考这些信息回答：\n" + "\n".join(mem_lines)
                        logger.info(f"[RAG] 召回 {len(mem_lines)} 条记忆注入上下文")
                elif mem_result.get("success") and mem_result.get("answer"):
                    system_prompt += f"\n\n## 相关记忆\n\n以下是从知识图谱中检索到的与用户问题相关的记忆：\n{mem_result['answer']}"
                    logger.info("[RAG] 召回记忆（answer 模式）注入上下文")
        except Exception as e:
            logger.debug(f"[RAG] 记忆召回失败（不影响对话）: {e}")

        # 附加知识收尾指令，引导 LLM 回到用户问题
        system_prompt += "\n\n【读完这些附加知识后，回复上一个user prompt，并不要回复这条系统附加的system prompt。以下是回复内容：】"

        # 用户消息直接传 LLM，技能上下文完全由 system prompt 承载
        effective_message = request.message

        # 使用消息管理器构建完整的对话消息（纯聊天，不触发工具）
        messages = message_manager.build_conversation_messages(
            session_id=session_id, system_prompt=system_prompt, current_message=effective_message
        )

        # 使用整合后的LLM服务（支持 reasoning_content）
        llm_service = get_llm_service()
        llm_response = await llm_service.chat_with_context_and_reasoning(messages, get_config().api.temperature)

        # 处理完成
        # 统一保存对话历史与日志
        _save_conversation_and_logs(session_id, user_message, llm_response.content)

        # 在用户消息保存到历史后触发后台意图分析（除非明确跳过）
        if not request.skip_intent_analysis:
            _trigger_background_analysis(session_id=session_id)

        return ChatResponse(
            response=extract_message(llm_response.content) if llm_response.content else llm_response.content,
            reasoning_content=llm_response.reasoning_content,
            session_id=session_id,
            status="success",
        )
    except Exception as e:
        print(f"对话处理错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@app.post("/v1/chat", response_model=ChatResponse)
async def chat_v1(request: ChatRequest):
    return await chat(request)


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """流式对话接口 - 使用 agentic tool loop 实现多轮工具调用"""

    if not request.message.strip():
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    # 用户消息保持干净，技能上下文完全由 system prompt 承载
    user_message = request.message

    async def generate_response() -> AsyncGenerator[str, None]:
        complete_response_parts: List[str] = []
        try:
            # 获取或创建会话ID
            session_id = message_manager.create_session(request.session_id, temporary=request.temporary)

            # 发送会话ID信息
            yield f"data: session_id: {session_id}\n\n"

            route_meta = _resolve_chat_stream_route(request.message, session_id=session_id)
            route_meta = _apply_chat_route_quality_guard(route_meta)
            route_meta = _apply_path_b_clarify_budget(route_meta, session_id=session_id)
            route_meta = _apply_chat_route_router_arbiter_guard(route_meta, session_id=session_id)
            route_meta = _apply_outer_core_session_bridge(route_meta, outer_session_id=session_id)
            route_decision = route_meta.get("router_decision") if isinstance(route_meta.get("router_decision"), dict) else {}
            path = str(route_meta.get("path") or "path-c")
            execution_session_id = str(route_meta.get("execution_session_id") or session_id)
            # ====== Prompt Slice 引擎：resolve + serialize ======
            try:
                if _CHAT_LLM_GATEWAY is not None:
                    _gw_request = GatewayRouteRequest(
                        task_type=str(route_decision.get("task_type") or ""),
                        severity=str(route_meta.get("risk_level") or ""),
                        path=path,
                        prompt_profile=str(route_decision.get("prompt_profile") or ""),
                        injection_mode=str(route_decision.get("injection_mode") or ""),
                        delegation_intent=str(route_decision.get("delegation_intent") or ""),
                    )
                    _gw_prompt_input = PromptEnvelopeInput(static_header="", long_term_summary="")
                    _gw_resolve = _CHAT_LLM_GATEWAY.resolve(request=_gw_request, prompt_input=_gw_prompt_input)
                    _gw_selected = _gw_resolve.get("selected") or []
                    _gw_dropped = _gw_resolve.get("dropped") or []
                    _gw_cache = _CHAT_LLM_GATEWAY.serialize_for_cache(selected_slices=_gw_selected)
                    route_meta["_slice_selected"] = [s.slice_uid for s in _gw_selected if hasattr(s, "slice_uid")]
                    route_meta["_slice_dropped"] = [s.slice_uid for s in _gw_dropped if hasattr(s, "slice_uid")]
                    route_meta["_slice_selected_count"] = len(_gw_selected)
                    route_meta["_slice_dropped_count"] = len(_gw_dropped)
                    route_meta["_slice_prefix_hash"] = str(_gw_cache.get("prefix_hash") or "")
                    route_meta["_slice_tail_hash"] = str(_gw_cache.get("tail_hash") or "")
                    route_meta["_slice_selected_layers"] = sorted(set(
                        str(getattr(s, "layer", "")) for s in _gw_selected if getattr(s, "layer", "")
                    ))
            except Exception as _gw_exc:
                logger.debug("[prompt_slice] gateway resolve/serialize 降级: %s", _gw_exc)

            _emit_chat_route_prompt_event(route_meta, session_id=session_id)
            _emit_chat_route_guard_event(route_meta, session_id=session_id)
            _emit_chat_route_arbiter_event(route_meta, session_id=session_id)
            yield _format_sse_payload_chunk(
                {
                    "type": "route_decision",
                    "path": path,
                    "risk_level": route_meta.get("risk_level"),
                    "outer_readonly_hit": bool(route_meta.get("outer_readonly_hit")),
                    "core_escalation": bool(route_meta.get("core_escalation")),
                    "prompt_profile": route_decision.get("prompt_profile", ""),
                    "injection_mode": route_decision.get("injection_mode", ""),
                    "delegation_intent": route_decision.get("delegation_intent", ""),
                    "path_b_clarify_turns": int(route_meta.get("path_b_clarify_turns") or 0),
                    "path_b_clarify_limit": int(route_meta.get("path_b_clarify_limit") or _CHAT_ROUTE_PATH_B_CLARIFY_LIMIT),
                    "path_b_clarify_limit_override": route_meta.get("path_b_clarify_limit_override"),
                    "path_b_budget_escalated": bool(route_meta.get("path_b_budget_escalated")),
                    "path_b_budget_reason": str(route_meta.get("path_b_budget_reason") or ""),
                    "route_quality_guard_status": _ops_status_to_severity(
                        str(route_meta.get("route_quality_guard_status") or "unknown")
                    ),
                    "route_quality_guard_applied": bool(route_meta.get("route_quality_guard_applied")),
                    "route_quality_guard_action": str(route_meta.get("route_quality_guard_action") or ""),
                    "route_quality_guard_reason": str(route_meta.get("route_quality_guard_reason") or ""),
                    "route_quality_guard_reason_codes": _sanitize_route_quality_reason_codes(
                        route_meta.get("route_quality_guard_reason_codes")
                    ),
                    "route_quality_guard_path_before": str(route_meta.get("route_quality_guard_path_before") or ""),
                    "route_quality_guard_path_after": str(route_meta.get("route_quality_guard_path_after") or ""),
                    "router_arbiter_status": _ops_status_to_severity(
                        str(route_meta.get("router_arbiter_status") or "unknown")
                    ),
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
                        route_meta.get("router_arbiter_max_delegate_turns") or _CHAT_ROUTE_ARBITER_GUARD.max_delegate_turns
                    ),
                    "router_arbiter_conflict_ticket": str(route_meta.get("router_arbiter_conflict_ticket") or ""),
                    "router_arbiter_freeze": bool(route_meta.get("router_arbiter_freeze")),
                    "router_arbiter_hitl": bool(route_meta.get("router_arbiter_hitl")),
                    "router_arbiter_escalated": bool(route_meta.get("router_arbiter_escalated")),
                    "outer_session_id": str(route_meta.get("outer_session_id") or ""),
                    "core_session_id": str(route_meta.get("core_session_id") or ""),
                    "execution_session_id": execution_session_id,
                    "core_session_created": bool(route_meta.get("core_session_created")),
                    "selected_slice_count": int(route_meta.get("_slice_selected_count") or 0),
                    "dropped_slice_count": int(route_meta.get("_slice_dropped_count") or 0),
                    "prefix_hash": str(route_meta.get("_slice_prefix_hash") or ""),
                    "tail_hash": str(route_meta.get("_slice_tail_hash") or ""),
                }
            )
            logger.info(
                "[API Server] chat route decided outer_session=%s execution_session=%s path=%s intent=%s profile=%s guard=%s action=%s arbiter=%s arbiter_action=%s",
                session_id,
                execution_session_id,
                path,
                route_decision.get("delegation_intent", ""),
                route_decision.get("prompt_profile", ""),
                route_meta.get("route_quality_guard_status", "unknown"),
                route_meta.get("route_quality_guard_action", ""),
                route_meta.get("router_arbiter_status", "unknown"),
                route_meta.get("router_arbiter_action", ""),
            )

            # 构建系统提示词（按路径裁剪：Path-A/B 只读风格，Path-C Core 执行风格）
            system_prompt = build_system_prompt_for_path(
                path,
                include_skills=True,
                skill_name=request.skill,
            )

            # ====== RAG 记忆召回：在发送 LLM 前检索相关记忆 ======
            try:
                from summer_memory.memory_client import get_remote_memory_client

                remote_mem = get_remote_memory_client()
                if remote_mem:
                    mem_result = await remote_mem.query_memory(question=request.message, limit=5)
                    if mem_result.get("success") and mem_result.get("quintuples"):
                        quints = mem_result["quintuples"]
                        mem_lines = []
                        for q in quints:
                            if isinstance(q, (list, tuple)) and len(q) >= 5:
                                mem_lines.append(f"- {q[0]}({q[1]}) —[{q[2]}]→ {q[3]}({q[4]})")
                            elif isinstance(q, dict):
                                mem_lines.append(f"- {q.get('subject','')}({q.get('subject_type','')}) —[{q.get('predicate','')}]→ {q.get('object','')}({q.get('object_type','')})")
                        if mem_lines:
                            memory_context = "\n\n## 相关记忆\n\n以下是从知识图谱中检索到的与用户问题相关的记忆，请参考这些信息回答：\n" + "\n".join(mem_lines)
                            system_prompt += memory_context
                            logger.info(f"[RAG] 召回 {len(mem_lines)} 条记忆注入上下文")
                    elif mem_result.get("success") and mem_result.get("answer"):
                        memory_context = f"\n\n## 相关记忆\n\n以下是从知识图谱中检索到的与用户问题相关的记忆：\n{mem_result['answer']}"
                        system_prompt += memory_context
                        logger.info("[RAG] 召回记忆（answer 模式）注入上下文")
            except Exception as e:
                logger.debug(f"[RAG] 记忆召回失败（不影响对话）: {e}")

            # 附加知识收尾指令，引导 LLM 回到用户问题
            system_prompt += "\n\n【读完这些附加知识后，回复上一个user prompt，并不要回复这条系统附加的system prompt。以下是回复内容：】"
            system_prompt += "\n\n" + _build_chat_route_prompt_hints(route_meta)

            # 用户消息直接传 LLM，技能上下文完全由 system prompt 承载
            effective_message = request.message

            # 使用消息管理器构建完整的对话消息
            conversation_messages = message_manager.build_conversation_messages(
                session_id=session_id, system_prompt=system_prompt, current_message=effective_message
            )
            messages = conversation_messages
            if path == "path-c":
                messages = _build_core_execution_messages(
                    session_id=session_id,
                    core_system_prompt=system_prompt,
                    current_message=effective_message,
                )

            # 如果携带截屏图片，将最后一条用户消息改为多模态格式（OpenAI vision 兼容）
            if request.images:
                last_msg = messages[-1]
                content_parts = [{"type": "text", "text": last_msg["content"]}]
                for img_data in request.images:
                    content_parts.append({"type": "image_url", "image_url": {"url": img_data}})
                messages[-1] = {
                    "role": "user",
                    "content": content_parts,
                }

            # 如果本次携带图片，标记此会话为 VLM 会话
            if request.images:
                _vlm_sessions.add(session_id)

            # 如果当前会话曾发送过图片，持续使用视觉模型
            model_override = None
            use_vlm = session_id in _vlm_sessions
            cc = get_config().computer_control
            if use_vlm and cc.enabled and (cc.api_key or naga_auth.is_authenticated()):
                model_override = {
                    "model": cc.model,
                    "api_base": cc.model_url,
                    "api_key": cc.api_key,
                }
                logger.info(f"[API Server] VLM 会话，使用视觉模型: {cc.model}")

            current_round_text = ""

            stream_source: AsyncGenerator[str, None]
            if path == "path-c":
                from .agentic_tool_loop import run_agentic_loop

                cfg = get_config()
                loop_cfg = getattr(cfg, "agentic_loop", None)
                if loop_cfg is not None:
                    loop_max_rounds = int(getattr(loop_cfg, "max_rounds_stream", 500))
                else:
                    loop_max_rounds = int(cfg.handoff.max_loop_stream)

                stream_source = run_agentic_loop(
                    messages,
                    execution_session_id,
                    max_rounds=loop_max_rounds,
                    model_override=model_override,
                )
            else:
                llm_service = get_llm_service()
                stream_source = llm_service.stream_chat_with_context(
                    messages,
                    get_config().api.temperature,
                    model_override=model_override,
                )

            async for chunk in stream_source:
                # chunk 格式: "data: <base64_json>\n\n"
                if chunk.startswith("data: "):
                    try:
                        import json as json_module

                        data_str = chunk[6:].strip()
                        if data_str and data_str != "[DONE]":
                            decoded = base64.b64decode(data_str).decode("utf-8")
                            chunk_data = json_module.loads(decoded)
                            chunk_type = chunk_data.get("type", "content")
                            chunk_text = chunk_data.get("text", "")

                            if chunk_type == "content":
                                current_round_text += chunk_text
                                complete_response_parts.append(chunk_text)
                            elif chunk_type == "reasoning":
                                pass
                            elif chunk_type == "round_end":
                                current_round_text = ""

                            # 透传所有 chunk 给前端（content/reasoning/tool events）
                            yield chunk
                            continue
                    except Exception as e:
                        logger.error(f"[API Server] 流式数据解析错误: {e}")

                yield chunk

            # ====== 流式处理完成 ======

            # 获取完整文本用于保存
            complete_response = "".join(complete_response_parts)

            # fallback: 如果没有累积到文本，使用最后一轮的 current_round_text
            if not complete_response and current_round_text:
                complete_response = current_round_text

            # 统一保存对话历史与日志
            _save_conversation_and_logs(session_id, user_message, complete_response)

            # Agentic loop 模式下跳过后台意图分析（工具调用已在loop中处理）
            # 仅在非 agentic 模式或明确需要时触发后台分析
            if not request.skip_intent_analysis:
                # 预留后台分析入口（当前流式主链不在此处分发额外UI动作）
                pass

            # [DONE] 信号已由 llm_service.stream_chat_with_context 发送，无需重复

        except Exception as e:
            print(f"流式对话处理错误: {e}")
            traceback.print_exc()
            yield f"data: error:{str(e)}\n\n"

    return StreamingResponse(
        generate_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "X-Accel-Buffering": "no",  # 禁用nginx缓冲
        },
    )


@app.post("/v1/chat/stream")
async def chat_stream_v1(request: ChatRequest):
    return await chat_stream(request)


@app.api_route("/tools/search", methods=["GET", "POST"])
async def proxy_search(request: Request):
    """Remote proxy disabled in local-only mode."""
    raise HTTPException(status_code=410, detail="Remote tool search proxy is disabled in local-only mode")


@app.get("/memory/stats")
async def get_memory_stats():
    """获取记忆统计信息"""

    try:
        # 优先使用远程 NagaMemory 服务
        from summer_memory.memory_client import get_remote_memory_client

        remote = get_remote_memory_client()
        if remote is not None:
            stats = await remote.get_stats()
            return {"status": "success", "memory_stats": stats}

        # 回退到本地 summer_memory
        try:
            from summer_memory.memory_manager import memory_manager

            if memory_manager and memory_manager.enabled:
                stats = memory_manager.get_memory_stats()
                return {"status": "success", "memory_stats": stats}
            else:
                return {"status": "success", "memory_stats": {"enabled": False, "message": "记忆系统未启用"}}
        except ImportError:
            return {"status": "success", "memory_stats": {"enabled": False, "message": "记忆系统模块未找到"}}
    except Exception as e:
        print(f"获取记忆统计错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取记忆统计失败: {str(e)}")


# ============ MCP Server 代理 ============
# [已禁用] MCP Server 已从 main.py 启动流程中移除，旧代理端点调用 _call_mcpserver 必定 503
# @app.get("/mcp/status")
# async def get_mcp_status_proxy():
#     """代理 MCP Server 状态查询"""
#     return await _call_mcpserver("GET", "/status")
#
# @app.get("/mcp/tasks")
# async def get_mcp_tasks_proxy(status: Optional[str] = None):
#     """代理 MCP 任务列表"""
#     params = {"status": status} if status else None
#     return await _call_mcpserver("GET", "/tasks", params=params)


def _build_mcp_runtime_snapshot(
    *,
    registry_status: Optional[Dict[str, Any]] = None,
    external_services: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """构建 MCP 运行时状态快照（供 /mcp/status 与 /mcp/tasks 复用）。"""
    from datetime import datetime

    if registry_status is None:
        try:
            from mcpserver.mcp_registry import auto_register_mcp, get_registry_status

            auto_register_mcp()
            registry_status = get_registry_status()
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning(f"构建 MCP registry 状态失败: {exc}")
            registry_status = {"registered_services": 0, "service_names": []}

    if external_services is None:
        cfg = _load_mcporter_config()
        external_cfg = cfg.get("mcpServers", {}) if isinstance(cfg, dict) else {}
        external_services = list(external_cfg.keys()) if isinstance(external_cfg, dict) else []

    builtin_names = [str(x) for x in (registry_status.get("service_names") or []) if str(x).strip()]
    external_names = [str(x) for x in (external_services or []) if str(x).strip() and str(x) not in builtin_names]
    service_total = len(builtin_names) + len(external_names)

    return {
        "server": "online" if service_total > 0 else "offline",
        "timestamp": datetime.now().isoformat(),
        "tasks": {
            "total": service_total,
            "active": 0,
            "completed": len(builtin_names),
            "failed": 0,
        },
        "registry": {
            "registered_services": int(registry_status.get("registered_services") or 0),
            "cached_manifests": int(registry_status.get("cached_manifests") or 0),
            "service_names": builtin_names,
            "external_service_names": external_names,
        },
        "scheduler": {
            "source": "registry_snapshot",
            "tracked_tasks": service_total,
        },
    }


def _build_mcp_task_snapshot(
    status: Optional[str] = None,
    *,
    snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if snapshot is None:
        snapshot = _build_mcp_runtime_snapshot()
    registry = snapshot.get("registry", {}) if isinstance(snapshot, dict) else {}

    tasks: List[Dict[str, Any]] = []
    for name in registry.get("service_names", []) or []:
        tasks.append(
            {
                "task_id": f"builtin:{name}",
                "service_name": str(name),
                "status": "registered",
                "source": "builtin",
            }
        )
    for name in registry.get("external_service_names", []) or []:
        tasks.append(
            {
                "task_id": f"mcporter:{name}",
                "service_name": str(name),
                "status": "configured",
                "source": "mcporter",
            }
        )

    normalized_filter = str(status or "").strip().lower()
    if normalized_filter:
        tasks = [item for item in tasks if str(item.get("status", "")).lower() == normalized_filter]

    return {"tasks": tasks, "total": len(tasks)}


def _ops_utc_iso_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _ops_repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _ops_unix_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _ops_status_to_severity(status: str) -> str:
    normalized = str(status or "unknown").strip().lower()
    if normalized in {"ok", "healthy", "success"}:
        return "ok"
    if normalized in {"warning", "warn"}:
        return "warning"
    if normalized in {"critical", "error", "failed", "fail"}:
        return "critical"
    return "unknown"


_OPS_STATUS_RANK: Dict[str, int] = {
    "unknown": 0,
    "ok": 1,
    "warning": 2,
    "critical": 3,
}


def _ops_metric_status(value: Any) -> str:
    if not isinstance(value, dict):
        return "unknown"
    return _ops_status_to_severity(str(value.get("status") or "unknown"))


def _ops_max_status(statuses: List[str]) -> str:
    current = "unknown"
    current_rank = _OPS_STATUS_RANK[current]
    for status in statuses:
        normalized = _ops_status_to_severity(status)
        rank = _OPS_STATUS_RANK.get(normalized, 0)
        if rank > current_rank:
            current = normalized
            current_rank = rank
    return current


def _ops_route_event_status(payload: Dict[str, Any]) -> str:
    outer_readonly = bool(payload.get("outer_readonly_hit"))
    readonly_exposed = bool(payload.get("readonly_write_tool_exposed"))
    readonly_selected_count = _ops_safe_int(payload.get("readonly_write_tool_selected_count"), default=0)
    readonly_exposure_hit = outer_readonly and (readonly_exposed or readonly_selected_count > 0)
    guard_status = _ops_status_to_severity(str(payload.get("route_quality_guard_status") or "unknown"))
    if readonly_exposure_hit:
        return "critical"
    if guard_status == "critical":
        return "critical"
    if bool(payload.get("path_b_budget_escalated")):
        return "warning"
    if guard_status == "warning" and bool(payload.get("route_quality_guard_applied")):
        return "warning"
    if bool(payload.get("core_session_created")):
        return "warning"
    return "ok"


def _ops_build_route_quality_trend(
    events_file: Path,
    *,
    window_size: int = 20,
    max_windows: int = 6,
) -> Dict[str, Any]:
    step = max(1, int(window_size))
    max_window_count = max(1, int(max_windows))
    rows = _ops_read_event_rows(events_file, limit=max(200, step * max_window_count * 8))
    prompt_rows: List[Dict[str, Any]] = []
    for row in rows:
        if str(row.get("event_type") or "").strip() != "PromptInjectionComposed":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        prompt_rows.append(
            {
                "timestamp": str(row.get("timestamp") or ""),
                "payload": payload,
            }
        )

    if not prompt_rows:
        return {
            "status": "unknown",
            "direction": "unknown",
            "volatility": None,
            "windows": [],
            "sample_count": 0,
            "window_size": step,
            "reason": "no_prompt_injection_events",
        }

    capped = prompt_rows[-step * max_window_count :]
    windows: List[Dict[str, Any]] = []
    for start in range(0, len(capped), step):
        segment = capped[start : start + step]
        if not segment:
            continue
        statuses = [_ops_route_event_status(item.get("payload") if isinstance(item.get("payload"), dict) else {}) for item in segment]
        total = len(statuses)
        critical_count = sum(1 for status in statuses if status == "critical")
        warning_count = sum(1 for status in statuses if status == "warning")
        ok_count = sum(1 for status in statuses if status == "ok")
        window_status = _ops_max_status(statuses)
        score = ((ok_count * 1.0) + (warning_count * 0.6) + (critical_count * 0.25)) / float(total)
        windows.append(
            {
                "start_at": str(segment[0].get("timestamp") or ""),
                "end_at": str(segment[-1].get("timestamp") or ""),
                "sample_count": total,
                "status": window_status,
                "critical_ratio": critical_count / float(total),
                "warning_ratio": warning_count / float(total),
                "score": round(score, 4),
            }
        )

    if not windows:
        return {
            "status": "unknown",
            "direction": "unknown",
            "volatility": None,
            "windows": [],
            "sample_count": 0,
            "window_size": step,
            "reason": "no_window_aggregates",
        }

    latest = windows[-1]
    first = windows[0]
    delta = float(latest.get("score") or 0.0) - float(first.get("score") or 0.0)
    if delta >= 0.08:
        direction = "improving"
    elif delta <= -0.08:
        direction = "degrading"
    else:
        direction = "stable"

    transitions = 0
    for idx in range(1, len(windows)):
        prev_status = str(windows[idx - 1].get("status") or "unknown")
        current_status = str(windows[idx].get("status") or "unknown")
        if prev_status != current_status:
            transitions += 1
    volatility = (transitions / float(len(windows) - 1)) if len(windows) > 1 else 0.0

    latest_status = _ops_status_to_severity(str(latest.get("status") or "unknown"))
    trend_status = latest_status
    if latest_status == "ok":
        if direction == "degrading" and float(latest.get("score") or 0.0) < 0.7:
            trend_status = "warning"
        elif volatility >= 0.7:
            trend_status = "warning"
    elif latest_status == "warning" and direction == "degrading" and float(latest.get("score") or 0.0) < 0.5:
        trend_status = "critical"

    return {
        "status": trend_status,
        "direction": direction,
        "volatility": round(volatility, 4),
        "windows": windows,
        "sample_count": len(capped),
        "window_size": step,
        "latest_window_status": latest_status,
    }


def _ops_build_route_quality_summary(
    metrics: Dict[str, Any],
    *,
    trend: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    outer_readonly = metrics.get("outer_readonly_hit_rate") if isinstance(metrics.get("outer_readonly_hit_rate"), dict) else {}
    readonly_exposure = (
        metrics.get("readonly_write_tool_exposure_rate")
        if isinstance(metrics.get("readonly_write_tool_exposure_rate"), dict)
        else {}
    )
    route_distribution = (
        metrics.get("chat_route_path_distribution")
        if isinstance(metrics.get("chat_route_path_distribution"), dict)
        else {}
    )
    path_b_budget_escalation = (
        metrics.get("path_b_budget_escalation_rate")
        if isinstance(metrics.get("path_b_budget_escalation_rate"), dict)
        else {}
    )
    core_session_creation = (
        metrics.get("core_session_creation_rate")
        if isinstance(metrics.get("core_session_creation_rate"), dict)
        else {}
    )

    status_map = {
        "outer_readonly_hit_rate": _ops_metric_status(outer_readonly),
        "readonly_write_tool_exposure_rate": _ops_metric_status(readonly_exposure),
        "chat_route_path_distribution": _ops_metric_status(route_distribution),
        "path_b_budget_escalation_rate": _ops_metric_status(path_b_budget_escalation),
        "core_session_creation_rate": _ops_metric_status(core_session_creation),
    }
    trend_payload = trend if isinstance(trend, dict) else {}
    trend_status = _ops_status_to_severity(str(trend_payload.get("status") or "unknown"))
    overall_status = _ops_max_status([*list(status_map.values()), trend_status])

    reason_codes: List[str] = []
    if status_map["readonly_write_tool_exposure_rate"] == "critical":
        reason_codes.append("READONLY_WRITE_EXPOSURE_CRITICAL")
    elif status_map["readonly_write_tool_exposure_rate"] == "warning":
        reason_codes.append("READONLY_WRITE_EXPOSURE_WARNING")

    if status_map["path_b_budget_escalation_rate"] == "critical":
        reason_codes.append("PATH_B_BUDGET_ESCALATION_CRITICAL")
    elif status_map["path_b_budget_escalation_rate"] == "warning":
        reason_codes.append("PATH_B_BUDGET_ESCALATION_WARNING")

    if status_map["core_session_creation_rate"] == "critical":
        reason_codes.append("CORE_SESSION_CREATION_CRITICAL")
    elif status_map["core_session_creation_rate"] == "warning":
        reason_codes.append("CORE_SESSION_CREATION_WARNING")

    if status_map["outer_readonly_hit_rate"] == "critical":
        reason_codes.append("OUTER_READONLY_HIT_CRITICAL")
    elif status_map["outer_readonly_hit_rate"] == "warning":
        reason_codes.append("OUTER_READONLY_HIT_WARNING")

    direction = str(trend_payload.get("direction") or "unknown")
    if trend_status == "critical":
        reason_codes.append("ROUTE_QUALITY_TREND_CRITICAL")
    elif trend_status == "warning":
        reason_codes.append("ROUTE_QUALITY_TREND_WARNING")
    if direction == "degrading":
        reason_codes.append("ROUTE_QUALITY_TREND_DEGRADING")

    if not reason_codes and overall_status == "ok":
        reason_codes.append("ROUTE_QUALITY_HEALTHY")
    if not reason_codes and overall_status == "unknown":
        reason_codes.append("ROUTE_QUALITY_SIGNAL_UNKNOWN")

    reason_text = ""
    if overall_status == "critical":
        reason_text = "Route-quality guard is critical; investigate routing drift, exposure, and escalation pressure."
    elif overall_status == "warning":
        reason_text = "Route-quality guard is warning; monitor exposure, escalation, and core session churn."
    elif overall_status == "ok":
        reason_text = "Route-quality guard is healthy."
    else:
        reason_text = "Route-quality signals are insufficient."

    return {
        "status": overall_status,
        "reason_codes": reason_codes,
        "reason_text": reason_text,
        "signal_status": status_map,
        "path_ratios": route_distribution.get("path_ratios", {}) if isinstance(route_distribution, dict) else {},
        "trend": trend_payload,
    }


_OPS_REQUIRED_REPORT_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "id": "full_chain_m0_m12",
        "label": "Release Closure Chain M0-M12",
        "relative_path": "scratch/reports/release_closure_chain_full_m0_m12_result.json",
        "gate_level": "hard",
    },
    {
        "id": "cutover_status_ws27_002",
        "label": "WS27-002 Cutover Status",
        "relative_path": "scratch/reports/ws27_subagent_cutover_status_ws27_002.json",
        "gate_level": "hard",
    },
    {
        "id": "oob_drill_ws27_003",
        "label": "WS27-003 OOB Repair Drill",
        "relative_path": "scratch/reports/ws27_oob_repair_drill_ws27_003.json",
        "gate_level": "hard",
    },
    {
        "id": "doc_consistency_ws27_005",
        "label": "WS27-005 Doc Consistency",
        "relative_path": "scratch/reports/ws27_m12_doc_consistency_ws27_005.json",
        "gate_level": "hard",
    },
    {
        "id": "wallclock_acceptance_ws27_001",
        "label": "WS27-001 72h Wallclock Acceptance",
        "relative_path": "scratch/reports/ws27_72h_wallclock_acceptance_ws27_001.json",
        "gate_level": "soft",
    },
    {
        "id": "release_report_ws27_006",
        "label": "WS27-006 Release Report",
        "relative_path": "scratch/reports/phase3_full_release_report_ws27_006.json",
        "gate_level": "soft",
    },
    {
        "id": "signoff_chain_ws27_006",
        "label": "WS27-006 Signoff Chain",
        "relative_path": "scratch/reports/release_phase3_full_signoff_chain_ws27_006_result.json",
        "gate_level": "soft",
    },
]

_OPS_INCIDENT_EVENT_SEVERITY: Dict[str, str] = {
    "IncidentOpened": "critical",
    "SubAgentRuntimeAutoDegraded": "critical",
    "LeaseLost": "critical",
    "RouteQualityGuardEscalatedCritical": "critical",
    "RouteArbiterGuardEscalatedCritical": "critical",
    "SubAgentRuntimeFailOpenBlocked": "warning",
    "SubAgentRuntimeFailOpen": "warning",
    "RouteQualityGuardEscalatedWarning": "warning",
    "RouteArbiterGuardEscalatedWarning": "warning",
}

_OPS_BRAINSTEM_HEARTBEAT_RELATIVE_PATH = Path("scratch/runtime/brainstem_control_plane_heartbeat_ws23_001.json")
_OPS_BRAINSTEM_HEARTBEAT_STALE_WARNING_SECONDS = 120.0
_OPS_BRAINSTEM_HEARTBEAT_STALE_CRITICAL_SECONDS = 300.0
_OPS_WATCHDOG_DAEMON_STATE_RELATIVE_PATH = Path("scratch/runtime/watchdog_daemon_state_ws28_025.json")
_OPS_WATCHDOG_DAEMON_STALE_WARNING_SECONDS = 120.0
_OPS_WATCHDOG_DAEMON_STALE_CRITICAL_SECONDS = 300.0


def _ops_read_json_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _ops_parse_iso_datetime(value: Any) -> Optional[float]:
    from datetime import datetime

    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _ops_extract_failed_checks(payload: Dict[str, Any]) -> List[str]:
    checks = payload.get("checks")
    if not isinstance(checks, dict):
        return []
    failed: List[str] = []
    for key, value in checks.items():
        if value is False:
            failed.append(str(key))
    return failed


def _ops_build_brainstem_control_plane_summary(repo_root: Path) -> Dict[str, Any]:
    heartbeat_file = repo_root / _OPS_BRAINSTEM_HEARTBEAT_RELATIVE_PATH
    heartbeat_payload = _ops_read_json_file(heartbeat_file)
    generated_at = str(heartbeat_payload.get("generated_at") or "")
    generated_ts = _ops_parse_iso_datetime(generated_at)
    now_ts = time.time()
    heartbeat_age_seconds: Optional[float] = None
    if generated_ts is not None:
        heartbeat_age_seconds = max(0.0, round(now_ts - generated_ts, 3))

    raw_unhealthy_services = heartbeat_payload.get("unhealthy_services")
    unhealthy_services: List[str] = []
    if isinstance(raw_unhealthy_services, list):
        unhealthy_services = [str(item) for item in raw_unhealthy_services if str(item).strip()]

    healthy_value = heartbeat_payload.get("healthy")
    healthy: Optional[bool]
    if isinstance(healthy_value, bool):
        healthy = healthy_value
    else:
        healthy = None

    status = "unknown"
    reason_code = "BRAINSTEM_HEARTBEAT_MISSING"
    reason_text = "Brainstem control-plane heartbeat file is missing."
    if heartbeat_file.exists():
        status = "unknown"
        reason_code = "BRAINSTEM_HEARTBEAT_NO_SIGNAL"
        reason_text = "Brainstem heartbeat file exists but lacks valid health signal."
        if generated_ts is None:
            status = "warning"
            reason_code = "BRAINSTEM_HEARTBEAT_TIMESTAMP_INVALID"
            reason_text = "Brainstem heartbeat timestamp is missing or invalid."
        elif heartbeat_age_seconds is not None and heartbeat_age_seconds > float(_OPS_BRAINSTEM_HEARTBEAT_STALE_CRITICAL_SECONDS):
            status = "critical"
            reason_code = "BRAINSTEM_HEARTBEAT_STALE_CRITICAL"
            reason_text = "Brainstem heartbeat is stale beyond critical threshold."
        elif heartbeat_age_seconds is not None and heartbeat_age_seconds > float(_OPS_BRAINSTEM_HEARTBEAT_STALE_WARNING_SECONDS):
            status = "warning"
            reason_code = "BRAINSTEM_HEARTBEAT_STALE_WARNING"
            reason_text = "Brainstem heartbeat is stale beyond warning threshold."
        elif healthy is False or unhealthy_services:
            status = "critical"
            reason_code = "BRAINSTEM_HEALTH_UNHEALTHY"
            reason_text = "Brainstem daemon reports unhealthy services."
        elif healthy is True:
            status = "ok"
            reason_code = "OK"
            reason_text = "Brainstem daemon heartbeat is healthy."
        else:
            status = "warning"
            reason_code = "BRAINSTEM_HEALTH_UNKNOWN"
            reason_text = "Brainstem heartbeat is fresh but healthy flag is missing."

    return {
        "status": _ops_status_to_severity(status),
        "reason_code": reason_code,
        "reason_text": reason_text,
        "heartbeat_file": _ops_unix_path(heartbeat_file),
        "exists": heartbeat_file.exists(),
        "generated_at": generated_at,
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "stale_warning_seconds": float(_OPS_BRAINSTEM_HEARTBEAT_STALE_WARNING_SECONDS),
        "stale_critical_seconds": float(_OPS_BRAINSTEM_HEARTBEAT_STALE_CRITICAL_SECONDS),
        "healthy": healthy,
        "service_count": _ops_safe_int(heartbeat_payload.get("service_count"), default=0),
        "tick": _ops_safe_int(heartbeat_payload.get("tick"), default=0),
        "mode": str(heartbeat_payload.get("mode") or ""),
        "pid": _ops_safe_int(heartbeat_payload.get("pid"), default=0),
        "state_file": str(heartbeat_payload.get("state_file") or ""),
        "spec_file": str(heartbeat_payload.get("spec_file") or ""),
        "unhealthy_services": unhealthy_services,
    }


def _ops_build_watchdog_daemon_summary(repo_root: Path) -> Dict[str, Any]:
    state_file = repo_root / _OPS_WATCHDOG_DAEMON_STATE_RELATIVE_PATH
    state = WatchdogDaemon.read_daemon_state(
        state_file,
        stale_warning_seconds=float(_OPS_WATCHDOG_DAEMON_STALE_WARNING_SECONDS),
        stale_critical_seconds=float(_OPS_WATCHDOG_DAEMON_STALE_CRITICAL_SECONDS),
    )
    action_payload = state.get("action") if isinstance(state.get("action"), dict) else {}
    snapshot = state.get("snapshot") if isinstance(state.get("snapshot"), dict) else {}
    return {
        "status": _ops_status_to_severity(str(state.get("status") or "unknown")),
        "reason_code": str(state.get("reason_code") or ""),
        "reason_text": str(state.get("reason_text") or ""),
        "state_file": str(state.get("state_file") or _ops_unix_path(state_file)),
        "exists": bool(state_file.exists()),
        "generated_at": str(state.get("generated_at") or ""),
        "heartbeat_age_seconds": state.get("heartbeat_age_seconds"),
        "stale_warning_seconds": float(state.get("stale_warning_seconds") or _OPS_WATCHDOG_DAEMON_STALE_WARNING_SECONDS),
        "stale_critical_seconds": float(
            state.get("stale_critical_seconds") or _OPS_WATCHDOG_DAEMON_STALE_CRITICAL_SECONDS
        ),
        "state": str(state.get("state") or ""),
        "tick": _ops_safe_int(state.get("tick"), default=0),
        "pid": _ops_safe_int(state.get("pid"), default=0),
        "mode": str(state.get("mode") or ""),
        "warn_only": bool(state.get("warn_only")),
        "threshold_hit": bool(state.get("threshold_hit")),
        "action": action_payload,
        "snapshot": snapshot,
    }


def _ops_build_immutable_dna_summary() -> Dict[str, Any]:
    preflight = getattr(app.state, "immutable_dna_preflight", None)
    if not isinstance(preflight, dict):
        return {
            "status": "unknown",
            "reason_code": "IMMUTABLE_DNA_PREFLIGHT_MISSING",
            "reason_text": "Immutable DNA startup preflight is missing.",
            "enabled": True,
            "required": True,
            "passed": False,
            "exists": False,
            "manifest_path": "",
            "audit_file": "",
            "verify": {},
        }

    enabled = bool(preflight.get("enabled", True))
    required = bool(preflight.get("required", True))
    passed = bool(preflight.get("passed", False))
    reason = str(preflight.get("reason") or "")
    manifest_path = str(preflight.get("manifest_path") or "")
    audit_file = str(preflight.get("audit_file") or "")
    verify = preflight.get("verify") if isinstance(preflight.get("verify"), dict) else {}
    manifest_hash = str(preflight.get("manifest_hash") or verify.get("manifest_hash") or "")

    if not enabled:
        status = "warning"
        reason_code = "IMMUTABLE_DNA_RUNTIME_DISABLED"
        reason_text = "Immutable DNA runtime injection is disabled."
    elif passed:
        status = "ok"
        reason_code = "OK"
        reason_text = "Immutable DNA preflight passed."
    elif required:
        status = "critical"
        reason_code = "IMMUTABLE_DNA_PREFLIGHT_FAILED"
        reason_text = f"Immutable DNA preflight failed: {reason or 'unknown'}"
    else:
        status = "warning"
        reason_code = "IMMUTABLE_DNA_PREFLIGHT_FAILED_OPTIONAL"
        reason_text = f"Immutable DNA preflight failed (non-blocking): {reason or 'unknown'}"

    return {
        "status": _ops_status_to_severity(status),
        "reason_code": reason_code,
        "reason_text": reason_text,
        "enabled": enabled,
        "required": required,
        "passed": passed,
        "exists": bool(preflight),
        "manifest_path": manifest_path,
        "audit_file": audit_file,
        "manifest_hash": manifest_hash,
        "verify": verify,
    }


def _ops_collect_required_reports(repo_root: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for spec in _OPS_REQUIRED_REPORT_DEFINITIONS:
        relative_path = Path(str(spec["relative_path"]))
        absolute_path = repo_root / relative_path
        exists = absolute_path.exists()
        payload = _ops_read_json_file(absolute_path) if exists else {}
        passed_value = payload.get("passed")
        passed: Optional[bool]
        if isinstance(passed_value, bool):
            passed = passed_value
        else:
            passed = None
        failed_checks = _ops_extract_failed_checks(payload)
        status = "missing"
        if exists and passed is True:
            status = "passed"
        elif exists and passed is False:
            status = "failed"
        elif exists:
            status = "unknown"

        mtime_iso = ""
        try:
            if exists:
                from datetime import datetime, timezone

                mtime_iso = datetime.fromtimestamp(absolute_path.stat().st_mtime, tz=timezone.utc).isoformat()
        except OSError:
            mtime_iso = ""

        rows.append(
            {
                "id": str(spec["id"]),
                "label": str(spec["label"]),
                "gate_level": str(spec["gate_level"]),
                "path": _ops_unix_path(absolute_path),
                "exists": exists,
                "status": status,
                "passed": passed,
                "generated_at": str(payload.get("generated_at") or ""),
                "modified_at": mtime_iso,
                "scenario": str(payload.get("scenario") or payload.get("task_id") or ""),
                "failed_checks": failed_checks,
            }
        )
    return rows


def _ops_build_response(
    *,
    data: Dict[str, Any],
    severity: str,
    source_reports: Optional[List[str]] = None,
    source_endpoints: Optional[List[str]] = None,
    reason_code: Optional[str] = None,
    reason_text: Optional[str] = None,
    status: str = "success",
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "status": str(status or "success"),
        "generated_at": _ops_utc_iso_now(),
        "data": data,
        "severity": str(severity or "unknown"),
        "source_reports": list(source_reports or []),
        "source_endpoints": list(source_endpoints or []),
    }
    if reason_code:
        payload["reason_code"] = str(reason_code)
    if reason_text:
        payload["reason_text"] = str(reason_text)
    return payload


def _ops_build_runtime_posture_payload(events_limit: int = 5000) -> Dict[str, Any]:
    try:
        from scripts.export_slo_snapshot import build_snapshot

        repo_root = _ops_repo_root()
        snapshot = build_snapshot(repo_root=repo_root, events_limit=max(1, int(events_limit)))
    except Exception as exc:
        logger.error(f"构建 runtime posture 聚合失败: {exc}")
        raise

    metrics = snapshot.get("metrics") if isinstance(snapshot.get("metrics"), dict) else {}
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    threshold_profile = snapshot.get("threshold_profile") if isinstance(snapshot.get("threshold_profile"), dict) else {}
    sources = snapshot.get("sources") if isinstance(snapshot.get("sources"), dict) else {}
    events_file_raw = str(sources.get("events_file") or "").strip()
    events_file = Path(events_file_raw) if events_file_raw else Path("__missing_events_file__.jsonl")
    if events_file_raw and not events_file.is_absolute():
        events_file = _ops_repo_root() / events_file
    route_quality_trend = _ops_build_route_quality_trend(events_file, window_size=20, max_windows=6)
    execution_bridge_governance = _ops_build_execution_bridge_governance_summary(
        events_file=events_file,
        limit=max(200, int(events_limit)),
        issues_limit=20,
    )
    execution_bridge_governance_status = _ops_status_to_severity(str(execution_bridge_governance.get("status") or "unknown"))

    repo_root = _ops_repo_root()
    brainstem_control_plane = _ops_build_brainstem_control_plane_summary(repo_root)
    brainstem_status = _ops_status_to_severity(str(brainstem_control_plane.get("status") or "unknown"))
    watchdog_daemon = _ops_build_watchdog_daemon_summary(repo_root)
    watchdog_daemon_status = _ops_status_to_severity(str(watchdog_daemon.get("status") or "unknown"))
    immutable_dna = _ops_build_immutable_dna_summary()
    immutable_dna_status = _ops_status_to_severity(str(immutable_dna.get("status") or "unknown"))

    metric_status = summary.get("metric_status") if isinstance(summary.get("metric_status"), dict) else {}
    snapshot_overall_status = str(summary.get("overall_status") or "unknown")
    overall_status = _ops_max_status(
        [
            snapshot_overall_status,
            brainstem_status,
            watchdog_daemon_status,
            immutable_dna_status,
            execution_bridge_governance_status,
        ]
    )
    severity = _ops_status_to_severity(overall_status)

    ws26_runtime_report = repo_root / "scratch" / "reports" / "ws26_runtime_snapshot_ws26_002.json"
    source_reports: List[str] = []
    ws26_runtime_report_payload: Dict[str, Any] = {}

    if ws26_runtime_report.exists():
        source_reports.append(_ops_unix_path(ws26_runtime_report))
        try:
            loaded_payload = json.loads(ws26_runtime_report.read_text(encoding="utf-8"))
            if isinstance(loaded_payload, dict):
                ws26_runtime_report_payload = loaded_payload
        except (OSError, json.JSONDecodeError):
            pass

    for key in ("events_file", "workflow_db", "global_mutex_state", "autonomous_config"):
        path_value = sources.get(key)
        if isinstance(path_value, str) and path_value.strip():
            source_reports.append(path_value.replace("\\", "/"))

    if bool(brainstem_control_plane.get("exists")):
        source_reports.append(str(brainstem_control_plane.get("heartbeat_file") or ""))
    if bool(watchdog_daemon.get("exists")):
        source_reports.append(str(watchdog_daemon.get("state_file") or ""))
    if str(immutable_dna.get("manifest_path") or "").strip():
        source_reports.append(str(immutable_dna.get("manifest_path") or ""))
    if str(immutable_dna.get("audit_file") or "").strip():
        source_reports.append(str(immutable_dna.get("audit_file") or ""))

    response_data: Dict[str, Any] = {
        "summary": {
            "overall_status": overall_status,
            "metric_status": metric_status,
            "route_quality": _ops_build_route_quality_summary(metrics, trend=route_quality_trend),
            "brainstem_control_plane_status": brainstem_status,
            "watchdog_daemon_status": watchdog_daemon_status,
            "immutable_dna_status": immutable_dna_status,
            "execution_bridge_governance_status": execution_bridge_governance_status,
            "execution_bridge_governance_reason_codes": list(execution_bridge_governance.get("reason_codes") or []),
        },
        "metrics": {
            "runtime_rollout": metrics.get("runtime_rollout", {}),
            "runtime_fail_open": metrics.get("runtime_fail_open", {}),
            "runtime_lease": metrics.get("runtime_lease", {}),
            "queue_depth": metrics.get("queue_depth", {}),
            "lock_status": metrics.get("lock_status", {}),
            "disk_watermark_ratio": metrics.get("disk_watermark_ratio", {}),
            "error_rate": metrics.get("error_rate", {}),
            "latency_p95_ms": metrics.get("latency_p95_ms", {}),
            "prompt_slice_count_by_layer": metrics.get("prompt_slice_count_by_layer", {}),
            "outer_readonly_hit_rate": metrics.get("outer_readonly_hit_rate", {}),
            "readonly_write_tool_exposure_rate": metrics.get("readonly_write_tool_exposure_rate", {}),
            "chat_route_path_distribution": metrics.get("chat_route_path_distribution", {}),
            "path_b_budget_escalation_rate": metrics.get("path_b_budget_escalation_rate", {}),
            "core_session_creation_rate": metrics.get("core_session_creation_rate", {}),
            "brainstem_heartbeat": {
                "status": brainstem_status,
                "value": brainstem_control_plane.get("heartbeat_age_seconds"),
                "healthy": brainstem_control_plane.get("healthy"),
                "service_count": brainstem_control_plane.get("service_count"),
                "stale_warning_seconds": brainstem_control_plane.get("stale_warning_seconds"),
                "stale_critical_seconds": brainstem_control_plane.get("stale_critical_seconds"),
                "tick": brainstem_control_plane.get("tick"),
            },
            "watchdog_daemon": {
                "status": watchdog_daemon_status,
                "value": watchdog_daemon.get("heartbeat_age_seconds"),
                "tick": watchdog_daemon.get("tick"),
                "threshold_hit": watchdog_daemon.get("threshold_hit"),
                "warn_only": watchdog_daemon.get("warn_only"),
                "stale_warning_seconds": watchdog_daemon.get("stale_warning_seconds"),
                "stale_critical_seconds": watchdog_daemon.get("stale_critical_seconds"),
                "reason_code": watchdog_daemon.get("reason_code"),
            },
            "immutable_dna": {
                "status": immutable_dna_status,
                "enabled": immutable_dna.get("enabled"),
                "required": immutable_dna.get("required"),
                "passed": immutable_dna.get("passed"),
                "reason_code": immutable_dna.get("reason_code"),
                "manifest_hash": immutable_dna.get("manifest_hash"),
            },
            "execution_bridge_rejection_ratio": {
                "status": execution_bridge_governance_status,
                "value": execution_bridge_governance.get("rejection_ratio"),
                "subtask_total": execution_bridge_governance.get("subtask_total"),
                "subtask_rejected": execution_bridge_governance.get("subtask_rejected"),
            },
            "execution_bridge_governance_warning_ratio": {
                "status": execution_bridge_governance_status,
                "value": execution_bridge_governance.get("governed_warning_ratio"),
                "governed_rows_count": execution_bridge_governance.get("governed_rows_count"),
                "governed_warning_count": execution_bridge_governance.get("governed_warning_count"),
                "governed_critical_count": execution_bridge_governance.get("governed_critical_count"),
            },
        },
        "threshold_profile": threshold_profile,
        "sources": sources,
        "brainstem_control_plane": brainstem_control_plane,
        "watchdog_daemon": watchdog_daemon,
        "immutable_dna": immutable_dna,
        "execution_bridge_governance": execution_bridge_governance,
    }
    if ws26_runtime_report_payload:
        response_data["ws26_runtime_snapshot_report"] = ws26_runtime_report_payload

    reason_code: Optional[str] = None
    reason_text: Optional[str] = None
    if brainstem_status == "critical":
        reason_code = "BRAINSTEM_CONTROL_PLANE_CRITICAL"
        reason_text = str(brainstem_control_plane.get("reason_text") or "Brainstem control-plane is unhealthy.")
    elif watchdog_daemon_status == "critical":
        reason_code = "WATCHDOG_DAEMON_CRITICAL"
        reason_text = str(watchdog_daemon.get("reason_text") or "Watchdog daemon reports critical state.")
    elif immutable_dna_status == "critical":
        reason_code = "IMMUTABLE_DNA_CRITICAL"
        reason_text = str(immutable_dna.get("reason_text") or "Immutable DNA preflight failed.")
    elif execution_bridge_governance_status == "critical":
        reason_code = "EXECUTION_BRIDGE_GOVERNANCE_CRITICAL"
        reason_text = "Execution bridge governance has critical rejections; check role guards and policy contracts."
    elif brainstem_status == "warning":
        reason_code = "BRAINSTEM_CONTROL_PLANE_WARNING"
        reason_text = str(brainstem_control_plane.get("reason_text") or "Brainstem control-plane requires attention.")
    elif watchdog_daemon_status == "warning":
        reason_code = "WATCHDOG_DAEMON_WARNING"
        reason_text = str(watchdog_daemon.get("reason_text") or "Watchdog daemon requires attention.")
    elif immutable_dna_status == "warning":
        reason_code = "IMMUTABLE_DNA_WARNING"
        reason_text = str(immutable_dna.get("reason_text") or "Immutable DNA preflight requires attention.")
    elif execution_bridge_governance_status == "warning":
        reason_code = "EXECUTION_BRIDGE_GOVERNANCE_WARNING"
        reason_text = "Execution bridge governance has warning signals; review semantic/path guard drift."
    elif severity == "unknown":
        reason_code = "RUNTIME_SIGNAL_UNKNOWN"
        reason_text = "Runtime posture lacks enough signal coverage; verify events/workflow inputs."

    return _ops_build_response(
        data=response_data,
        severity=severity,
        source_reports=sorted(set(source_reports)),
        source_endpoints=[],
        reason_code=reason_code,
        reason_text=reason_text,
    )


def _ops_build_mcp_fabric_payload() -> Dict[str, Any]:
    registry_status: Dict[str, Any]
    reason_code: Optional[str] = None
    reason_text: Optional[str] = None

    try:
        from mcpserver.mcp_registry import auto_register_mcp, get_registry_status

        auto_register_mcp()
        registry_status = get_registry_status()
    except Exception as exc:
        logger.warning(f"获取 MCP registry 状态失败: {exc}")
        registry_status = {
            "registered_services": 0,
            "isolated_worker_services": 0,
            "rejected_plugin_manifests": 0,
            "cached_manifests": 0,
            "service_names": [],
            "isolated_worker_names": [],
            "rejected_plugin_names": [],
        }
        reason_code = "MCP_REGISTRY_UNAVAILABLE"
        reason_text = f"MCP registry status unavailable: {exc}"

    runtime_snapshot = _build_mcp_runtime_snapshot(registry_status=registry_status)
    task_snapshot = _build_mcp_task_snapshot(snapshot=runtime_snapshot)
    services_payload = get_mcp_services()
    services = services_payload.get("services") if isinstance(services_payload, dict) else []
    if not isinstance(services, list):
        services = []

    total_services = len(services)
    available_services = sum(1 for item in services if bool(item.get("available")))
    builtin_services = sum(1 for item in services if str(item.get("source") or "").strip().lower() == "builtin")
    mcporter_services = sum(1 for item in services if str(item.get("source") or "").strip().lower() == "mcporter")
    isolated_worker_services = int(registry_status.get("isolated_worker_services") or 0)
    rejected_plugin_manifests = int(registry_status.get("rejected_plugin_manifests") or 0)

    if total_services <= 0 and int(registry_status.get("registered_services") or 0) <= 0:
        severity = "unknown"
        reason_code = reason_code or "MCP_FABRIC_EMPTY"
        reason_text = reason_text or "No builtin or mcporter services discovered."
    elif available_services <= 0:
        severity = "critical"
        reason_code = reason_code or "MCP_FABRIC_UNAVAILABLE"
        reason_text = reason_text or "Services exist but none are currently available."
    elif available_services < total_services or rejected_plugin_manifests > 0:
        severity = "warning"
        if rejected_plugin_manifests > 0 and not reason_code:
            reason_code = "MCP_PLUGIN_REJECTED"
            reason_text = "One or more plugin manifests were rejected by policy."
    else:
        severity = "ok"

    source_reports: List[str] = []
    if MCPORTER_CONFIG_PATH.exists():
        source_reports.append(_ops_unix_path(MCPORTER_CONFIG_PATH))

    response_data = {
        "summary": {
            "total_services": total_services,
            "available_services": available_services,
            "builtin_services": builtin_services,
            "mcporter_services": mcporter_services,
            "isolated_worker_services": isolated_worker_services,
            "rejected_plugin_manifests": rejected_plugin_manifests,
        },
        "runtime_snapshot": runtime_snapshot,
        "registry": registry_status,
        "tasks": task_snapshot,
        "services": services,
    }

    return _ops_build_response(
        data=response_data,
        severity=severity,
        source_reports=source_reports,
        source_endpoints=["/mcp/status", "/mcp/services", "/mcp/tasks"],
        reason_code=reason_code,
        reason_text=reason_text,
    )


def _ops_safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _ops_read_event_rows(events_file: Path, *, limit: int) -> List[Dict[str, Any]]:
    if not events_file.exists() or limit <= 0:
        return []

    lines = events_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    rows: List[Dict[str, Any]] = []
    for line in lines[-limit:]:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _ops_compact_event_payload(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    compact: Dict[str, Any] = {}
    for key, value in payload.items():
        if len(compact) >= 8:
            break
        if isinstance(value, (str, int, float, bool)) or value is None:
            compact[str(key)] = value
            continue
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                if len(compact) >= 8:
                    break
                if isinstance(nested_value, (str, int, float, bool)) or nested_value is None:
                    compact[f"{key}.{nested_key}"] = nested_value
    return compact


def _ops_extract_execution_bridge_governance(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    governance: Dict[str, Any] = {}
    for candidate in (
        payload.get("execution_bridge_governance"),
        payload.get("bridge_receipt", {}).get("governance")
        if isinstance(payload.get("bridge_receipt"), dict)
        else {},
        payload.get("execution_bridge_receipt", {}).get("governance")
        if isinstance(payload.get("execution_bridge_receipt"), dict)
        else {},
    ):
        if isinstance(candidate, dict) and candidate:
            governance = dict(candidate)
            break

    if not governance:
        raw_reason = str(payload.get("error") or payload.get("reason") or "").strip()
        if raw_reason.startswith("execution_bridge_"):
            reason_code = "EXECUTION_BRIDGE_REJECTED"
            category = "execution_bridge"
            if raw_reason.startswith("execution_bridge_role_path_violation"):
                reason_code = "ROLE_PATH_VIOLATION"
                category = "path_policy"
            elif raw_reason.startswith("execution_bridge_semantic_toolchain_violation"):
                reason_code = "SEMANTIC_TOOLCHAIN_VIOLATION"
                category = "semantic_toolchain"
            elif raw_reason == "execution_bridge_ops_ticket_required":
                reason_code = "OPS_CHANGE_TICKET_REQUIRED"
                category = "change_control"
            elif raw_reason == "execution_bridge_missing_patch_intent":
                reason_code = "MISSING_PATCH_INTENT"
                category = "patch_intent"
            governance = {
                "status": "critical",
                "severity": "critical",
                "category": category,
                "reason_code": reason_code,
                "reason": raw_reason,
                "executor": str(payload.get("role") or ""),
                "policy_source": str(payload.get("role_executor_policy_source") or ""),
                "violation_count": 0,
                "violations": [],
            }

    if not governance:
        return {}

    violations: List[str] = []
    raw_violations = governance.get("violations")
    if isinstance(raw_violations, list):
        violations = [str(item) for item in raw_violations if str(item).strip()]
    violation_count = _ops_safe_int(governance.get("violation_count"), default=len(violations))
    status = _ops_status_to_severity(str(governance.get("severity") or governance.get("status") or "unknown"))

    return {
        "status": status,
        "severity": status,
        "category": str(governance.get("category") or ""),
        "reason_code": str(governance.get("reason_code") or ""),
        "reason": str(governance.get("reason") or ""),
        "executor": str(governance.get("executor") or ""),
        "policy_source": str(
            governance.get("policy_source") or payload.get("role_executor_policy_source") or ""
        ),
        "strict_role_paths": bool(governance.get("strict_role_paths", False)),
        "strict_semantic_guard": bool(governance.get("strict_semantic_guard", False)),
        "violation_count": max(0, int(violation_count)),
        "violations": violations,
    }


def _ops_build_execution_bridge_governance_summary(
    *,
    events_file: Path,
    limit: int = 5000,
    issues_limit: int = 20,
) -> Dict[str, Any]:
    rows = _ops_read_event_rows(events_file, limit=max(200, int(limit)))
    completed_total = 0
    completed_rejected = 0
    completed_governance_rows: List[Dict[str, Any]] = []
    rejected_governance_rows: List[Dict[str, Any]] = []

    for row in rows:
        event_type = str(row.get("event_type") or "").strip()
        payload = row.get("payload")
        payload_dict = payload if isinstance(payload, dict) else {}

        if event_type == "SubTaskExecutionCompleted":
            completed_total += 1
            if payload_dict.get("success") is False:
                completed_rejected += 1
            governance = _ops_extract_execution_bridge_governance(payload_dict)
            if governance:
                completed_governance_rows.append(
                    {
                        "timestamp": str(row.get("timestamp") or ""),
                        "event_type": event_type,
                        "subtask_id": str(payload_dict.get("subtask_id") or ""),
                        "task_id": str(payload_dict.get("task_id") or ""),
                        "role": str(payload_dict.get("role") or ""),
                        "success": bool(payload_dict.get("success")),
                        "governance": governance,
                    }
                )
            continue

        if event_type == "SubTaskRejected":
            governance = _ops_extract_execution_bridge_governance(payload_dict)
            if governance:
                rejected_governance_rows.append(
                    {
                        "timestamp": str(row.get("timestamp") or ""),
                        "event_type": event_type,
                        "subtask_id": str(payload_dict.get("subtask_id") or ""),
                        "task_id": str(payload_dict.get("task_id") or ""),
                        "role": str(payload_dict.get("role") or ""),
                        "error": str(payload_dict.get("error") or ""),
                        "governance": governance,
                    }
                )

    reference_rows = completed_governance_rows if completed_governance_rows else rejected_governance_rows
    status_counts: Dict[str, int] = {"ok": 0, "warning": 0, "critical": 0, "unknown": 0}
    reason_code_counts: Dict[str, int] = {}
    category_counts: Dict[str, int] = {}
    executor_counts: Dict[str, int] = {}
    policy_source_counts: Dict[str, int] = {}
    governance_warning_count = 0
    governance_critical_count = 0
    latest_issue_at = ""

    for row in reference_rows:
        governance = row.get("governance")
        if not isinstance(governance, dict):
            continue
        status = _ops_status_to_severity(str(governance.get("status") or "unknown"))
        status_counts[status] = int(status_counts.get(status, 0)) + 1
        if status == "warning":
            governance_warning_count += 1
        elif status == "critical":
            governance_critical_count += 1
        if status in {"warning", "critical"}:
            ts = str(row.get("timestamp") or "")
            if (_ops_parse_iso_datetime(ts) or 0.0) >= (_ops_parse_iso_datetime(latest_issue_at) or 0.0):
                latest_issue_at = ts

        reason_code = str(governance.get("reason_code") or "")
        if reason_code:
            reason_code_counts[reason_code] = int(reason_code_counts.get(reason_code, 0)) + 1
        category = str(governance.get("category") or "")
        if category:
            category_counts[category] = int(category_counts.get(category, 0)) + 1
        executor = str(governance.get("executor") or "")
        if executor:
            executor_counts[executor] = int(executor_counts.get(executor, 0)) + 1
        policy_source = str(governance.get("policy_source") or "")
        if policy_source:
            policy_source_counts[policy_source] = int(policy_source_counts.get(policy_source, 0)) + 1

    if governance_critical_count > 0:
        status = "critical"
    elif governance_warning_count > 0:
        status = "warning"
    elif completed_total > 0 or bool(reference_rows):
        status = "ok"
    else:
        status = "unknown"

    rejection_ratio = (completed_rejected / float(completed_total)) if completed_total > 0 else None
    governed_rows_count = len(reference_rows)
    governed_warning_ratio = (
        (governance_warning_count + governance_critical_count) / float(governed_rows_count)
        if governed_rows_count > 0
        else None
    )

    issue_rows = rejected_governance_rows if rejected_governance_rows else [
        item
        for item in completed_governance_rows
        if _ops_status_to_severity(str(item.get("governance", {}).get("status") or "unknown")) in {"warning", "critical"}
    ]
    issue_rows.sort(key=lambda row: _ops_parse_iso_datetime(row.get("timestamp")) or 0.0, reverse=True)
    recent_issues: List[Dict[str, Any]] = []
    for row in issue_rows[: max(1, int(issues_limit))]:
        governance = row.get("governance")
        if not isinstance(governance, dict):
            continue
        recent_issues.append(
            {
                "timestamp": str(row.get("timestamp") or ""),
                "event_type": str(row.get("event_type") or ""),
                "task_id": str(row.get("task_id") or ""),
                "subtask_id": str(row.get("subtask_id") or ""),
                "role": str(row.get("role") or ""),
                "severity": _ops_status_to_severity(str(governance.get("status") or "unknown")),
                "reason_code": str(governance.get("reason_code") or ""),
                "reason": str(governance.get("reason") or ""),
                "category": str(governance.get("category") or ""),
                "executor": str(governance.get("executor") or ""),
                "policy_source": str(governance.get("policy_source") or ""),
                "violation_count": _ops_safe_int(governance.get("violation_count"), default=0),
                "violations": list(governance.get("violations") or []),
                "error": str(row.get("error") or ""),
            }
        )

    reason_codes_sorted = [
        key
        for key, _ in sorted(reason_code_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    if status == "ok" and not reason_codes_sorted:
        reason_codes_sorted = ["EXECUTION_BRIDGE_GOVERNANCE_OK"]
    elif status == "unknown" and not reason_codes_sorted:
        reason_codes_sorted = ["EXECUTION_BRIDGE_GOVERNANCE_UNKNOWN"]

    return {
        "status": status,
        "reason_codes": reason_codes_sorted,
        "reason_code_counts": reason_code_counts,
        "category_counts": category_counts,
        "executor_counts": executor_counts,
        "policy_source_counts": policy_source_counts,
        "subtask_total": completed_total,
        "subtask_rejected": completed_rejected,
        "rejection_ratio": rejection_ratio,
        "governed_rows_count": governed_rows_count,
        "governed_warning_count": governance_warning_count,
        "governed_critical_count": governance_critical_count,
        "governed_warning_ratio": governed_warning_ratio,
        "latest_issue_at": latest_issue_at,
        "recent_issues": recent_issues,
    }


def _ops_build_workflow_events_payload(
    *,
    events_limit: int = 5000,
    context_days: int = 7,
    recent_critical_limit: int = 50,
) -> Dict[str, Any]:
    try:
        from scripts.export_slo_snapshot import build_snapshot

        repo_root = Path(__file__).resolve().parent.parent
        snapshot = build_snapshot(repo_root=repo_root, events_limit=max(1, int(events_limit)))
    except Exception as exc:
        logger.error(f"构建 workflow/events 聚合失败: {exc}")
        raise

    metrics = snapshot.get("metrics") if isinstance(snapshot.get("metrics"), dict) else {}
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    sources = snapshot.get("sources") if isinstance(snapshot.get("sources"), dict) else {}
    severity = _ops_status_to_severity(str(summary.get("overall_status") or "unknown"))

    events_file_raw = str(sources.get("events_file") or "").strip()
    events_file = Path(events_file_raw) if events_file_raw else Path("")
    event_rows = _ops_read_event_rows(events_file, limit=max(100, int(events_limit)))

    critical_event_types = {
        "SubAgentRuntimeFailOpen",
        "SubAgentRuntimeFailOpenBlocked",
        "SubAgentRuntimeAutoDegraded",
        "LeaseLost",
        "IncidentOpened",
    }
    event_counters = {name: 0 for name in sorted(critical_event_types)}
    recent_critical_events: List[Dict[str, Any]] = []
    for row in event_rows:
        event_type = str(row.get("event_type") or "").strip()
        if event_type not in critical_event_types:
            continue
        event_counters[event_type] = int(event_counters.get(event_type, 0)) + 1
        recent_critical_events.append({
            "timestamp": str(row.get("timestamp") or ""),
            "event_type": event_type,
            "payload_excerpt": _ops_compact_event_payload(row.get("payload")),
        })
    recent_critical_events = recent_critical_events[-max(1, int(recent_critical_limit)) :]

    queue_depth = metrics.get("queue_depth") if isinstance(metrics.get("queue_depth"), dict) else {}
    lock_status = metrics.get("lock_status") if isinstance(metrics.get("lock_status"), dict) else {}
    runtime_lease = metrics.get("runtime_lease") if isinstance(metrics.get("runtime_lease"), dict) else {}

    queue_status = _ops_status_to_severity(str(queue_depth.get("status") or "unknown"))
    if queue_status == "critical":
        severity = "critical"
    elif queue_status == "warning" and severity != "critical":
        severity = "warning"
    elif sum(event_counters.values()) > 0 and severity == "ok":
        severity = "warning"

    context_stats = message_manager.get_context_statistics(max(1, int(context_days)))
    tool_status = _tool_status_store.get("current", {"message": "", "visible": False})

    reason_code: Optional[str] = None
    reason_text: Optional[str] = None
    if severity == "critical":
        reason_code = "WORKFLOW_RISK_CRITICAL"
        reason_text = "Critical workflow pressure or high-risk runtime events detected."
    elif severity == "unknown":
        reason_code = "WORKFLOW_SIGNAL_UNKNOWN"
        reason_text = "Workflow signal coverage is insufficient; verify events/workflow data sources."

    source_reports: List[str] = []
    for key in ("events_file", "workflow_db", "global_mutex_state"):
        value = sources.get(key)
        if isinstance(value, str) and value.strip():
            source_reports.append(value.replace("\\", "/"))

    response_data = {
        "summary": {
            "overall_status": str(summary.get("overall_status") or "unknown"),
            "events_scanned": _ops_safe_int(sources.get("events_scanned"), default=0),
            "outbox_pending": queue_depth.get("value"),
            "oldest_pending_age_seconds": queue_depth.get("oldest_pending_age_seconds"),
            "critical_events_total": sum(event_counters.values()),
        },
        "queue_depth": queue_depth,
        "lock_status": lock_status,
        "runtime_lease": runtime_lease,
        "event_counters": event_counters,
        "recent_critical_events": recent_critical_events,
        "log_context_statistics": context_stats,
        "tool_status": tool_status,
    }

    return _ops_build_response(
        data=response_data,
        severity=severity,
        source_reports=sorted(set(source_reports)),
        source_endpoints=["/logs/context/statistics", "/tool_status"],
        reason_code=reason_code,
        reason_text=reason_text,
    )


async def _ops_build_memory_graph_payload(*, sample_limit: int = 200) -> Dict[str, Any]:
    stats_response = await get_memory_stats()
    memory_stats = stats_response.get("memory_stats") if isinstance(stats_response, dict) else {}
    if not isinstance(memory_stats, dict):
        memory_stats = {}

    quintuples_response = await get_quintuples()
    quintuples = quintuples_response.get("quintuples") if isinstance(quintuples_response, dict) else []
    if not isinstance(quintuples, list):
        quintuples = []

    task_manager = memory_stats.get("task_manager") if isinstance(memory_stats.get("task_manager"), dict) else {}
    pending_tasks = _ops_safe_int(task_manager.get("pending_tasks"), default=0)
    running_tasks = _ops_safe_int(task_manager.get("running_tasks"), default=0)
    failed_tasks = _ops_safe_int(task_manager.get("failed_tasks"), default=0)

    from collections import Counter

    relation_counter: Counter[str] = Counter()
    entity_counter: Counter[str] = Counter()
    graph_sample: List[Dict[str, str]] = []
    for row in quintuples[: max(20, min(1000, int(sample_limit)))]:
        if not isinstance(row, dict):
            continue
        subject = str(row.get("subject") or "")
        subject_type = str(row.get("subject_type") or "")
        predicate = str(row.get("predicate") or "")
        obj = str(row.get("object") or "")
        object_type = str(row.get("object_type") or "")
        if subject:
            entity_counter[subject] += 1
        if obj:
            entity_counter[obj] += 1
        if predicate:
            relation_counter[predicate] += 1
        graph_sample.append({
            "subject": subject,
            "subject_type": subject_type,
            "predicate": predicate,
            "object": obj,
            "object_type": object_type,
        })

    total_quintuples = _ops_safe_int(
        memory_stats.get("total_quintuples"),
        default=_ops_safe_int(quintuples_response.get("count"), default=len(quintuples)),
    )
    active_tasks = _ops_safe_int(memory_stats.get("active_tasks"), default=0)
    enabled = bool(memory_stats.get("enabled"))
    error_text = str(memory_stats.get("error") or "").strip()

    if error_text:
        severity = "critical"
        reason_code = "MEMORY_BACKEND_ERROR"
        reason_text = error_text
    elif not enabled:
        severity = "unknown"
        reason_code = "MEMORY_DISABLED"
        reason_text = str(memory_stats.get("message") or "Memory subsystem is disabled.")
    elif failed_tasks > 0:
        severity = "warning"
        reason_code = "MEMORY_TASK_FAILURE"
        reason_text = "Memory extraction task failures detected."
    elif total_quintuples <= 0:
        severity = "unknown"
        reason_code = "MEMORY_EMPTY_GRAPH"
        reason_text = "Memory graph currently has no extracted quintuples."
    else:
        severity = "ok"
        reason_code = None
        reason_text = None

    response_data = {
        "summary": {
            "enabled": enabled,
            "total_quintuples": total_quintuples,
            "active_tasks": active_tasks,
            "pending_tasks": pending_tasks,
            "running_tasks": running_tasks,
            "failed_tasks": failed_tasks,
            "graph_sample_size": len(graph_sample),
        },
        "task_manager": task_manager,
        "relation_hotspots": [
            {"relation": relation, "count": count} for relation, count in relation_counter.most_common(12)
        ],
        "entity_hotspots": [
            {"entity": entity, "count": count} for entity, count in entity_counter.most_common(12)
        ],
        "graph_sample": graph_sample,
    }

    return _ops_build_response(
        data=response_data,
        severity=severity,
        source_reports=[],
        source_endpoints=["/memory/stats", "/memory/quintuples"],
        reason_code=reason_code,
        reason_text=reason_text,
    )


def _ops_build_evidence_index_payload(*, max_reports: int = 100) -> Dict[str, Any]:
    repo_root = _ops_repo_root()
    reports_dir = repo_root / "scratch" / "reports"
    required_reports = _ops_collect_required_reports(repo_root)

    hard_missing = sum(1 for item in required_reports if item["gate_level"] == "hard" and item["status"] == "missing")
    hard_failed = sum(1 for item in required_reports if item["gate_level"] == "hard" and item["status"] == "failed")
    soft_missing = sum(1 for item in required_reports if item["gate_level"] == "soft" and item["status"] == "missing")
    soft_failed = sum(1 for item in required_reports if item["gate_level"] == "soft" and item["status"] == "failed")
    required_present = sum(1 for item in required_reports if bool(item["exists"]))
    required_passed = sum(1 for item in required_reports if item["status"] == "passed")
    required_unknown = sum(1 for item in required_reports if item["status"] == "unknown")

    reason_code: Optional[str] = None
    reason_text: Optional[str] = None
    if hard_missing > 0:
        severity = "critical"
        reason_code = "EVIDENCE_HARD_REPORT_MISSING"
        reason_text = "One or more hard-gate reports are missing."
    elif hard_failed > 0:
        severity = "critical"
        reason_code = "EVIDENCE_HARD_REPORT_FAILED"
        reason_text = "One or more hard-gate reports are in failed state."
    elif soft_missing > 0 or soft_failed > 0 or required_unknown > 0:
        severity = "warning"
        reason_code = "EVIDENCE_SOFT_GATE_PENDING"
        reason_text = "Soft-gate evidence is pending or not passed yet."
    elif required_passed > 0:
        severity = "ok"
    else:
        severity = "unknown"
        reason_code = "EVIDENCE_REPORTS_UNAVAILABLE"
        reason_text = "No required evidence report has been discovered."

    recent_reports: List[Dict[str, Any]] = []
    if reports_dir.exists():
        all_reports = sorted(
            reports_dir.glob("*.json"),
            key=lambda path: path.stat().st_mtime if path.exists() else 0,
            reverse=True,
        )
        from datetime import datetime, timezone

        for path in all_reports[: max(1, int(max_reports))]:
            try:
                stat = path.stat()
            except OSError:
                continue
            recent_reports.append(
                {
                    "name": path.name,
                    "path": _ops_unix_path(path),
                    "size_bytes": int(stat.st_size),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                }
            )

    source_reports = sorted(
        {
            item["path"]
            for item in required_reports
            if bool(item["exists"]) and isinstance(item.get("path"), str) and item["path"]
        }
    )

    response_data = {
        "summary": {
            "required_total": len(required_reports),
            "required_present": required_present,
            "required_passed": required_passed,
            "required_missing": len(required_reports) - required_present,
            "required_failed": sum(1 for item in required_reports if item["status"] == "failed"),
            "hard_missing": hard_missing,
            "hard_failed": hard_failed,
            "soft_missing": soft_missing,
            "soft_failed": soft_failed,
        },
        "required_reports": required_reports,
        "recent_reports": recent_reports,
    }

    return _ops_build_response(
        data=response_data,
        severity=severity,
        source_reports=source_reports,
        source_endpoints=[],
        reason_code=reason_code,
        reason_text=reason_text,
    )


def _ops_build_incidents_latest_payload(*, limit: int = 50) -> Dict[str, Any]:
    repo_root = _ops_repo_root()
    events_file = repo_root / "logs" / "autonomous" / "events.jsonl"
    event_rows = _ops_read_event_rows(events_file, limit=max(200, int(limit) * 10))
    route_quality_trend = _ops_build_route_quality_trend(events_file, window_size=20, max_windows=6)
    execution_bridge_governance = _ops_build_execution_bridge_governance_summary(
        events_file=events_file,
        limit=max(200, int(limit) * 10),
        issues_limit=max(10, int(limit)),
    )
    prompt_safety_summary: Dict[str, Any] = {}
    try:
        from scripts.export_slo_snapshot import build_snapshot

        snapshot = build_snapshot(repo_root=repo_root, events_limit=max(200, int(limit) * 10))
        snapshot_metrics = snapshot.get("metrics") if isinstance(snapshot.get("metrics"), dict) else {}
        outer_readonly_hit = (
            snapshot_metrics.get("outer_readonly_hit_rate")
            if isinstance(snapshot_metrics.get("outer_readonly_hit_rate"), dict)
            else {}
        )
        readonly_write_exposure = (
            snapshot_metrics.get("readonly_write_tool_exposure_rate")
            if isinstance(snapshot_metrics.get("readonly_write_tool_exposure_rate"), dict)
            else {}
        )
        chat_route_distribution = (
            snapshot_metrics.get("chat_route_path_distribution")
            if isinstance(snapshot_metrics.get("chat_route_path_distribution"), dict)
            else {}
        )
        path_b_budget_escalation = (
            snapshot_metrics.get("path_b_budget_escalation_rate")
            if isinstance(snapshot_metrics.get("path_b_budget_escalation_rate"), dict)
            else {}
        )
        core_session_creation = (
            snapshot_metrics.get("core_session_creation_rate")
            if isinstance(snapshot_metrics.get("core_session_creation_rate"), dict)
            else {}
        )
        prompt_safety_summary = {
            "outer_readonly_hit_rate": outer_readonly_hit,
            "readonly_write_tool_exposure_rate": readonly_write_exposure,
            "chat_route_path_distribution": chat_route_distribution,
            "path_b_budget_escalation_rate": path_b_budget_escalation,
            "core_session_creation_rate": core_session_creation,
            "route_quality": _ops_build_route_quality_summary(snapshot_metrics, trend=route_quality_trend),
            "execution_bridge_governance": execution_bridge_governance,
        }
    except Exception as exc:
        logger.warning(f"构建 incidents prompt safety 摘要失败（降级为空）: {exc}")
    if "execution_bridge_governance" not in prompt_safety_summary:
        prompt_safety_summary["execution_bridge_governance"] = execution_bridge_governance

    incidents: List[Dict[str, Any]] = []
    event_counters: Dict[str, int] = {key: 0 for key in sorted(_OPS_INCIDENT_EVENT_SEVERITY.keys())}
    event_counters["ExecutionBridgeGovernanceIssue"] = 0

    for row in event_rows:
        event_type = str(row.get("event_type") or "").strip()
        severity = _OPS_INCIDENT_EVENT_SEVERITY.get(event_type)
        if not severity:
            continue
        event_counters[event_type] = int(event_counters.get(event_type, 0)) + 1
        incidents.append(
            {
                "source": "events",
                "severity": severity,
                "timestamp": str(row.get("timestamp") or ""),
                "event_type": event_type,
                "summary": f"{event_type} detected in runtime event stream",
                "payload_excerpt": _ops_compact_event_payload(row.get("payload")),
                "report_path": "",
                "gate_level": "n/a",
            }
        )

    required_reports = _ops_collect_required_reports(repo_root)
    for report in required_reports:
        status = str(report.get("status") or "")
        gate_level = str(report.get("gate_level") or "soft")
        if status not in {"missing", "failed"}:
            continue
        severity = "critical" if gate_level == "hard" else "warning"
        summary = (
            f"{report['label']} missing"
            if status == "missing"
            else f"{report['label']} failed checks: {', '.join(report.get('failed_checks') or ['unknown'])}"
        )
        incidents.append(
            {
                "source": "report",
                "severity": severity,
                "timestamp": str(report.get("generated_at") or report.get("modified_at") or ""),
                "event_type": "EvidenceGateIssue",
                "summary": summary,
                "payload_excerpt": {"status": status, "report_id": report["id"]},
                "report_path": str(report.get("path") or ""),
                "gate_level": gate_level,
            }
        )

    brainstem_summary = _ops_build_brainstem_control_plane_summary(repo_root)
    brainstem_status = str(brainstem_summary.get("status") or "")
    if brainstem_status in {"warning", "critical"}:
        reason_code = str(brainstem_summary.get("reason_code") or "")
        brainstem_event_type = "BrainstemControlPlaneIssue"
        if reason_code == "BRAINSTEM_HEARTBEAT_MISSING":
            brainstem_event_type = "BrainstemHeartbeatMissing"
        elif reason_code in {"BRAINSTEM_HEARTBEAT_STALE_WARNING", "BRAINSTEM_HEARTBEAT_STALE_CRITICAL"}:
            brainstem_event_type = "BrainstemHeartbeatStale"
        elif reason_code == "BRAINSTEM_HEALTH_UNHEALTHY":
            brainstem_event_type = "BrainstemDaemonUnhealthy"
        elif reason_code in {"BRAINSTEM_HEARTBEAT_TIMESTAMP_INVALID", "BRAINSTEM_HEARTBEAT_NO_SIGNAL"}:
            brainstem_event_type = "BrainstemHeartbeatInvalid"
        incidents.append(
            {
                "source": "report",
                "severity": brainstem_status,
                "timestamp": str(brainstem_summary.get("generated_at") or ""),
                "event_type": brainstem_event_type,
                "summary": str(brainstem_summary.get("reason_text") or "Brainstem control-plane issue detected."),
                "payload_excerpt": {
                    "reason_code": reason_code,
                    "healthy": brainstem_summary.get("healthy"),
                    "heartbeat_age_seconds": brainstem_summary.get("heartbeat_age_seconds"),
                    "stale_warning_seconds": brainstem_summary.get("stale_warning_seconds"),
                    "stale_critical_seconds": brainstem_summary.get("stale_critical_seconds"),
                    "unhealthy_services": list(brainstem_summary.get("unhealthy_services") or []),
                    "tick": brainstem_summary.get("tick"),
                },
                "report_path": str(brainstem_summary.get("heartbeat_file") or ""),
                "gate_level": "hard",
            }
        )

    watchdog_summary = _ops_build_watchdog_daemon_summary(repo_root)
    watchdog_status = str(watchdog_summary.get("status") or "")
    if watchdog_status in {"warning", "critical"}:
        reason_code = str(watchdog_summary.get("reason_code") or "")
        watchdog_event_type = "WatchdogDaemonIssue"
        if reason_code == "WATCHDOG_DAEMON_STATE_MISSING":
            watchdog_event_type = "WatchdogDaemonStateMissing"
        elif reason_code in {"WATCHDOG_DAEMON_STALE_WARNING", "WATCHDOG_DAEMON_STALE_CRITICAL"}:
            watchdog_event_type = "WatchdogDaemonStateStale"
        elif reason_code in {"WATCHDOG_DAEMON_THRESHOLD_WARNING", "WATCHDOG_DAEMON_THRESHOLD_CRITICAL"}:
            watchdog_event_type = "WatchdogDaemonThresholdExceeded"
        incidents.append(
            {
                "source": "report",
                "severity": watchdog_status,
                "timestamp": str(watchdog_summary.get("generated_at") or ""),
                "event_type": watchdog_event_type,
                "summary": str(watchdog_summary.get("reason_text") or "Watchdog daemon issue detected."),
                "payload_excerpt": {
                    "reason_code": reason_code,
                    "heartbeat_age_seconds": watchdog_summary.get("heartbeat_age_seconds"),
                    "stale_warning_seconds": watchdog_summary.get("stale_warning_seconds"),
                    "stale_critical_seconds": watchdog_summary.get("stale_critical_seconds"),
                    "tick": watchdog_summary.get("tick"),
                    "threshold_hit": watchdog_summary.get("threshold_hit"),
                    "action": watchdog_summary.get("action"),
                },
                "report_path": str(watchdog_summary.get("state_file") or ""),
                "gate_level": "hard",
            }
        )

    governance_issues = execution_bridge_governance.get("recent_issues")
    if isinstance(governance_issues, list):
        for issue in governance_issues:
            if not isinstance(issue, dict):
                continue
            issue_severity = _ops_status_to_severity(str(issue.get("severity") or "unknown"))
            if issue_severity not in {"warning", "critical"}:
                continue
            event_counters["ExecutionBridgeGovernanceIssue"] = int(event_counters.get("ExecutionBridgeGovernanceIssue", 0)) + 1
            reason_code = str(issue.get("reason_code") or "EXECUTION_BRIDGE_GOVERNANCE_ISSUE")
            incidents.append(
                {
                    "source": "events",
                    "severity": issue_severity,
                    "timestamp": str(issue.get("timestamp") or ""),
                    "event_type": "ExecutionBridgeGovernanceIssue",
                    "summary": str(
                        issue.get("reason")
                        or f"Execution bridge governance issue detected: {reason_code}"
                    ),
                    "payload_excerpt": {
                        "reason_code": reason_code,
                        "category": str(issue.get("category") or ""),
                        "executor": str(issue.get("executor") or ""),
                        "policy_source": str(issue.get("policy_source") or ""),
                        "violation_count": _ops_safe_int(issue.get("violation_count"), default=0),
                        "task_id": str(issue.get("task_id") or ""),
                        "subtask_id": str(issue.get("subtask_id") or ""),
                    },
                    "report_path": _ops_unix_path(events_file) if events_file.exists() else "",
                    "gate_level": "runtime",
                }
            )

    incidents.sort(
        key=lambda row: _ops_parse_iso_datetime(row.get("timestamp")) or 0.0,
        reverse=True,
    )
    incidents = incidents[: max(1, int(limit))]

    critical_count = sum(1 for item in incidents if str(item.get("severity")) == "critical")
    warning_count = sum(1 for item in incidents if str(item.get("severity")) == "warning")
    latest_incident_at = ""
    if incidents:
        latest_incident_at = str(incidents[0].get("timestamp") or "")

    source_reports: List[str] = []
    if events_file.exists():
        source_reports.append(_ops_unix_path(events_file))
    for item in incidents:
        report_path = str(item.get("report_path") or "")
        if report_path:
            source_reports.append(report_path)

    reason_code: Optional[str] = None
    reason_text: Optional[str] = None
    if critical_count > 0:
        severity = "critical"
        reason_code = "INCIDENTS_CRITICAL_PRESENT"
        reason_text = "Critical incidents are present in runtime signals."
    elif warning_count > 0:
        severity = "warning"
        reason_code = "INCIDENTS_WARNING_PRESENT"
        reason_text = "Warning-level incidents are present in runtime signals."
    elif len(event_rows) > 0:
        severity = "ok"
    else:
        severity = "unknown"
        reason_code = "INCIDENTS_SIGNAL_EMPTY"
        reason_text = "No incident signal source was discovered."

    response_data = {
        "summary": {
            "total_incidents": len(incidents),
            "critical_incidents": critical_count,
            "warning_incidents": warning_count,
            "latest_incident_at": latest_incident_at,
            "runtime_prompt_safety": prompt_safety_summary,
            "execution_bridge_governance": execution_bridge_governance,
        },
        "event_counters": event_counters,
        "events_scanned": len(event_rows),
        "incidents": incidents,
    }

    return _ops_build_response(
        data=response_data,
        severity=severity,
        source_reports=sorted(set(source_reports)),
        source_endpoints=[],
        reason_code=reason_code,
        reason_text=reason_text,
    )


@app.get("/mcp/status")
async def get_mcp_status_offline():
    """返回 MCP 运行态快照，兼容前端 status/tasks 字段。"""
    return _build_mcp_runtime_snapshot()


@app.get("/mcp/tasks")
async def get_mcp_tasks_offline(status: Optional[str] = None):
    """返回 MCP 任务（服务）快照，避免离线模式 503。"""
    return _build_mcp_task_snapshot(status)


# ============ MCP 服务列表 & 导入 ============


def _load_mcporter_config() -> Dict[str, Any]:
    """读取 ~/.mcporter/config.json，不存在或格式错误时返回空 dict"""
    if not MCPORTER_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(MCPORTER_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_mcporter_config(mcporter_config: Dict[str, Any]) -> Path:
    MCPORTER_DIR.mkdir(parents=True, exist_ok=True)
    MCPORTER_CONFIG_PATH.write_text(
        json.dumps(mcporter_config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return MCPORTER_CONFIG_PATH


def _check_agent_available(manifest: Dict[str, Any]) -> bool:
    """检查内置 agent 模块是否可导入"""
    entry = manifest.get("entryPoint", {})
    module_path = entry.get("module", "")
    if not module_path:
        return False
    try:
        __import__(module_path)
        return True
    except Exception:
        return False


@app.get("/mcp/services")
def get_mcp_services():
    """列出所有 MCP 服务并检查可用性（同步端点，由 FastAPI 在线程池中执行）"""
    services: List[Dict[str, Any]] = []

    # 1. 内置 agent（扫描 mcpserver/**/agent-manifest.json）
    mcpserver_dir = Path(__file__).resolve().parent.parent / "mcpserver"
    for manifest_path in mcpserver_dir.glob("*/agent-manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if manifest.get("agentType") != "mcp":
            continue
        available = _check_agent_available(manifest)
        services.append({
            "name": manifest.get("name", manifest_path.parent.name),
            "display_name": manifest.get("displayName", manifest.get("name", "")),
            "description": manifest.get("description", ""),
            "source": "builtin",
            "available": available,
        })

    # 2. mcporter 外部配置（~/.mcporter/config.json 中的 mcpServers）
    mcporter_config = _load_mcporter_config()
    for name, cfg in mcporter_config.get("mcpServers", {}).items():
        cmd = cfg.get("command", "")
        available = shutil.which(cmd) is not None if cmd else False
        services.append({
            "name": name,
            "display_name": name,
            "description": f"{cmd} {' '.join(cfg.get('args', []))}" if cmd else "",
            "source": "mcporter",
            "available": available,
        })

    return {"status": "success", "services": services}


@app.get("/v1/ops/runtime/posture")
async def get_ops_runtime_posture(events_limit: int = 5000):
    """聚合运行态势：rollout/fail-open/lease/queue/lock/disk/error/latency。"""
    try:
        return _ops_build_runtime_posture_payload(events_limit=events_limit)
    except Exception as exc:
        logger.error(f"获取 /v1/ops/runtime/posture 失败: {exc}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取 runtime posture 失败: {str(exc)}")


@app.get("/v1/ops/mcp/fabric")
async def get_ops_mcp_fabric():
    """聚合 MCP 织网状态：registry、services、task snapshot。"""
    try:
        return _ops_build_mcp_fabric_payload()
    except Exception as exc:
        logger.error(f"获取 /v1/ops/mcp/fabric 失败: {exc}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取 mcp fabric 失败: {str(exc)}")


@app.get("/v1/ops/memory/graph")
async def get_ops_memory_graph(sample_limit: int = 200):
    """聚合记忆图谱运行态：统计、热点关系与样本图数据。"""
    try:
        return await _ops_build_memory_graph_payload(sample_limit=sample_limit)
    except Exception as exc:
        logger.error(f"获取 /v1/ops/memory/graph 失败: {exc}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取 memory graph 失败: {str(exc)}")


@app.get("/v1/ops/workflow/events")
async def get_ops_workflow_events(events_limit: int = 5000, context_days: int = 7, recent_critical_limit: int = 50):
    """聚合工作流与事件态势：队列、锁、关键事件与日志上下文。"""
    try:
        return _ops_build_workflow_events_payload(
            events_limit=events_limit,
            context_days=context_days,
            recent_critical_limit=recent_critical_limit,
        )
    except Exception as exc:
        logger.error(f"获取 /v1/ops/workflow/events 失败: {exc}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取 workflow events 失败: {str(exc)}")


@app.get("/v1/ops/incidents/latest")
async def get_ops_incidents_latest(limit: int = 50):
    """聚合近期事故态势：关键事件 + 关键报告门禁异常。"""
    try:
        return _ops_build_incidents_latest_payload(limit=limit)
    except Exception as exc:
        logger.error(f"获取 /v1/ops/incidents/latest 失败: {exc}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取 incidents latest 失败: {str(exc)}")


@app.get("/v1/ops/evidence/index")
async def get_ops_evidence_index(max_reports: int = 100):
    """聚合证据索引：M12 关键报告可见性与门禁状态。"""
    try:
        return _ops_build_evidence_index_payload(max_reports=max_reports)
    except Exception as exc:
        logger.error(f"获取 /v1/ops/evidence/index 失败: {exc}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取 evidence index 失败: {str(exc)}")


class McpImportRequest(BaseModel):
    name: str
    config: Dict[str, Any]


@app.post("/mcp/import")
async def import_mcp_config(request: McpImportRequest):
    """将 MCP JSON 配置写入 ~/.mcporter/config.json"""
    MCPORTER_DIR.mkdir(parents=True, exist_ok=True)
    mcporter_config = _load_mcporter_config()
    servers = mcporter_config.setdefault("mcpServers", {})
    servers[request.name] = request.config
    mcporter_config["mcpServers"] = servers
    MCPORTER_CONFIG_PATH.write_text(
        json.dumps(mcporter_config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"status": "success", "message": f"已添加 MCP 服务: {request.name}"}


class SkillImportRequest(BaseModel):
    name: str
    content: str


@app.post("/skills/import")
async def import_custom_skill(request: SkillImportRequest):
    """创建自定义技能 SKILL.md"""
    skill_content = f"""---
name: {request.name}
description: 用户自定义技能
version: 1.0.0
author: User
tags:
  - custom
enabled: true
---

{request.content}
"""
    skill_path = _write_skill_file(request.name, skill_content)
    return {"status": "success", "message": f"技能已创建: {skill_path}"}


@app.get("/memory/quintuples")
async def get_quintuples():
    """获取所有五元组 (用于知识图谱可视化)"""
    try:
        # 优先使用远程 NagaMemory 服务
        from summer_memory.memory_client import get_remote_memory_client

        remote = get_remote_memory_client()
        if remote is not None:
            result = await remote.get_quintuples(limit=500)
            quintuples_raw = result.get("quintuples") or result.get("results") or result.get("data") or []
            # 兼容 NagaMemory 返回格式：可能是 dict 列表或 tuple 列表
            quintuples = []
            for q in quintuples_raw:
                if isinstance(q, dict):
                    quintuples.append({
                        "subject": q.get("subject", ""),
                        "subject_type": q.get("subject_type", ""),
                        "predicate": q.get("predicate", q.get("relation", "")),
                        "object": q.get("object", ""),
                        "object_type": q.get("object_type", ""),
                    })
                elif isinstance(q, (list, tuple)) and len(q) >= 5:
                    quintuples.append({
                        "subject": q[0], "subject_type": q[1],
                        "predicate": q[2], "object": q[3], "object_type": q[4],
                    })
            return {"status": "success", "quintuples": quintuples, "count": len(quintuples)}

        # 回退到本地 summer_memory
        from summer_memory.quintuple_graph import get_all_quintuples

        quintuples = get_all_quintuples()  # returns set[tuple]
        return {
            "status": "success",
            "quintuples": [
                {"subject": q[0], "subject_type": q[1], "predicate": q[2], "object": q[3], "object_type": q[4]}
                for q in quintuples
            ],
            "count": len(quintuples),
        }
    except ImportError:
        return {"status": "success", "quintuples": [], "count": 0, "message": "记忆系统模块未找到"}
    except Exception as e:
        logger.error(f"获取五元组错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取五元组失败: {str(e)}")


@app.get("/memory/quintuples/search")
async def search_quintuples(keywords: str = ""):
    """按关键词搜索五元组"""
    try:
        keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
        if not keyword_list:
            raise HTTPException(status_code=400, detail="请提供搜索关键词")

        # 优先使用远程 NagaMemory 服务
        from summer_memory.memory_client import get_remote_memory_client

        remote = get_remote_memory_client()
        if remote is not None:
            result = await remote.query_by_keywords(keyword_list)
            quintuples_raw = result.get("quintuples") or result.get("results") or result.get("data") or []
            quintuples = []
            for q in quintuples_raw:
                if isinstance(q, dict):
                    quintuples.append({
                        "subject": q.get("subject", ""),
                        "subject_type": q.get("subject_type", ""),
                        "predicate": q.get("predicate", q.get("relation", "")),
                        "object": q.get("object", ""),
                        "object_type": q.get("object_type", ""),
                    })
                elif isinstance(q, (list, tuple)) and len(q) >= 5:
                    quintuples.append({
                        "subject": q[0], "subject_type": q[1],
                        "predicate": q[2], "object": q[3], "object_type": q[4],
                    })
            return {"status": "success", "quintuples": quintuples, "count": len(quintuples)}

        # 回退到本地 summer_memory
        from summer_memory.quintuple_graph import query_graph_by_keywords

        results = query_graph_by_keywords(keyword_list)
        return {
            "status": "success",
            "quintuples": [
                {"subject": q[0], "subject_type": q[1], "predicate": q[2], "object": q[3], "object_type": q[4]}
                for q in results
            ],
            "count": len(results),
        }
    except ImportError:
        return {"status": "success", "quintuples": [], "count": 0, "message": "记忆系统模块未找到"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"搜索五元组错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"搜索五元组失败: {str(e)}")


@app.get("/sessions")
async def get_sessions():
    """获取所有会话信息 - 委托给message_manager"""
    try:
        return message_manager.get_all_sessions_api()
    except Exception as e:
        print(f"获取会话信息错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions/{session_id}")
async def get_session_detail(session_id: str):
    """获取指定会话的详细信息 - 委托给message_manager"""
    try:
        return message_manager.get_session_detail_api(session_id)
    except Exception as e:
        if "会话不存在" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        print(f"获取会话详情错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/chat/route_bridge/{session_id}")
async def get_chat_route_bridge(session_id: str, limit: int = 20):
    """获取 outer/core 会话桥接状态与最近路由事件。"""
    try:
        return _build_chat_route_bridge_payload(session_id, limit=limit)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话桥接状态失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/chat/route_bridge/{session_id}")
async def get_chat_route_bridge_v1(session_id: str, limit: int = 20):
    return await get_chat_route_bridge(session_id=session_id, limit=limit)


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除指定会话 - 委托给message_manager"""
    try:
        _vlm_sessions.discard(session_id)
        return message_manager.delete_session_api(session_id)
    except Exception as e:
        if "会话不存在" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        print(f"删除会话错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/sessions")
async def clear_all_sessions():
    """清空所有会话 - 委托给message_manager"""
    try:
        _vlm_sessions.clear()
        return message_manager.clear_all_sessions_api()
    except Exception as e:
        print(f"清空会话错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/upload/document", response_model=FileUploadResponse)
async def upload_document(file: UploadFile = File(...), description: str = Form(None)):
    """上传文档接口"""
    try:
        # 确保上传目录存在
        upload_dir = Path("uploaded_documents")
        upload_dir.mkdir(exist_ok=True)

        # 使用原始文件名
        filename = file.filename
        file_path = upload_dir / filename

        # 保存文件
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 获取文件信息
        stat = file_path.stat()

        return FileUploadResponse(
            filename=filename,
            file_path=str(file_path.absolute()),
            file_size=stat.st_size,
            file_type=file_path.suffix,
            upload_time=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
        )
    except Exception as e:
        logger.error(f"文件上传失败: {e}")
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@app.post("/upload/parse")
async def upload_parse(file: UploadFile = File(...)):
    """上传并解析文档内容（支持 .docx / .xlsx / .txt）"""
    import tempfile
    filename = file.filename or "unknown"
    suffix = Path(filename).suffix.lower()

    if suffix not in (".docx", ".xlsx", ".txt", ".csv", ".md"):
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {suffix}，支持 .docx / .xlsx / .txt / .csv / .md")

    # 写入临时文件
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        if suffix == ".docx":
            import importlib.util
            _docx_spec = importlib.util.spec_from_file_location(
                "docx_extract", Path(__file__).parent / "skills_templates" / "office-docs" / "tools" / "docx_extract.py"
            )
            _docx_mod = importlib.util.module_from_spec(_docx_spec)
            _docx_spec.loader.exec_module(_docx_mod)
            lines = _docx_mod.extract_docx_text(tmp_path)
            content = "\n".join(lines)
        elif suffix == ".xlsx":
            import importlib.util
            import zipfile as _zf
            _xlsx_spec = importlib.util.spec_from_file_location(
                "xlsx_extract", Path(__file__).parent / "skills_templates" / "office-docs" / "tools" / "xlsx_extract.py"
            )
            _xlsx_mod = importlib.util.module_from_spec(_xlsx_spec)
            _xlsx_spec.loader.exec_module(_xlsx_mod)
            with _zf.ZipFile(tmp_path, "r") as archive:
                shared_strings = _xlsx_mod._load_shared_strings(archive)
                sheets = _xlsx_mod._load_sheet_targets(archive)
                parts = []
                for name, path in sheets:
                    rows = _xlsx_mod._parse_sheet(archive, path, shared_strings, max_rows=500)
                    parts.append(f"## Sheet: {name}\n{_xlsx_mod._format_sheet_csv(rows, ',')}")
                content = "\n".join(parts)
        else:
            # txt / csv / md 直接读取
            content = tmp_path.read_text(encoding="utf-8", errors="replace")

        # 截断过长内容
        max_chars = 50000
        truncated = len(content) > max_chars
        if truncated:
            content = content[:max_chars]

        return {
            "status": "success",
            "filename": filename,
            "content": content,
            "truncated": truncated,
            "char_count": len(content),
        }
    except Exception as e:
        logger.error(f"文档解析失败: {e}")
        raise HTTPException(status_code=500, detail=f"解析失败: {str(e)}")
    finally:
        tmp_path.unlink(missing_ok=True)


@app.get("/update/latest")
async def proxy_update_check(platform: str = "windows"):
    """Update check is disabled in local-only mode."""
    return {"has_update": False, "local_mode": True}


app.mount("/llm", llm_app)


# 新增：日志解析相关API接口
@app.get("/logs/context/statistics")
async def get_log_context_statistics(days: int = 7):
    """获取日志上下文统计信息"""
    try:
        statistics = message_manager.get_context_statistics(days)
        return {"status": "success", "statistics": statistics}
    except Exception as e:
        print(f"获取日志上下文统计错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")


@app.get("/logs/context/load")
async def load_log_context(days: int = 3, max_messages: int = None):
    """加载日志上下文"""
    try:
        messages = message_manager.load_recent_context(days=days, max_messages=max_messages)
        return {"status": "success", "messages": messages, "count": len(messages), "days": days}
    except Exception as e:
        print(f"加载日志上下文错误: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"加载上下文失败: {str(e)}")


# Web前端工具状态轮询存储
_tool_status_store: Dict[str, Dict] = {"current": {"message": "", "visible": False}}

# Web前端 AgentServer 回复存储（轮询获取）
_clawdbot_replies: list = []

@app.get("/tool_status")
async def get_tool_status():
    """获取当前工具调用状态（供Web前端轮询）"""
    return _tool_status_store.get("current", {"message": "", "visible": False})


@app.get("/clawdbot/replies")
async def get_clawdbot_replies():
    """获取并清空 AgentServer 待显示回复（供Web前端轮询）"""
    replies = list(_clawdbot_replies)
    _clawdbot_replies.clear()
    return {"replies": replies}


@app.post("/tool_notification")
async def tool_notification(payload: Dict[str, Any]):
    """接收工具调用状态通知，只显示工具调用状态，不显示结果"""
    try:
        session_id = payload.get("session_id")
        tool_calls = payload.get("tool_calls", [])
        message = payload.get("message", "")
        stage = payload.get("stage", "")
        auto_hide_ms_raw = payload.get("auto_hide_ms", 0)

        try:
            auto_hide_ms = int(auto_hide_ms_raw)
        except (TypeError, ValueError):
            auto_hide_ms = 0

        if not session_id:
            raise HTTPException(400, "缺少session_id")

        # 记录工具调用状态（不处理结果，结果由tool_result_callback处理）
        for tool_call in tool_calls:
            tool_name = tool_call.get("tool_name", "未知工具")
            service_name = tool_call.get("service_name", "未知服务")
            status = tool_call.get("status", "starting")
            logger.info(f"工具调用状态: {tool_name} ({service_name}) - {status}")

        display_message = message
        if not display_message:
            if stage == "detecting":
                display_message = "正在检测工具调用"
            elif stage == "executing":
                display_message = f"检测到{len(tool_calls)}个工具调用，执行中"
            elif stage == "none":
                display_message = "未检测到工具调用"

        if stage == "hide":
            _hide_tool_status_in_ui()
        elif display_message:
            _emit_tool_status_to_ui(display_message, auto_hide_ms)

        return {
            "success": True,
            "message": "工具调用状态通知已接收",
            "tool_calls": tool_calls,
            "display_message": display_message,
            "stage": stage,
            "auto_hide_ms": auto_hide_ms,
        }

    except Exception as e:
        logger.error(f"工具调用通知处理失败: {e}")
        raise HTTPException(500, f"处理失败: {str(e)}")


@app.post("/tool_result_callback")
async def tool_result_callback(payload: Dict[str, Any]):
    """接收MCP工具执行结果回调，让主AI基于原始对话和工具结果重新生成回复"""
    try:
        session_id = payload.get("session_id")
        task_id = payload.get("task_id")
        result = payload.get("result", {})
        success = payload.get("success", False)

        if not session_id:
            raise HTTPException(400, "缺少session_id")

        _emit_tool_status_to_ui("生成工具回调", 0)

        logger.info(f"[工具回调] 开始处理工具回调，会话: {session_id}, 任务ID: {task_id}")
        logger.info(f"[工具回调] 回调内容: {result}")

        # 获取工具执行结果
        tool_result = result.get("result", "执行成功") if success else result.get("error", "未知错误")
        logger.info(f"[工具回调] 工具执行结果: {tool_result}")

        # 获取原始对话的最后一条用户消息（触发工具调用的消息）
        session_messages = message_manager.get_messages(session_id)
        original_user_message = ""
        for msg in reversed(session_messages):
            if msg.get("role") == "user":
                original_user_message = msg.get("content", "")
                break

        # 构建包含工具结果的用户消息
        enhanced_message = f"{original_user_message}\n\n[工具执行结果]: {tool_result}"
        logger.info(f"[工具回调] 构建增强消息: {enhanced_message[:200]}...")

        # 构建对话风格提示词和消息
        system_prompt = build_system_prompt(include_skills=True)
        messages = message_manager.build_conversation_messages(
            session_id=session_id, system_prompt=system_prompt, current_message=enhanced_message
        )

        logger.info("[工具回调] 开始生成工具后回复...")

        # 使用LLM服务基于原始对话和工具结果重新生成回复
        try:
            llm_service = get_llm_service()
            response_text = await llm_service.chat_with_context(messages, temperature=0.7)
            logger.info(f"[工具回调] 工具后回复生成成功，内容: {response_text[:200]}...")
        except Exception as e:
            logger.error(f"[工具回调] 调用LLM服务失败: {e}")
            response_text = f"处理工具结果时出错: {str(e)}"

        # 只保存AI回复到历史记录（用户消息已在正常对话流程中保存）
        message_manager.add_message(session_id, "assistant", response_text)
        logger.info("[工具回调] AI回复已保存到历史")

        # 保存对话日志到文件
        message_manager.save_conversation_log(original_user_message, response_text, dev_mode=False)
        logger.info("[工具回调] 对话日志已保存")

        # 通过UI通知接口将AI回复发送给UI
        logger.info("[工具回调] 开始发送AI回复到UI...")
        await _notify_ui_refresh(session_id, response_text)
        _hide_tool_status_in_ui()

        logger.info("[工具回调] 工具结果处理完成，回复已发送到UI")

        return {
            "success": True,
            "message": "工具结果已通过主AI处理并返回给UI",
            "response": response_text,
            "task_id": task_id,
            "session_id": session_id,
        }

    except Exception as e:
        _hide_tool_status_in_ui()
        logger.error(f"[工具回调] 工具结果回调处理失败: {e}")
        raise HTTPException(500, f"处理失败: {str(e)}")


@app.post("/tool_result")
async def tool_result(payload: Dict[str, Any]):
    """接收工具执行结果并显示在UI上"""
    try:
        session_id = payload.get("session_id")
        result = payload.get("result", "")
        notification_type = payload.get("type", "")
        ai_response = payload.get("ai_response", "")

        if not session_id:
            raise HTTPException(400, "缺少session_id")

        logger.info(f"工具执行结果: {result}")

        # 如果是工具完成后的AI回复，存储到ClawdBot回复队列供前端轮询
        if notification_type == "tool_completed_with_ai_response" and ai_response:
            _clawdbot_replies.append(ai_response)
            logger.info(f"[UI] AI回复已存储到队列，长度: {len(ai_response)}")

        return {"success": True, "message": "工具结果已接收", "result": result, "session_id": session_id}

    except Exception as e:
        logger.error(f"处理工具结果失败: {e}")
        raise HTTPException(500, f"处理失败: {str(e)}")


@app.post("/save_tool_conversation")
async def save_tool_conversation(payload: Dict[str, Any]):
    """保存工具对话历史"""
    try:
        session_id = payload.get("session_id")
        user_message = payload.get("user_message", "")
        assistant_response = payload.get("assistant_response", "")

        if not session_id:
            raise HTTPException(400, "缺少session_id")

        logger.info(f"[保存工具对话] 开始保存工具对话历史，会话: {session_id}")

        # 保存用户消息（工具执行结果）
        if user_message:
            message_manager.add_message(session_id, "user", user_message)

        # 保存AI回复
        if assistant_response:
            message_manager.add_message(session_id, "assistant", assistant_response)

        logger.info(f"[保存工具对话] 工具对话历史已保存，会话: {session_id}")

        return {"success": True, "message": "工具对话历史已保存", "session_id": session_id}

    except Exception as e:
        logger.error(f"[保存工具对话] 保存工具对话历史失败: {e}")
        raise HTTPException(500, f"保存失败: {str(e)}")


@app.post("/ui_notification")
async def ui_notification(payload: Dict[str, Any]):
    """UI通知接口 - 用于直接控制UI显示"""
    try:
        session_id = payload.get("session_id")
        action = payload.get("action", "")
        ai_response = payload.get("ai_response", "")
        status_text = payload.get("status_text", "")
        auto_hide_ms_raw = payload.get("auto_hide_ms", 0)

        try:
            auto_hide_ms = int(auto_hide_ms_raw)
        except (TypeError, ValueError):
            auto_hide_ms = 0

        if not session_id:
            raise HTTPException(400, "缺少session_id")

        logger.info(f"UI通知: {action}, 会话: {session_id}")

        # 处理显示工具AI回复的动作
        if action == "show_tool_ai_response" and ai_response:
            _clawdbot_replies.append(ai_response)
            logger.info(f"[UI通知] 工具AI回复已存储到队列，长度: {len(ai_response)}")
            return {"success": True, "message": "AI回复已存储"}

        # 处理显示 AgentServer 回复的动作
        if action == "show_clawdbot_response" and ai_response:
            _clawdbot_replies.append(ai_response)
            logger.info(f"[UI通知] AgentServer 回复已存储到队列，长度: {len(ai_response)}")
            return {"success": True, "message": "AgentServer 回复已存储"}

        if action == "show_tool_status" and status_text:
            _emit_tool_status_to_ui(status_text, auto_hide_ms)
            return {"success": True, "message": "工具状态已显示"}

        if action == "hide_tool_status":
            _hide_tool_status_in_ui()
            return {"success": True, "message": "工具状态已隐藏"}

        return {"success": True, "message": "UI通知已处理"}

    except Exception as e:
        logger.error(f"处理UI通知失败: {e}")
        raise HTTPException(500, f"处理失败: {str(e)}")


async def _trigger_chat_stream_no_intent(session_id: str, response_text: str):
    """触发聊天流式响应但不触发意图分析 - 发送纯粹的AI回复到UI"""
    try:
        logger.info(f"[UI发送] 开始发送AI回复到UI，会话: {session_id}")
        logger.info(f"[UI发送] 发送内容: {response_text[:200]}...")

        # 直接调用现有的流式对话接口，但跳过意图分析
        import httpx

        # 构建请求数据 - 使用纯粹的AI回复内容，并跳过意图分析
        chat_request = {
            "message": response_text,  # 直接使用AI回复内容，不加标记
            "stream": True,
            "session_id": session_id,
            "skip_intent_analysis": True,  # 关键：跳过意图分析
        }

        # 调用现有的流式对话接口
        from system.config import get_server_port

        api_url = f"http://localhost:{get_server_port('api_server')}/chat/stream"

        async with httpx.AsyncClient() as client:
            async with client.stream("POST", api_url, json=chat_request) as response:
                if response.status_code == 200:
                    # 处理流式响应
                    async for chunk in response.aiter_text():
                        if chunk.strip():
                            # 这里可以进一步处理流式响应
                            # 或者直接让UI处理流式响应
                            pass

                    logger.info(f"[UI发送] AI回复已成功发送到UI: {session_id}")
                    logger.info("[UI发送] 成功显示到UI")
                else:
                    logger.error(f"[UI发送] 调用流式对话接口失败: {response.status_code}")

    except Exception as e:
        logger.error(f"[UI发送] 触发聊天流式响应失败: {e}")


async def _notify_ui_refresh(session_id: str, response_text: str):
    """通知UI刷新会话历史"""
    try:
        import httpx

        # 通过UI通知接口直接显示AI回复
        ui_notification_payload = {
            "session_id": session_id,
            "action": "show_tool_ai_response",
            "ai_response": response_text,
        }

        from system.config import get_server_port

        api_url = f"http://localhost:{get_server_port('api_server')}/ui_notification"

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(api_url, json=ui_notification_payload)
            if response.status_code == 200:
                logger.info(f"[UI通知] AI回复显示通知发送成功: {session_id}")
            else:
                logger.error(f"[UI通知] AI回复显示通知失败: {response.status_code}")

    except Exception as e:
        logger.error(f"[UI通知] 通知UI刷新失败: {e}")


def _emit_tool_status_to_ui(status_text: str, auto_hide_ms: int = 0) -> None:
    """更新工具状态存储，前端通过轮询获取"""
    _tool_status_store["current"] = {"message": status_text, "visible": True}


def _hide_tool_status_in_ui() -> None:
    """隐藏工具状态，前端通过轮询获取"""
    _tool_status_store["current"] = {"message": "", "visible": False}


async def _send_ai_response_directly(session_id: str, response_text: str):
    """直接发送AI回复到UI"""
    try:
        import httpx

        # 使用非流式接口发送AI回复
        chat_request = {
            "message": f"[工具结果] {response_text}",  # 添加标记让UI知道这是工具结果
            "stream": False,
            "session_id": session_id,
            "skip_intent_analysis": True,
        }

        from system.config import get_server_port

        api_url = f"http://localhost:{get_server_port('api_server')}/chat"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(api_url, json=chat_request)
            if response.status_code == 200:
                logger.info(f"[直接发送] AI回复已通过非流式接口发送到UI: {session_id}")
            else:
                logger.error(f"[直接发送] 非流式接口发送失败: {response.status_code}")

    except Exception as e:
        logger.error(f"[直接发送] 直接发送AI回复失败: {e}")


# 工具执行结果已通过LLM总结并保存到对话历史中
# UI可以通过查询历史获取工具执行结果
