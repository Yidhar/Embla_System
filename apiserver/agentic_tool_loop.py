#!/usr/bin/env python3
"""
Agentic Tool Loop 核心引擎
实现单LLM agentic loop：模型在对话中发起工具调用，接收结果，再继续推理，直到不再需要工具。
"""

import asyncio
import base64
import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from system.config import get_config, get_server_port
from system.coding_intent import contains_direct_coding_signal, extract_latest_user_message, requires_codex_for_messages
from system.episodic_memory import archive_tool_results_for_session, build_reinjection_context
from system.gc_budget_guard import GCBudgetGuard, GCBudgetGuardConfig
from system.gc_memory_card import build_gc_memory_index_card
from system.gc_reader_bridge import build_gc_reader_followup_plan
from system.global_mutex import LeaseHandle, get_global_mutex_manager
from system.router_arbiter import MAX_DELEGATE_TURNS, evaluate_workspace_conflict_retry
from system.semantic_graph import update_semantic_graph_from_records
from system.tool_contract import ToolCallEnvelope
from .native_tools import get_native_tool_executor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 循环策略与运行态
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgenticLoopPolicy:
    """Agentic loop 编排策略（配置驱动）。"""

    max_rounds: int
    enable_summary_round: bool
    max_consecutive_tool_failures: int
    max_consecutive_validation_failures: int
    max_consecutive_no_tool_rounds: int
    inject_no_tool_feedback: bool
    tool_result_preview_chars: int
    emit_workflow_stage_events: bool
    max_parallel_tool_calls: int
    retry_failed_tool_calls: bool
    max_tool_retries: int
    retry_backoff_seconds: float
    gc_budget_guard_enabled: bool
    gc_budget_repeat_threshold: int
    gc_budget_window_size: int


@dataclass
class AgenticLoopRuntimeState:
    """Agentic loop 运行态统计。"""

    round_num: int = 0
    total_tool_calls: int = 0
    total_tool_success: int = 0
    total_tool_errors: int = 0
    consecutive_tool_failures: int = 0
    consecutive_validation_failures: int = 0
    consecutive_no_tool_rounds: int = 0
    gc_guard_repeat_count: int = 0
    gc_guard_error_total: int = 0
    gc_guard_success_total: int = 0
    gc_guard_hit_total: int = 0
    stop_reason: str = ""


def _clamp_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        num = int(value)
    except Exception:
        return default
    return max(min_value, min(max_value, num))


def _resolve_agentic_loop_policy(max_rounds_override: Optional[int]) -> AgenticLoopPolicy:
    cfg = get_config()
    handoff_cfg = getattr(cfg, "handoff", None)
    loop_cfg = getattr(cfg, "agentic_loop", None)

    fallback_rounds = 500
    if handoff_cfg is not None:
        fallback_rounds = _clamp_int(getattr(handoff_cfg, "max_loop_stream", 500), 500, 1, 5000)

    configured_rounds = fallback_rounds
    if loop_cfg is not None:
        configured_rounds = _clamp_int(getattr(loop_cfg, "max_rounds_stream", fallback_rounds), fallback_rounds, 1, 5000)

    if max_rounds_override is not None and int(max_rounds_override) > 0:
        max_rounds = _clamp_int(max_rounds_override, configured_rounds, 1, 5000)
    else:
        max_rounds = configured_rounds

    if loop_cfg is None:
        return AgenticLoopPolicy(
            max_rounds=max_rounds,
            enable_summary_round=True,
            max_consecutive_tool_failures=2,
            max_consecutive_validation_failures=2,
            max_consecutive_no_tool_rounds=2,
            inject_no_tool_feedback=True,
            tool_result_preview_chars=500,
            emit_workflow_stage_events=True,
            max_parallel_tool_calls=8,
            retry_failed_tool_calls=True,
            max_tool_retries=1,
            retry_backoff_seconds=0.8,
            gc_budget_guard_enabled=True,
            gc_budget_repeat_threshold=3,
            gc_budget_window_size=6,
        )

    return AgenticLoopPolicy(
        max_rounds=max_rounds,
        enable_summary_round=bool(getattr(loop_cfg, "enable_summary_round", True)),
        max_consecutive_tool_failures=_clamp_int(
            getattr(loop_cfg, "max_consecutive_tool_failures", 2), 2, 1, 20
        ),
        max_consecutive_validation_failures=_clamp_int(
            getattr(loop_cfg, "max_consecutive_validation_failures", 2), 2, 1, 20
        ),
        max_consecutive_no_tool_rounds=_clamp_int(
            getattr(loop_cfg, "max_consecutive_no_tool_rounds", 2), 2, 1, 20
        ),
        inject_no_tool_feedback=bool(getattr(loop_cfg, "inject_no_tool_feedback", True)),
        tool_result_preview_chars=_clamp_int(
            getattr(loop_cfg, "tool_result_preview_chars", 500), 500, 120, 20000
        ),
        emit_workflow_stage_events=bool(getattr(loop_cfg, "emit_workflow_stage_events", True)),
        max_parallel_tool_calls=_clamp_int(getattr(loop_cfg, "max_parallel_tool_calls", 8), 8, 1, 64),
        retry_failed_tool_calls=bool(getattr(loop_cfg, "retry_failed_tool_calls", True)),
        max_tool_retries=_clamp_int(getattr(loop_cfg, "max_tool_retries", 1), 1, 0, 5),
        retry_backoff_seconds=float(getattr(loop_cfg, "retry_backoff_seconds", 0.8)),
        gc_budget_guard_enabled=bool(getattr(loop_cfg, "gc_budget_guard_enabled", True)),
        gc_budget_repeat_threshold=_clamp_int(getattr(loop_cfg, "gc_budget_repeat_threshold", 3), 3, 2, 10),
        gc_budget_window_size=_clamp_int(getattr(loop_cfg, "gc_budget_window_size", 6), 6, 2, 30),
    )


def _is_retryable_tool_failure(call: Dict[str, Any], result: Dict[str, Any]) -> bool:
    if bool(call.get("no_retry", False)):
        return False

    err_text = str(result.get("result", "") or "")
    non_retry_markers = [
        "需要登录",
        "缺少",
        "不支持",
        "参数",
        "安全限制",
        "Blocked",
        "blocked",
        "unauthorized",
        "forbidden",
    ]
    return not any(marker in err_text for marker in non_retry_markers)


def _summarize_results_for_frontend(results: List[Dict[str, Any]], preview_chars: int) -> List[Dict[str, Any]]:
    summaries: List[Dict[str, Any]] = []
    limit = _clamp_int(preview_chars, 500, 120, 20000)
    for r in results:
        result_text = str(r.get("result", ""))
        display_result = result_text[:limit] + "..." if len(result_text) > limit else result_text
        summaries.append(
            {
                "service_name": r.get("service_name", "unknown"),
                "tool_name": r.get("tool_name", ""),
                "status": r.get("status", "unknown"),
                "result": display_result,
            }
        )
        if r.get("conflict_ticket"):
            summaries[-1]["conflict_ticket"] = str(r.get("conflict_ticket"))
        if r.get("delegate_turns") is not None:
            summaries[-1]["delegate_turns"] = _clamp_int(r.get("delegate_turns"), 0, 0, 10000)
        if "freeze" in r:
            summaries[-1]["freeze"] = bool(r.get("freeze"))
        if "hitl" in r:
            summaries[-1]["hitl"] = bool(r.get("hitl"))
        router_arbiter = r.get("router_arbiter")
        if isinstance(router_arbiter, dict):
            summaries[-1]["router_arbiter"] = router_arbiter
        gc_budget_guard = r.get("gc_budget_guard")
        if isinstance(gc_budget_guard, dict):
            summaries[-1]["gc_budget_guard"] = gc_budget_guard
        if "guard_hit" in r:
            summaries[-1]["guard_hit"] = bool(r.get("guard_hit"))
        if r.get("guard_stop_reason"):
            summaries[-1]["guard_stop_reason"] = str(r.get("guard_stop_reason"))
    return summaries


def _looks_like_pending_tool_intent(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    markers = [
        "我先查",
        "我来查",
        "我先看",
        "我来看看",
        "让我查",
        "让我看",
        "正在检查",
        "稍等",
        "I'll check",
        "let me check",
        "I will check",
    ]
    return any(m in lowered for m in markers)


def _is_explicit_no_tool_completion(text: str) -> bool:
    """Detect explicit model signal that no additional tools are needed."""
    if not text:
        return False

    compact = re.sub(r"\s+", "", text).lower()
    cn_markers = (
        "不需要工具",
        "无需工具",
        "不需要额外工具",
        "无需额外工具",
    )
    if any(marker in compact for marker in cn_markers):
        return True

    lowered = text.lower()
    en_markers = (
        "no tool needed",
        "no tools needed",
        "no additional tools needed",
        "no need to use tools",
        "no extra tools needed",
        "no_tool_needed",
    )
    return any(marker in lowered for marker in en_markers)


_END_MARKER_RE = re.compile(r"\{\s*end\s*\}", re.IGNORECASE)


def _find_end_marker_span(text: str) -> Optional[Tuple[int, int]]:
    if not text:
        return None
    matched = _END_MARKER_RE.search(text)
    if not matched:
        return None
    return matched.span()


def _extract_terminal_stream_error_text(text: str) -> str:
    """Detect fatal upstream stream errors that should stop the loop immediately."""
    if not text:
        return ""
    normalized = " ".join(str(text).strip().split())
    lowered = normalized.lower()
    markers = (
        "streaming call error",
        "google streaming error",
        "google live streaming error",
        "llm service unavailable",
        "chat call error",
        "google api call error",
        "login expired",
    )
    return normalized if any(marker in lowered for marker in markers) else ""


_CODING_KEYWORDS = (
    "修复",
    "实现",
    "重构",
    "改造",
    "写代码",
    "代码",
    "开发",
    "bug",
    "fix",
    "implement",
    "refactor",
    "coding",
    "unit test",
    "integration test",
    "lint",
    "compile",
    "build",
    "repo",
    "repository",
)
_CODEX_SERVICE_ALIASES = {"codex-cli", "codex-mcp"}
_CODEX_TOOL_NAMES = {"ask-codex", "brainstorm", "help", "ping"}
_MUTATING_NATIVE_TOOL_NAMES = {"write_file", "git_checkout_file", "workspace_txn_apply"}


def _extract_latest_user_message(messages: List[Dict[str, Any]]) -> str:
    return extract_latest_user_message(messages)


def _looks_like_coding_request(text: str) -> bool:
    if contains_direct_coding_signal(text):
        return True
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in _CODING_KEYWORDS)


def _inject_ephemeral_system_context(messages: List[Dict[str, Any]], content: str) -> bool:
    text = str(content or "").strip()
    if not text:
        return False

    marker = "[Episodic Memory Reinjection]"
    for msg in messages:
        if str(msg.get("role", "")).strip() == "system" and marker in str(msg.get("content", "")):
            return False

    insert_at = 0
    while insert_at < len(messages) and str(messages[insert_at].get("role", "")).strip() == "system":
        insert_at += 1
    messages.insert(insert_at, {"role": "system", "content": text})
    return True


def _is_codex_mcp_call(call: Dict[str, Any]) -> bool:
    if str(call.get("agentType", "")).strip().lower() != "mcp":
        return False
    service = str(call.get("service_name", "")).strip().lower()
    tool = str(call.get("tool_name", "")).strip().lower()
    if tool in _CODEX_TOOL_NAMES and (not service or service in _CODEX_SERVICE_ALIASES):
        return True
    return service in _CODEX_SERVICE_ALIASES


def _is_mutating_native_call(call: Dict[str, Any]) -> bool:
    if str(call.get("agentType", "")).strip().lower() != "native":
        return False
    tool_name = str(call.get("tool_name", "")).strip().lower()
    return tool_name in _MUTATING_NATIVE_TOOL_NAMES


def _build_tool_envelope_from_call(call: Dict[str, Any]) -> ToolCallEnvelope:
    tool_name = str(call.get("tool_name", "") or "unknown")
    legacy_call = {
        "tool_name": tool_name,
        "_tool_call_id": call.get("_tool_call_id"),
        "arguments": {k: v for k, v in call.items() if not str(k).startswith("_")},
    }
    return ToolCallEnvelope.from_legacy_call(
        legacy_call,
        session_id=str(call.get("_session_id") or "") or None,
        trace_id=str(call.get("_trace_id") or "") or None,
    )


def _requires_global_mutex(call: Dict[str, Any]) -> bool:
    try:
        envelope = _build_tool_envelope_from_call(call)
        return bool(envelope.requires_global_mutex)
    except Exception:
        return False


def _apply_parallel_contract_gate(actionable_calls: List[Dict[str, Any]]) -> Tuple[List[str], bool]:
    """
    WS13-002:
    - Parallel mutating calls must share the same non-empty contract_id.
    - On mismatch, downgrade this round to serial mode instead of blind parallel writes.
    """
    mutating_native_calls = [call for call in actionable_calls if _is_mutating_native_call(call)]
    if len(mutating_native_calls) <= 1:
        return [], False

    contract_ids = {
        str(call.get("contract_id") or "").strip()
        for call in mutating_native_calls
    }
    checksum_values = {
        str(call.get("contract_checksum") or "").strip()
        for call in mutating_native_calls
        if str(call.get("contract_checksum") or "").strip()
    }

    gate_messages: List[str] = []
    force_serial = False
    if "" in contract_ids or len(contract_ids) != 1:
        force_serial = True
        gate_messages.append(
            "Contract gate: parallel mutating calls missing/mismatched contract_id; downgraded to serial execution."
        )
    if len(checksum_values) > 1:
        force_serial = True
        gate_messages.append(
            "Contract gate: parallel mutating calls mismatched contract_checksum; downgraded to serial execution."
        )

    if force_serial:
        for call in mutating_native_calls:
            call["_force_serial"] = True

    return gate_messages, force_serial


def _build_forced_codex_call(user_request: str, round_num: int) -> Dict[str, Any]:
    prompt = user_request.strip() if user_request else ""
    if not prompt:
        prompt = "Complete the pending coding task in current repository."

    return {
        "agentType": "mcp",
        "service_name": "codex-cli",
        "tool_name": "ask-codex",
        "message": prompt,
        "sandboxMode": "workspace-write",
        "approvalPolicy": "on-failure",
        "_tool_call_id": f"forced_codex_round_{round_num}",
    }


def _apply_codex_first_guard(
    actionable_calls: List[Dict[str, Any]],
    *,
    requires_codex: bool,
    codex_engaged: bool,
    latest_user_request: str,
    round_num: int,
) -> Tuple[List[Dict[str, Any]], bool, int]:
    """Ensure coding tasks route through codex before mutating local native tools."""
    if not requires_codex or codex_engaged:
        return actionable_calls, codex_engaged, 0

    if any(_is_codex_mcp_call(call) for call in actionable_calls):
        return actionable_calls, True, 0

    blocked_mutating = 0
    passthrough_calls: List[Dict[str, Any]] = []
    for call in actionable_calls:
        if _is_mutating_native_call(call):
            blocked_mutating += 1
            continue
        passthrough_calls.append(call)

    forced_calls = [_build_forced_codex_call(latest_user_request, round_num), *passthrough_calls]
    return forced_calls, True, blocked_mutating


_WORKFLOW_PHASES = {"plan", "execute", "verify", "repair"}
_WORKFLOW_PHASE_STATUS = {"start", "success", "error", "skip"}


def _format_workflow_stage_event(
    round_num: int,
    phase: str,
    status: str,
    *,
    policy: AgenticLoopPolicy,
    reason: str = "",
    decision: str = "",
    details: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    if not policy.emit_workflow_stage_events:
        return None

    normalized_phase = phase if phase in _WORKFLOW_PHASES else "verify"
    normalized_status = status if status in _WORKFLOW_PHASE_STATUS else "start"
    payload: Dict[str, Any] = {
        "round": round_num,
        "phase": normalized_phase,
        "status": normalized_status,
    }
    if reason:
        payload["reason"] = reason
    if decision:
        payload["decision"] = decision
    if details:
        payload.update(details)
    return _format_sse_event("tool_stage", payload)


def _parse_structured_tool_calls_payload(raw_payload: Any) -> List[Dict[str, Any]]:
    def _normalize(value: Any) -> List[Dict[str, Any]]:
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []

    if isinstance(raw_payload, (dict, list)):
        return _normalize(raw_payload)
    if not isinstance(raw_payload, str):
        return []

    payload_text = raw_payload.strip()
    if not payload_text:
        return []

    parsed: Any = None
    try:
        parsed = json.loads(payload_text)
    except Exception:
        try:
            import json5 as _json5

            parsed = _json5.loads(payload_text)
        except Exception:
            return []
    return _normalize(parsed)


def _detect_legacy_tool_protocol_violation(
    complete_text: str,
    structured_calls: List[Dict[str, Any]],
) -> Optional[str]:
    if structured_calls:
        return None
    if not complete_text:
        return None

    lowered = complete_text.lower()
    if "```tool" in lowered:
        return (
            "检测到旧式 ```tool``` 代码块。当前系统仅接受原生 function calling，"
            "请直接发起函数调用，不要在正文输出工具 JSON。"
        )

    # 不执行旧协议，仅将其视为协议违规并让模型纠偏。
    if re.search(r"\"agentType\"\s*:\s*\"[A-Za-z0-9_\-]+\"", complete_text):
        return (
            "检测到正文中的 agentType 工具 JSON。当前系统仅接受原生 function calling，"
            "请改为函数调用。"
        )
    return None


def _shorten_for_log(value: Any, limit: int = 300) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _normalize_codex_mcp_call_payload(call: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(call or {})
    tool_name = str(normalized.get("tool_name", "")).strip()
    if tool_name != "ask-codex":
        return normalized

    nested_args = normalized.get("arguments")
    prompt = normalized.get("prompt")
    message = normalized.get("message")

    if (prompt is None or prompt == "") and isinstance(message, str) and message.strip():
        normalized["prompt"] = message
        prompt = message

    if (prompt is None or prompt == "") and isinstance(nested_args, dict):
        nested_prompt = nested_args.get("prompt")
        nested_message = nested_args.get("message")
        if isinstance(nested_prompt, str) and nested_prompt.strip():
            normalized["prompt"] = nested_prompt
        elif isinstance(nested_message, str) and nested_message.strip():
            normalized["prompt"] = nested_message

    normalized.pop("message", None)
    normalized.setdefault("sandboxMode", "workspace-write")
    normalized.setdefault("approvalPolicy", "on-failure")
    return normalized


def _extract_mcp_call_status(raw_result: Any) -> Tuple[str, str]:
    if not isinstance(raw_result, str):
        return "ok", _shorten_for_log(raw_result)
    try:
        parsed = json.loads(raw_result)
    except Exception:
        return "ok", _shorten_for_log(raw_result)

    if not isinstance(parsed, dict):
        return "ok", _shorten_for_log(raw_result)

    status = str(parsed.get("status", "ok"))
    if "message" in parsed:
        detail = parsed.get("message", "")
    elif "result" in parsed:
        detail = parsed.get("result", "")
    else:
        detail = raw_result
    return status, _shorten_for_log(detail)


# ---------------------------------------------------------------------------
# 工具执行
# ---------------------------------------------------------------------------


async def _execute_mcp_call(call: Dict[str, Any]) -> Dict[str, Any]:
    """执行单个MCP调用"""
    call = _normalize_codex_mcp_call_payload(call)
    service_name = call.get("service_name", "")
    tool_name = call.get("tool_name", "")
    call_id = str(call.get("_tool_call_id") or f"mcp_call_{tool_name or 'unknown'}")

    if not service_name and tool_name in {
        "ask_guide",
        "ask_guide_with_screenshot",
        "calculate_damage",
        "get_team_recommendation",
    }:
        service_name = "game_guide"
        call["service_name"] = service_name

    # Coding tasks via Codex MCP: allow omission of service_name in call payload.
    if not service_name and tool_name in {"ask-codex", "brainstorm", "help", "ping"}:
        service_name = "codex-cli"
        call["service_name"] = service_name

    if tool_name == "ask-codex":
        call.setdefault("sandboxMode", "workspace-write")
        call.setdefault("approvalPolicy", "on-failure")

    prompt_len = len(str(call.get("prompt") or "")) if tool_name == "ask-codex" else 0
    logger.info(
        "[AgenticLoop] MCP tool start id=%s service=%s tool=%s prompt_len=%s payload_keys=%s",
        call_id,
        service_name or "<missing>",
        tool_name or "<missing>",
        prompt_len,
        sorted(call.keys()),
    )

    # 游戏攻略功能仅登录用户可用
    if service_name == "game_guide":
        from apiserver import naga_auth

        if not naga_auth.is_authenticated():
            return {
                "tool_call": call,
                "result": "游戏攻略功能需要登录 Naga 账号后才能使用，请先登录。",
                "status": "error",
                "service_name": service_name,
                "tool_name": tool_name,
            }

    try:
        from mcpserver.mcp_manager import get_mcp_manager

        manager = get_mcp_manager()
        result = await manager.unified_call(service_name, call)
        mcp_status, mcp_detail = _extract_mcp_call_status(result)
        if mcp_status == "error":
            logger.warning(
                "[AgenticLoop] MCP tool failed id=%s service=%s tool=%s detail=%s",
                call_id,
                service_name,
                tool_name,
                mcp_detail,
            )
            return {
                "tool_call": call,
                "result": result,
                "status": "error",
                "service_name": service_name,
                "tool_name": tool_name,
            }
        logger.info(
            "[AgenticLoop] MCP tool success id=%s service=%s tool=%s detail=%s",
            call_id,
            service_name,
            tool_name,
            mcp_detail,
        )
        return {
            "tool_call": call,
            "result": result,
            "status": "success",
            "service_name": service_name,
            "tool_name": tool_name,
        }
    except Exception as e:
        logger.error("[AgenticLoop] MCP调用异常 id=%s service=%s tool=%s error=%s", call_id, service_name, tool_name, e)
        return {
            "tool_call": call,
            "result": f"调用失败: {e}",
            "status": "error",
            "service_name": service_name,
            "tool_name": tool_name,
        }
async def _execute_native_call(call: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    """执行单个本地native调用"""
    executor = get_native_tool_executor()
    return await executor.execute(call, session_id=session_id)


async def _send_live2d_actions(live2d_calls: List[Dict[str, Any]], session_id: str):
    """Fire-and-forget发送Live2D动作到UI"""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout=5.0)) as client:
            for call in live2d_calls:
                action_name = call.get("action", "")
                logger.info(f"[AgenticLoop] 发送 Live2D 动作: {action_name}, 完整调用: {call}")
                if not action_name:
                    continue
                payload = {
                    "session_id": session_id,
                    "action": "live2d_action",
                    "action_name": action_name,
                }
                try:
                    await client.post(
                        f"http://localhost:{get_server_port('api_server')}/ui_notification",
                        json=payload,
                    )
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"[AgenticLoop] Live2D动作发送失败: {e}")


async def _execute_single_tool_call(call: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    agent_type = call.get("agentType", "")
    if agent_type == "mcp":
        return await _execute_mcp_call(call)
    if agent_type == "native":
        return await _execute_native_call(call, session_id)

    logger.warning(f"[AgenticLoop] 未知agentType: {agent_type}, 跳过: {call}")
    return {
        "tool_call": call,
        "result": f"未知agentType: {agent_type}",
        "status": "error",
        "service_name": "unknown",
        "tool_name": "unknown",
    }


async def _execute_tool_call_with_retry(
    call: Dict[str, Any],
    session_id: str,
    *,
    semaphore: asyncio.Semaphore,
    retry_failed: bool,
    max_retries: int,
    retry_backoff_seconds: float,
) -> Dict[str, Any]:
    max_attempts = max(1, int(max_retries) + 1)
    max_delegate_turns = _clamp_int(call.get("max_delegate_turns"), MAX_DELEGATE_TURNS, 1, 20)
    tracked_conflict_ticket = ""
    tracked_delegate_turns = 0
    call_id = str(call.get("_tool_call_id") or f"tool_{uuid.uuid4().hex[:8]}")
    agent_type = str(call.get("agentType", ""))
    service_name = str(call.get("service_name", ""))
    tool_name = str(call.get("tool_name", call.get("task_type", "")))
    for attempt in range(1, max_attempts + 1):
        logger.info(
            "[AgenticLoop] tool attempt start id=%s agent=%s service=%s tool=%s attempt=%s/%s",
            call_id,
            agent_type,
            service_name or "<n/a>",
            tool_name or "<n/a>",
            attempt,
            max_attempts,
        )
        lease: Optional[LeaseHandle] = None
        heartbeat_task: Optional[asyncio.Task[None]] = None
        stop_heartbeat = asyncio.Event()
        heartbeat_errors: List[str] = []
        mutex_manager = None
        try:
            if _requires_global_mutex(call):
                mutex_manager = get_global_mutex_manager()
                lease = await mutex_manager.acquire(
                    owner_id=str(session_id or call.get("_session_id") or "unknown_session"),
                    job_id=call_id,
                    ttl_seconds=10.0,
                    wait_timeout_seconds=30.0,
                    poll_interval_seconds=0.2,
                )
                call["_fencing_epoch"] = lease.fencing_epoch

                async def _heartbeat_loop() -> None:
                    nonlocal lease
                    if lease is None:
                        return
                    interval = max(1.0, min(5.0, lease.ttl_seconds / 2.0))
                    while not stop_heartbeat.is_set():
                        await asyncio.sleep(interval)
                        if stop_heartbeat.is_set():
                            return
                        try:
                            lease = await mutex_manager.renew(lease)  # type: ignore[union-attr]
                        except Exception as hb_exc:
                            heartbeat_errors.append(str(hb_exc))
                            return

                heartbeat_task = asyncio.create_task(_heartbeat_loop())

            async with semaphore:
                result = await _execute_single_tool_call(call, session_id)

            if heartbeat_errors:
                result = {
                    "tool_call": call,
                    "result": f"lease heartbeat failed: {'; '.join(heartbeat_errors)}",
                    "status": "error",
                    "service_name": "runtime",
                    "tool_name": tool_name or "unknown",
                }
        except Exception as e:
            result = {
                "tool_call": call,
                "result": f"执行异常: {e}",
                "status": "error",
                "service_name": "unknown",
                "tool_name": "unknown",
            }
        finally:
            stop_heartbeat.set()
            if heartbeat_task is not None:
                try:
                    await heartbeat_task
                except Exception:
                    pass
            if lease is not None and mutex_manager is not None:
                try:
                    await mutex_manager.release(lease)
                except Exception:
                    pass

        logger.info(
            "[AgenticLoop] tool attempt done id=%s status=%s service=%s tool=%s result=%s",
            call_id,
            result.get("status", "unknown"),
            result.get("service_name", service_name or "unknown"),
            result.get("tool_name", tool_name or "unknown"),
            _shorten_for_log(result.get("result", "")),
        )

        if result.get("status") != "error":
            if attempt > 1:
                result["retry_attempts"] = attempt - 1
            return result

        arbiter_signal = evaluate_workspace_conflict_retry(
            call,
            result,
            previous_conflict_ticket=tracked_conflict_ticket,
            previous_delegate_turns=tracked_delegate_turns,
            max_delegate_turns=max_delegate_turns,
        )
        if arbiter_signal is not None:
            tracked_conflict_ticket = arbiter_signal.conflict_ticket or tracked_conflict_ticket
            tracked_delegate_turns = arbiter_signal.delegate_turns
            result["conflict_ticket"] = tracked_conflict_ticket
            result["delegate_turns"] = tracked_delegate_turns
            result["freeze"] = arbiter_signal.freeze
            result["hitl"] = arbiter_signal.hitl
            result["router_arbiter"] = arbiter_signal.to_payload()
            if arbiter_signal.escalated:
                result["retry_attempts"] = attempt - 1
                logger.warning(
                    "[AgenticLoop] router arbiter escalation id=%s conflict_ticket=%s delegate_turns=%s threshold=%s",
                    call_id,
                    tracked_conflict_ticket or "<unknown>",
                    tracked_delegate_turns,
                    max_delegate_turns,
                )
                return result

        if not retry_failed:
            return result
        if attempt >= max_attempts:
            result["retry_attempts"] = max_attempts - 1
            return result
        if not _is_retryable_tool_failure(call, result):
            return result

        await asyncio.sleep(max(0.0, min(10.0, retry_backoff_seconds * attempt)))

    return {
        "tool_call": call,
        "result": "执行异常: 未知重试状态",
        "status": "error",
        "service_name": "unknown",
        "tool_name": "unknown",
    }


async def execute_tool_calls(
    tool_calls: List[Dict[str, Any]],
    session_id: str,
    *,
    max_parallel_calls: int = 8,
    retry_failed: bool = True,
    max_retries: int = 1,
    retry_backoff_seconds: float = 0.8,
) -> List[Dict[str, Any]]:
    """并发执行工具调用（不包含 live2d），支持重试与并发控制。"""
    if not tool_calls:
        return []

    force_serial = any(bool(call.get("_force_serial", False)) for call in tool_calls)
    parallel_limit = 1 if force_serial else _clamp_int(max_parallel_calls, 8, 1, 64)
    semaphore = asyncio.Semaphore(parallel_limit)

    tasks = [
        _execute_tool_call_with_retry(
            call,
            session_id,
            semaphore=semaphore,
            retry_failed=retry_failed,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
        )
        for call in tool_calls
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)
    final: List[Dict[str, Any]] = []
    for idx, r in enumerate(results):
        if isinstance(r, Exception):
            final.append(
                {
                    "tool_call": tool_calls[idx] if idx < len(tool_calls) else {},
                    "result": f"执行异常: {r}",
                    "status": "error",
                    "service_name": "unknown",
                    "tool_name": "unknown",
                }
            )
        else:
            final.append(r)
    return final


def _build_gc_reader_suggestion_result(reason: str, suggestion: str, error_text: str = "") -> Dict[str, Any]:
    lines = [
        "[gc_reader_bridge] 自动证据回读已降级为建议。",
        f"[reason] {reason or 'unknown'}",
    ]
    if error_text:
        lines.append(f"[readback_error] {error_text}")
    if suggestion:
        lines.append(f"[suggested_call] {suggestion}")
    return {
        "tool_call": {"agentType": "native", "tool_name": "artifact_reader", "_gc_reader_bridge": True},
        "result": "\n".join(lines),
        "status": "success",
        "service_name": "gc_reader_bridge",
        "tool_name": "artifact_reader_suggestion",
    }


async def _maybe_execute_gc_reader_followup(
    primary_results: List[Dict[str, Any]],
    session_id: str,
    *,
    round_num: int,
) -> List[Dict[str, Any]]:
    """Execute at most one automatic artifact_reader follow-up for current round."""
    plan = build_gc_reader_followup_plan(primary_results, round_num=round_num, max_calls_per_round=1)
    if not plan.call:
        return []

    logger.info(
        "[AgenticLoop] gc_reader_bridge trigger round=%s source_index=%s reason=%s",
        round_num,
        plan.source_index,
        plan.reason,
    )
    try:
        followup_results = await execute_tool_calls(
            [plan.call],
            session_id,
            max_parallel_calls=1,
            retry_failed=False,
            max_retries=0,
            retry_backoff_seconds=0.0,
        )
    except Exception as exc:
        logger.warning("[AgenticLoop] gc_reader_bridge execution failed round=%s error=%s", round_num, exc)
        return [
            _build_gc_reader_suggestion_result(
                reason=plan.reason,
                suggestion=plan.suggestion,
                error_text=str(exc),
            )
        ]

    if followup_results and followup_results[0].get("status") == "error":
        err_preview = str(followup_results[0].get("result", ""))
        logger.warning(
            "[AgenticLoop] gc_reader_bridge follow-up failed round=%s detail=%s",
            round_num,
            _shorten_for_log(err_preview),
        )
        followup_results.append(
            _build_gc_reader_suggestion_result(
                reason=plan.reason,
                suggestion=plan.suggestion,
                error_text=err_preview,
            )
        )
    return followup_results


# ---------------------------------------------------------------------------
# 格式化
# ---------------------------------------------------------------------------


def format_tool_results_for_llm(results: List[Dict[str, Any]]) -> str:
    """将工具执行结果格式化为LLM可理解的文本"""
    parts = []
    total = len(results)
    for idx, r in enumerate(results, 1):
        memory_card = build_gc_memory_index_card(r, index=idx, total=total)
        if memory_card:
            parts.append(memory_card)
            continue

        svc = r.get("service_name", "unknown")
        tool = r.get("tool_name", "")
        status = r.get("status", "unknown")
        result_text = r.get("result", "")
        label = f"{svc}"
        if tool:
            label += f": {tool}"
        parts.append(f"[工具结果 {idx}/{total} - {label} ({status})]\n{result_text}")
    return "\n\n".join(parts)


def get_agentic_tool_definitions() -> List[Dict[str, Any]]:
    """原生工具调用定义（OpenAI-compatible tools schema）"""
    return [
        {
            "type": "function",
            "function": {
                "name": "native_call",
                "description": "Execute a local native tool in current project workspace.",
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "tool_name": {
                            "type": "string",
                            "enum": [
                                "read_file",
                                "write_file",
                                "get_cwd",
                                "run_cmd",
                                "search_keyword",
                                "query_docs",
                                "list_files",
                                "git_status",
                                "git_diff",
                                "git_log",
                                "git_show",
                                "git_blame",
                                "git_grep",
                                "git_changed_files",
                                "git_checkout_file",
                                "python_repl",
                                "artifact_reader",
                                "file_ast_skeleton",
                                "file_ast_chunk_read",
                                "workspace_txn_apply",
                                "sleep_and_watch",
                                "killswitch_plan",
                                "os_bash",
                            ],
                        },
                        "path": {"type": "string"},
                        "file_path": {"type": "string"},
                        "artifact_id": {"type": "string"},
                        "forensic_artifact_ref": {"type": "string"},
                        "raw_result_ref": {"type": "string"},
                        "content": {"type": "string"},
                        "changes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "path": {"type": "string"},
                                    "file_path": {"type": "string"},
                                    "content": {"type": "string"},
                                    "mode": {"type": "string", "enum": ["overwrite", "append"]},
                                    "encoding": {"type": "string"},
                                },
                                "required": ["content"],
                            },
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["overwrite", "append", "preview", "line_range", "grep", "jsonpath", "freeze"],
                        },
                        "encoding": {"type": "string"},
                        "command": {"type": "string"},
                        "cmd": {"type": "string"},
                        "cwd": {"type": "string"},
                        "artifact_priority": {"type": "string", "enum": ["low", "normal", "high", "critical"]},
                        "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 1200},
                        "keyword": {"type": "string"},
                        "query": {"type": "string"},
                        "jsonpath": {"type": "string"},
                        "log_file": {"type": "string"},
                        "regex": {"type": "string"},
                        "search_path": {"type": "string"},
                        "repo_path": {"type": "string"},
                        "target_path": {"type": "string"},
                        "pathspec": {"type": "string"},
                        "pattern": {"type": "string"},
                        "ref": {"type": "string"},
                        "base_ref": {"type": "string"},
                        "since": {"type": "string"},
                        "pretty": {"type": "string"},
                        "docker_image": {"type": "string"},
                        "python_cmd": {"type": "string"},
                        "code": {"type": "string"},
                        "expression": {"type": "string"},
                        "sandbox": {"type": "string", "enum": ["restricted", "docker"]},
                        "glob": {"type": "string"},
                        "case_sensitive": {"type": "boolean"},
                        "use_regex": {"type": "boolean"},
                        "short": {"type": "boolean"},
                        "branch": {"type": "boolean"},
                        "porcelain": {"type": "boolean"},
                        "include_untracked": {"type": "boolean"},
                        "confirm": {"type": "boolean"},
                        "cached": {"type": "boolean"},
                        "staged": {"type": "boolean"},
                        "worktree": {"type": "boolean"},
                        "name_only": {"type": "boolean"},
                        "stat": {"type": "boolean"},
                        "stat_only": {"type": "boolean"},
                        "oneline": {"type": "boolean"},
                        "max_results": {"type": "integer", "minimum": 1, "maximum": 1000},
                        "max_count": {"type": "integer", "minimum": 1, "maximum": 500},
                        "max_lines": {"type": "integer", "minimum": 1, "maximum": 5000},
                        "max_file_size_kb": {"type": "integer", "minimum": 64, "maximum": 4096},
                        "unified": {"type": "integer", "minimum": 0, "maximum": 30},
                        "start_line": {"type": "integer", "minimum": 1},
                        "end_line": {"type": "integer", "minimum": 1},
                        "context_before": {"type": "integer", "minimum": 0, "maximum": 200},
                        "context_after": {"type": "integer", "minimum": 0, "maximum": 200},
                        "max_chars": {"type": "integer", "minimum": 200, "maximum": 100000},
                        "max_output_chars": {"type": "integer", "minimum": 200, "maximum": 500000},
                        "poll_interval_seconds": {"type": "number", "minimum": 0.05, "maximum": 10.0},
                        "from_end": {"type": "boolean"},
                        "max_line_chars": {"type": "integer", "minimum": 64, "maximum": 20000},
                        "contract_id": {"type": "string"},
                        "contract_checksum": {"type": "string"},
                        "verify_after_apply": {"type": "boolean"},
                        "oob_allowlist": {"type": "array", "items": {"type": "string"}},
                        "dns_allow": {"type": "boolean"},
                        "recursive": {"type": "boolean"},
                    },
                    "required": ["tool_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "mcp_call",
                "description": "Invoke one MCP service tool.",
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "service_name": {"type": "string"},
                        "tool_name": {"type": "string"},
                        "arguments": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["tool_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "live2d_action",
                "description": "Trigger Live2D UI action.",
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["normal", "happy", "enjoy", "sad", "surprise"],
                        }
                    },
                    "required": ["action"],
                },
            },
        },
    ]


def _convert_structured_tool_calls(
    structured_calls: List[Dict[str, Any]],
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    """
    转换结构化工具调用，注入上下文元数据

    NGA-WS10-002: 注入 call_id/trace_id/session_id 等上下文元数据
    """
    actionable_calls: List[Dict[str, Any]] = []
    live2d_calls: List[Dict[str, Any]] = []
    validation_errors: List[str] = []

    # 生成 trace_id（如果未提供）
    if not trace_id:
        trace_id = f"trace_{uuid.uuid4().hex[:16]}"

    for idx, call in enumerate(structured_calls, 1):
        call_id = str(call.get("id") or f"tool_call_{idx}")
        tool_name = str(call.get("name") or "").strip()
        parse_error = call.get("parse_error")
        args = call.get("arguments")

        # 注入上下文元数据（NGA-WS10-002）
        call["_tool_call_id"] = call_id
        call["_trace_id"] = trace_id
        if session_id:
            call["_session_id"] = session_id

        if parse_error:
            validation_errors.append(f"工具调用参数解析失败: id={call_id}, error={parse_error}")
            continue

        if not isinstance(args, dict):
            validation_errors.append(f"工具调用参数非法: id={call_id}, name={tool_name}, arguments必须是对象")
            continue

        if tool_name == "native_call":
            native_tool_name = str(args.get("tool_name") or "").strip()
            if not native_tool_name:
                validation_errors.append(f"native_call 缺少 tool_name: id={call_id}")
                continue
            native_call = {
                "agentType": "native",
                **args,
                "_tool_call_id": call_id,
                "_trace_id": trace_id,
            }
            if session_id:
                native_call["_session_id"] = session_id
            actionable_calls.append(native_call)
            continue

        if tool_name == "mcp_call":
            mcp_tool_name = str(args.get("tool_name") or "").strip()
            if not mcp_tool_name:
                validation_errors.append(f"mcp_call 缺少 tool_name: id={call_id}")
                continue

            merged_call: Dict[str, Any] = {
                "agentType": "mcp",
                "tool_name": mcp_tool_name,
                "_tool_call_id": call_id,
                "_trace_id": trace_id,
            }
            if session_id:
                merged_call["_session_id"] = session_id
            service_name = str(args.get("service_name") or "").strip()
            if not service_name and mcp_tool_name in {"ask-codex", "brainstorm", "help", "ping"}:
                service_name = "codex-cli"
            if service_name:
                merged_call["service_name"] = service_name

            arg_payload = args.get("arguments") or {}
            if not isinstance(arg_payload, dict):
                validation_errors.append(f"mcp_call.arguments 必须是对象: id={call_id}")
                continue
            if mcp_tool_name == "ask-codex":
                prompt = arg_payload.get("prompt")
                if (
                    (prompt is None or prompt == "")
                    and isinstance(args.get("prompt"), str)
                    and args.get("prompt", "").strip()
                ):
                    arg_payload["prompt"] = args.get("prompt", "")
                    prompt = arg_payload["prompt"]
                if (prompt is None or prompt == "") and isinstance(arg_payload.get("message"), str):
                    msg = arg_payload.get("message", "").strip()
                    if msg:
                        arg_payload["prompt"] = msg
                        prompt = msg
                if (prompt is None or prompt == "") and isinstance(args.get("message"), str):
                    top_msg = args.get("message", "").strip()
                    if top_msg:
                        arg_payload["prompt"] = top_msg
                        prompt = top_msg
                arg_payload.pop("message", None)
                if prompt is None or str(prompt).strip() == "":
                    validation_errors.append(f"mcp_call ask-codex 缺少 prompt/message: id={call_id}")
                    continue
                arg_payload.setdefault("sandboxMode", "workspace-write")
                arg_payload.setdefault("approvalPolicy", "on-failure")
            merged_call.update(arg_payload)
            actionable_calls.append(merged_call)
            continue

        if tool_name == "live2d_action":
            action = str(args.get("action") or "").strip()
            if not action:
                validation_errors.append(f"live2d_action 缺少 action: id={call_id}")
                continue
            live2d_calls.append({
                "agentType": "live2d",
                "action": action,
                "_tool_call_id": call_id,
                "_trace_id": trace_id,
            })
            continue

        validation_errors.append(f"未知函数调用: id={call_id}, name={tool_name}")

    return actionable_calls, live2d_calls, validation_errors


def _build_validation_results(errors: List[str]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for msg in errors:
        results.append(
            {
                "tool_call": {"agentType": "tool_protocol"},
                "result": msg,
                "status": "error",
                "service_name": "tool_protocol",
                "tool_name": "validation",
            }
        )
    return results


# ---------------------------------------------------------------------------
# SSE 辅助
# ---------------------------------------------------------------------------


def _format_sse_event(event_type: str, data: Any) -> str:
    """格式化扩展SSE事件（使用与llm_service相同的base64编码格式）"""
    payload = {"type": event_type}
    if isinstance(data, dict):
        payload.update(data)
    else:
        payload["data"] = data
    b64 = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
    return f"data: {b64}\n\n"


def _build_summary_instruction(runtime: AgenticLoopRuntimeState, max_rounds: int) -> str:
    reason = runtime.stop_reason or "unknown"
    return (
        "[系统提示] 工具调用循环已结束。请基于已有工具结果直接回答用户问题。\n"
        f"- 结束原因: {reason}\n"
        f"- 已执行轮次: {runtime.round_num}/{max_rounds}\n"
        f"- 工具调用总数: {runtime.total_tool_calls}\n"
        f"- 工具成功/失败: {runtime.total_tool_success}/{runtime.total_tool_errors}\n"
        f"- GC防抖计数(命中/错误/成功): "
        f"{runtime.gc_guard_hit_total}/{runtime.gc_guard_error_total}/{runtime.gc_guard_success_total}\n"
        "若关键工具全部失败，请诚实告知当前限制并给出下一步可执行方案。\n"
        "不要再发起任何工具调用。"
    )


# ---------------------------------------------------------------------------
# Agentic Loop 核心
# ---------------------------------------------------------------------------


async def run_agentic_loop(
    messages: List[Dict[str, Any]],
    session_id: str,
    max_rounds: int = 500,
    model_override: Optional[Dict[str, str]] = None,
) -> AsyncGenerator[str, None]:
    """Agentic tool loop 核心（原生结构化 tool calling + 配置化编排控制）。"""
    from .llm_service import get_llm_service

    llm_service = get_llm_service()
    tool_definitions = get_agentic_tool_definitions()
    policy = _resolve_agentic_loop_policy(max_rounds)
    runtime = AgenticLoopRuntimeState()
    needs_summary = False
    gc_budget_guard: Optional[GCBudgetGuard] = None
    if policy.gc_budget_guard_enabled:
        gc_budget_guard = GCBudgetGuard(
            GCBudgetGuardConfig(
                repeat_threshold=policy.gc_budget_repeat_threshold,
                window_size=policy.gc_budget_window_size,
            )
        )
    latest_user_request = _extract_latest_user_message(messages)
    requires_codex = _looks_like_coding_request(latest_user_request) or requires_codex_for_messages(messages)
    codex_engaged = False

    if requires_codex:
        logger.info("[AgenticLoop] coding request detected, enabling codex-first guard")

    if latest_user_request:
        try:
            episodic_context = build_reinjection_context(
                session_id=session_id,
                query=latest_user_request,
                top_k=3,
            )
            if episodic_context and _inject_ephemeral_system_context(messages, episodic_context):
                logger.info("[AgenticLoop] injected episodic context for session=%s", session_id)
        except Exception as exc:
            logger.warning("[AgenticLoop] episodic reinjection skipped: %s", exc)

    for round_num in range(1, policy.max_rounds + 1):
        runtime.round_num = round_num
        if round_num > 1:
            yield _format_sse_event("round_start", {"round": round_num})
        plan_start_event = _format_workflow_stage_event(round_num, "plan", "start", policy=policy)
        if plan_start_event:
            yield plan_start_event

        complete_text = ""
        complete_reasoning = ""
        structured_tool_calls: List[Dict[str, Any]] = []
        stream_terminal_error = ""
        stream_terminal_error_reason = ""
        end_marker_cutoff: Optional[int] = None
        buffered_round_chunks: List[str] = []

        def _drain_buffered_round_chunks(*, content_cutoff: Optional[int] = None) -> List[str]:
            if not buffered_round_chunks:
                return []
            drained_raw = list(buffered_round_chunks)
            buffered_round_chunks.clear()
            if content_cutoff is None:
                return drained_raw

            cutoff = max(0, int(content_cutoff))
            drained_sanitized: List[str] = []
            content_cursor = 0
            content_closed = False

            for chunk in drained_raw:
                if not chunk.startswith("data: "):
                    drained_sanitized.append(chunk)
                    continue

                try:
                    data_str = chunk[6:].strip()
                    if not data_str or data_str == "[DONE]":
                        drained_sanitized.append(chunk)
                        continue
                    payload = json.loads(base64.b64decode(data_str).decode("utf-8"))
                    chunk_type = payload.get("type", "content")
                    if chunk_type != "content":
                        drained_sanitized.append(chunk)
                        continue

                    chunk_text = payload.get("text", "")
                    if not isinstance(chunk_text, str):
                        chunk_text = str(chunk_text)
                except Exception:
                    drained_sanitized.append(chunk)
                    continue

                if content_closed:
                    content_cursor += len(chunk_text)
                    continue

                remaining = cutoff - content_cursor
                chunk_len = len(chunk_text)
                if remaining <= 0:
                    content_cursor += chunk_len
                    content_closed = True
                    continue

                if chunk_len <= remaining:
                    drained_sanitized.append(chunk)
                    content_cursor += chunk_len
                    continue

                payload["text"] = chunk_text[:remaining]
                b64 = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
                drained_sanitized.append(f"data: {b64}\n\n")
                content_cursor += chunk_len
                content_closed = True

            return drained_sanitized

        round_tool_choice = "required" if requires_codex and not codex_engaged else "auto"

        async for chunk in llm_service.stream_chat_with_context(
            messages,
            get_config().api.temperature,
            model_override=model_override,
            tools=tool_definitions,
            tool_choice=round_tool_choice,
        ):
            should_passthrough_chunk = True
            if chunk.startswith("data: "):
                try:
                    data_str = chunk[6:].strip()
                    if data_str and data_str != "[DONE]":
                        decoded = base64.b64decode(data_str).decode("utf-8")
                        chunk_data = json.loads(decoded)
                        chunk_type = chunk_data.get("type", "content")
                        chunk_payload = chunk_data.get("text", "")

                        if chunk_type == "content":
                            if isinstance(chunk_payload, str):
                                complete_text += chunk_payload
                                if not stream_terminal_error:
                                    detected = _extract_terminal_stream_error_text(complete_text)
                                    if detected:
                                        stream_terminal_error = detected
                                        stream_terminal_error_reason = "llm_stream_error"
                            buffered_round_chunks.append(chunk)
                            should_passthrough_chunk = False
                        elif chunk_type == "reasoning":
                            if isinstance(chunk_payload, str):
                                complete_reasoning += chunk_payload
                            buffered_round_chunks.append(chunk)
                            should_passthrough_chunk = False
                        elif chunk_type == "tool_calls":
                            parsed_calls = _parse_structured_tool_calls_payload(chunk_payload)
                            structured_tool_calls.extend(parsed_calls)
                            # 原生 tool_calls 事件不透传给前端，统一由 loop 生成 tool_calls/tool_results 事件
                            continue
                        elif chunk_type == "auth_expired":
                            stream_terminal_error = (
                                str(chunk_payload).strip() if isinstance(chunk_payload, str) and chunk_payload else "Login expired"
                            )
                            stream_terminal_error_reason = "auth_expired"
                        elif chunk_type == "error":
                            stream_terminal_error = (
                                str(chunk_payload).strip() if isinstance(chunk_payload, str) and chunk_payload else "LLM stream error"
                            )
                            stream_terminal_error_reason = "llm_stream_error"
                except Exception as e:
                    logger.warning(f"[AgenticLoop] 解析流式工具调用失败: {e}")

            if should_passthrough_chunk:
                yield chunk

        logger.debug(
            f"[AgenticLoop] Round {round_num} complete_text ({len(complete_text)} chars): {complete_text[:300]!r}"
        )

        if not stream_terminal_error:
            detected = _extract_terminal_stream_error_text(complete_text)
            if detected:
                stream_terminal_error = detected
                stream_terminal_error_reason = "llm_stream_error"

        marker_span = _find_end_marker_span(complete_text)
        if marker_span:
            end_marker_cutoff = marker_span[0]
            complete_text = complete_text[:end_marker_cutoff]

        if stream_terminal_error:
            for buffered_chunk in _drain_buffered_round_chunks(content_cutoff=end_marker_cutoff):
                yield buffered_chunk
            runtime.stop_reason = stream_terminal_error_reason or "llm_stream_error"
            logger.error(
                "[AgenticLoop] Round %s: 检测到上游流式错误，终止循环: %s",
                round_num,
                stream_terminal_error,
            )
            plan_error_event = _format_workflow_stage_event(
                round_num,
                "plan",
                "error",
                policy=policy,
                reason=runtime.stop_reason,
                details={"error": stream_terminal_error[:500]},
            )
            if plan_error_event:
                yield plan_error_event
            execute_skip_event = _format_workflow_stage_event(
                round_num,
                "execute",
                "skip",
                policy=policy,
                reason=runtime.stop_reason,
            )
            if execute_skip_event:
                yield execute_skip_event
            verify_error_event = _format_workflow_stage_event(
                round_num,
                "verify",
                "error",
                policy=policy,
                reason=runtime.stop_reason,
                decision="stop",
                details={"error": stream_terminal_error[:500]},
            )
            if verify_error_event:
                yield verify_error_event
            yield _format_sse_event("round_end", {"round": round_num, "has_more": False})
            break

        actionable_calls, live2d_calls, validation_errors = _convert_structured_tool_calls(
            structured_tool_calls,
            session_id=session_id,
            trace_id=None,  # 自动生成
        )
        legacy_protocol_error = _detect_legacy_tool_protocol_violation(complete_text, structured_tool_calls)
        if legacy_protocol_error:
            validation_errors.append(legacy_protocol_error)

        actionable_calls, codex_engaged, blocked_mutating_calls = _apply_codex_first_guard(
            actionable_calls,
            requires_codex=requires_codex,
            codex_engaged=codex_engaged,
            latest_user_request=latest_user_request,
            round_num=round_num,
        )
        if requires_codex and blocked_mutating_calls > 0:
            logger.info(
                "[AgenticLoop] round %s blocked %s mutating native call(s) before codex handoff",
                round_num,
                blocked_mutating_calls,
            )

        contract_gate_messages, contract_force_serial = _apply_parallel_contract_gate(actionable_calls)
        if contract_gate_messages:
            for msg in contract_gate_messages:
                logger.warning("[AgenticLoop] round %s %s", round_num, msg)
            yield _format_sse_event(
                "guardrail",
                {
                    "round": round_num,
                    "type": "contract_gate",
                    "force_serial": contract_force_serial,
                    "messages": contract_gate_messages,
                },
            )

        validation_results = _build_validation_results(validation_errors)
        pending_tool_intent = False
        explicit_no_tool_completion = False
        if not actionable_calls and not validation_results:
            pending_tool_intent = _looks_like_pending_tool_intent(complete_text)
            explicit_no_tool_completion = _is_explicit_no_tool_completion(complete_text)

            if requires_codex and not codex_engaged:
                pending_tool_intent = True
                explicit_no_tool_completion = False

        def _build_round_model_output_event(*, fallback_text: str) -> str:
            output_text = complete_text if isinstance(complete_text, str) else str(complete_text)
            placeholder = False
            if not output_text.strip():
                placeholder = True
                output_text = fallback_text
            return _format_sse_event(
                "model_output",
                {
                    "round": round_num,
                    "text": output_text,
                    "placeholder": placeholder,
                    "has_tool_calls": bool(actionable_calls),
                    "validation_errors": len(validation_results),
                },
            )

        if end_marker_cutoff is not None:
            yield _build_round_model_output_event(fallback_text="（检测到结束标记，本轮结束）")
            for buffered_chunk in _drain_buffered_round_chunks(content_cutoff=end_marker_cutoff):
                yield buffered_chunk

            runtime.stop_reason = "end_marker"
            plan_success_event = _format_workflow_stage_event(
                round_num,
                "plan",
                "success",
                policy=policy,
                reason="end_marker",
                details={
                    "actionable_calls": len(actionable_calls),
                    "live2d_calls": len(live2d_calls),
                    "validation_errors": len(validation_results),
                },
            )
            if plan_success_event:
                yield plan_success_event
            execute_skip_event = _format_workflow_stage_event(
                round_num,
                "execute",
                "skip",
                policy=policy,
                reason="end_marker",
            )
            if execute_skip_event:
                yield execute_skip_event
            verify_success_event = _format_workflow_stage_event(
                round_num,
                "verify",
                "success",
                policy=policy,
                reason="end_marker",
                decision="stop",
            )
            if verify_success_event:
                yield verify_success_event
            logger.info(f"[AgenticLoop] Round {round_num}: 检测到 {{End}} 标记，循环结束")
            yield _format_sse_event("round_end", {"round": round_num, "has_more": False})
            break

        if live2d_calls:
            asyncio.create_task(_send_live2d_actions(live2d_calls, session_id))

        if actionable_calls:
            yield _build_round_model_output_event(fallback_text="（本轮模型未返回正文，直接发起工具调用）")
            for buffered_chunk in _drain_buffered_round_chunks():
                yield buffered_chunk
            plan_success_event = _format_workflow_stage_event(
                round_num,
                "plan",
                "success",
                policy=policy,
                details={
                    "actionable_calls": len(actionable_calls),
                    "live2d_calls": len(live2d_calls),
                    "validation_errors": len(validation_results),
                },
            )
            if plan_success_event:
                yield plan_success_event
        elif validation_results:
            yield _build_round_model_output_event(fallback_text="（本轮模型未返回正文，且工具调用参数/协议校验失败）")
            plan_error_event = _format_workflow_stage_event(
                round_num,
                "plan",
                "error",
                policy=policy,
                reason="validation_errors",
                details={"validation_errors": len(validation_results)},
            )
            if plan_error_event:
                yield plan_error_event
        else:
            if explicit_no_tool_completion:
                no_action_reason = "explicit_no_tool_completion"
            elif pending_tool_intent:
                no_action_reason = "pending_tool_intent"
            else:
                no_action_reason = "no_actionable_calls"
            plan_no_action_event = _format_workflow_stage_event(
                round_num,
                "plan",
                "success",
                policy=policy,
                reason=no_action_reason,
                details={
                    "actionable_calls": 0,
                    "live2d_calls": len(live2d_calls),
                    "validation_errors": 0,
                },
            )
            if plan_no_action_event:
                yield plan_no_action_event

        if not actionable_calls:
            execute_skip_event = _format_workflow_stage_event(
                round_num,
                "execute",
                "skip",
                policy=policy,
                reason="no_actionable_calls",
                details={"validation_errors": len(validation_results)},
            )
            if execute_skip_event:
                yield execute_skip_event

            verify_start_event = _format_workflow_stage_event(
                round_num,
                "verify",
                "start",
                policy=policy,
                reason="no_actionable_calls",
            )
            if verify_start_event:
                yield verify_start_event

            if validation_results:
                for buffered_chunk in _drain_buffered_round_chunks():
                    yield buffered_chunk
                runtime.consecutive_validation_failures += 1
                runtime.consecutive_no_tool_rounds = 0
                logger.warning(
                    f"[AgenticLoop] Round {round_num}: 工具参数/协议校验失败 {len(validation_results)} 条 "
                    f"(连续 {runtime.consecutive_validation_failures} 轮)"
                )

                validation_summaries = _summarize_results_for_frontend(
                    validation_results, policy.tool_result_preview_chars
                )
                yield _format_sse_event("tool_results", {"results": validation_summaries})

                assistant_content = complete_text if complete_text else "(工具调用参数错误)"
                repair_start_event = _format_workflow_stage_event(
                    round_num,
                    "repair",
                    "start",
                    policy=policy,
                    reason="validation_errors",
                    details={"validation_errors": len(validation_results)},
                )
                if repair_start_event:
                    yield repair_start_event
                messages.append({"role": "assistant", "content": assistant_content})
                messages.append({"role": "user", "content": format_tool_results_for_llm(validation_results)})
                repair_success_event = _format_workflow_stage_event(
                    round_num,
                    "repair",
                    "success",
                    policy=policy,
                    reason="validation_feedback_injected",
                    details={"validation_errors": len(validation_results)},
                )
                if repair_success_event:
                    yield repair_success_event

                if runtime.consecutive_validation_failures >= policy.max_consecutive_validation_failures:
                    runtime.stop_reason = "validation_failures"
                    logger.warning("[AgenticLoop] 连续工具参数/协议错误达到阈值")
                    verify_error_event = _format_workflow_stage_event(
                        round_num,
                        "verify",
                        "error",
                        policy=policy,
                        reason="validation_failures",
                        decision="summary" if policy.enable_summary_round else "stop",
                        details={
                            "consecutive_validation_failures": runtime.consecutive_validation_failures,
                            "threshold": policy.max_consecutive_validation_failures,
                        },
                    )
                    if verify_error_event:
                        yield verify_error_event
                    if policy.enable_summary_round:
                        needs_summary = True
                        yield _format_sse_event("round_end", {"round": round_num, "has_more": True})
                    else:
                        yield _format_sse_event("round_end", {"round": round_num, "has_more": False})
                    break

                if round_num < policy.max_rounds:
                    verify_success_event = _format_workflow_stage_event(
                        round_num,
                        "verify",
                        "success",
                        policy=policy,
                        decision="continue",
                        reason="validation_retry",
                        details={"consecutive_validation_failures": runtime.consecutive_validation_failures},
                    )
                    if verify_success_event:
                        yield verify_success_event
                    yield _format_sse_event("round_end", {"round": round_num, "has_more": True})
                else:
                    runtime.stop_reason = "validation_failures"
                    verify_error_event = _format_workflow_stage_event(
                        round_num,
                        "verify",
                        "error",
                        policy=policy,
                        reason="validation_failures_max_rounds",
                        decision="summary" if policy.enable_summary_round else "stop",
                    )
                    if verify_error_event:
                        yield verify_error_event
                    if policy.enable_summary_round:
                        needs_summary = True
                        yield _format_sse_event("round_end", {"round": round_num, "has_more": True})
                    else:
                        yield _format_sse_event("round_end", {"round": round_num, "has_more": False})
                    break
                continue

            runtime.consecutive_validation_failures = 0
            runtime.consecutive_no_tool_rounds += 1
            if explicit_no_tool_completion:
                yield _build_round_model_output_event(fallback_text="（本轮模型未返回正文，但声明无需继续工具）")
                for buffered_chunk in _drain_buffered_round_chunks():
                    yield buffered_chunk
                runtime.stop_reason = "explicit_no_tool_completion"
                verify_success_event = _format_workflow_stage_event(
                    round_num,
                    "verify",
                    "success",
                    policy=policy,
                    reason="explicit_no_tool_completion",
                    decision="stop",
                )
                if verify_success_event:
                    yield verify_success_event
                logger.info(f"[AgenticLoop] Round {round_num}: 模型明确返回“不需要工具”，循环结束")
                yield _format_sse_event("round_end", {"round": round_num, "has_more": False})
                break

            codex_retry_required = requires_codex and not codex_engaged
            should_retry_no_tool = (
                (codex_retry_required or pending_tool_intent or policy.inject_no_tool_feedback)
                and runtime.consecutive_no_tool_rounds < policy.max_consecutive_no_tool_rounds
                and round_num < policy.max_rounds
            )
            if should_retry_no_tool:
                logger.info(
                    f"[AgenticLoop] Round {round_num}: 无工具调用，注入纠偏反馈后继续下一轮 "
                    f"(连续无工具 {runtime.consecutive_no_tool_rounds}/{policy.max_consecutive_no_tool_rounds})"
                )
                assistant_content = complete_text if complete_text else "(本轮未发起工具调用)"
                repair_start_event = _format_workflow_stage_event(
                    round_num,
                    "repair",
                    "start",
                    policy=policy,
                    reason="no_tool_retry",
                    details={
                        "consecutive_no_tool_rounds": runtime.consecutive_no_tool_rounds,
                        "threshold": policy.max_consecutive_no_tool_rounds,
                    },
                )
                if repair_start_event:
                    yield repair_start_event
                if codex_retry_required:
                    feedback_text = (
                        "[系统反馈] 当前请求属于代码开发任务，必须先调用 Codex MCP 工具。"
                        "请直接发起 mcp_call，参数示例："
                        "service_name='codex-cli', tool_name='ask-codex', "
                        "arguments={'prompt':'<实现任务>', 'sandboxMode':'workspace-write', 'approvalPolicy':'on-failure'}。"
                        "不要直接输出最终答案。"
                    )
                elif pending_tool_intent:
                    feedback_text = (
                        "[系统反馈] 你上一轮表示将使用工具，但没有实际发起函数调用。"
                        "请立即调用合适函数继续执行；只有在无需任何工具且任务已完成时才直接给最终答案，"
                        "并在回答中显式包含“不需要工具”。"
                    )
                else:
                    feedback_text = (
                        "[系统反馈] 你上一轮没有发起任何工具调用。"
                        "如果任务仍需要外部信息、文件操作、命令执行或网络能力，请立即调用合适函数并继续执行。"
                        "只有在无需任何工具且任务已完成时才直接给最终答案，并在回答中显式包含“不需要工具”。"
                    )
                messages.append({"role": "assistant", "content": assistant_content})
                messages.append(
                    {
                        "role": "user",
                        "content": feedback_text,
                    }
                )
                repair_success_event = _format_workflow_stage_event(
                    round_num,
                    "repair",
                    "success",
                    policy=policy,
                    reason="no_tool_feedback_injected",
                    details={"pending_tool_intent": bool(pending_tool_intent)},
                )
                if repair_success_event:
                    yield repair_success_event
                verify_success_event = _format_workflow_stage_event(
                    round_num,
                    "verify",
                    "success",
                    policy=policy,
                    decision="continue",
                    reason="no_tool_retry",
                    details={
                        "consecutive_no_tool_rounds": runtime.consecutive_no_tool_rounds,
                        "threshold": policy.max_consecutive_no_tool_rounds,
                    },
                )
                if verify_success_event:
                    yield verify_success_event
                yield _format_sse_event("round_end", {"round": round_num, "has_more": True})
                continue

            yield _build_round_model_output_event(fallback_text="（本轮模型未返回正文）")
            for buffered_chunk in _drain_buffered_round_chunks():
                yield buffered_chunk
            runtime.stop_reason = "no_tool_calls"
            verify_success_event = _format_workflow_stage_event(
                round_num,
                "verify",
                "success",
                policy=policy,
                reason="no_tool_calls",
                decision="stop",
            )
            if verify_success_event:
                yield verify_success_event
            logger.info(f"[AgenticLoop] Round {round_num}: 无工具调用，循环结束")
            yield _format_sse_event("round_end", {"round": round_num, "has_more": False})
            break

        runtime.consecutive_validation_failures = 0
        runtime.consecutive_no_tool_rounds = 0
        logger.info(f"[AgenticLoop] Round {round_num}: 检测到 {len(actionable_calls)} 个工具调用")
        execute_start_event = _format_workflow_stage_event(
            round_num,
            "execute",
            "start",
            policy=policy,
            details={"actionable_calls": len(actionable_calls)},
        )
        if execute_start_event:
            yield execute_start_event

        call_descriptions = []
        for tc in actionable_calls:
            desc = {"agentType": tc.get("agentType", "")}
            if tc.get("service_name"):
                desc["service_name"] = tc["service_name"]
            if tc.get("tool_name"):
                desc["tool_name"] = tc["tool_name"]
            if tc.get("message"):
                desc["message"] = str(tc["message"])[:100]
            call_descriptions.append(desc)
        yield _format_sse_event("tool_calls", {"calls": call_descriptions})

        primary_results = await execute_tool_calls(
            actionable_calls,
            session_id,
            max_parallel_calls=policy.max_parallel_tool_calls,
            retry_failed=policy.retry_failed_tool_calls,
            max_retries=policy.max_tool_retries,
            retry_backoff_seconds=policy.retry_backoff_seconds,
        )
        followup_results = await _maybe_execute_gc_reader_followup(primary_results, session_id, round_num=round_num)
        executed_results = primary_results + followup_results

        try:
            archived_records = archive_tool_results_for_session(session_id, executed_results)
            if archived_records:
                logger.debug(
                    "[AgenticLoop] archived %s episodic record(s) in round %s",
                    len(archived_records),
                    round_num,
                )
                try:
                    updated_edges = update_semantic_graph_from_records(session_id, archived_records)
                    logger.debug(
                        "[AgenticLoop] semantic graph updated with %s edge mutation(s) in round %s",
                        updated_edges,
                        round_num,
                    )
                except Exception as exc:
                    logger.warning("[AgenticLoop] semantic graph update skipped in round %s: %s", round_num, exc)
        except Exception as exc:
            logger.warning("[AgenticLoop] episodic archive skipped in round %s: %s", round_num, exc)

        results = validation_results + executed_results
        gc_guard_signal = gc_budget_guard.observe_round(executed_results) if gc_budget_guard is not None else None
        gc_guard_snapshot = gc_budget_guard.snapshot() if gc_budget_guard is not None else {}
        runtime.gc_guard_repeat_count = _clamp_int(gc_guard_snapshot.get("repeat_count", 0), 0, 0, 9999)
        runtime.gc_guard_error_total = _clamp_int(gc_guard_snapshot.get("gc_error_total", 0), 0, 0, 999999)
        runtime.gc_guard_success_total = _clamp_int(gc_guard_snapshot.get("gc_success_total", 0), 0, 0, 999999)
        runtime.gc_guard_hit_total = _clamp_int(gc_guard_snapshot.get("gc_guard_hits", 0), 0, 0, 999999)

        runtime.total_tool_calls += len(actionable_calls)
        success_count = sum(1 for r in primary_results if r.get("status") == "success")
        error_count = sum(1 for r in primary_results if r.get("status") == "error")
        runtime.total_tool_success += success_count
        runtime.total_tool_errors += error_count

        all_failed = bool(primary_results) and success_count == 0
        if all_failed:
            runtime.consecutive_tool_failures += 1
            logger.warning(
                f"[AgenticLoop] Round {round_num}: 本轮所有可执行工具调用失败 "
                f"(连续 {runtime.consecutive_tool_failures} 轮)"
            )
        else:
            runtime.consecutive_tool_failures = 0
        execute_final_status = "error" if all_failed else "success"
        execute_finish_event = _format_workflow_stage_event(
            round_num,
            "execute",
            execute_final_status,
            policy=policy,
            details={
                "actionable_calls": len(actionable_calls),
                "auto_followup_calls": len(followup_results),
                "success_count": success_count,
                "error_count": error_count,
                "gc_guard_repeat_count": runtime.gc_guard_repeat_count,
                "gc_guard_error_total": runtime.gc_guard_error_total,
                "gc_guard_success_total": runtime.gc_guard_success_total,
                "gc_guard_hit_total": runtime.gc_guard_hit_total,
            },
        )
        if execute_finish_event:
            yield execute_finish_event
        if gc_guard_signal and gc_guard_signal.guard_hit:
            yield _format_sse_event(
                "guardrail",
                {
                    "guard_type": "gc_budget_guard",
                    "round": round_num,
                    **gc_guard_signal.to_payload(),
                },
            )

        result_summaries = _summarize_results_for_frontend(results, policy.tool_result_preview_chars)
        yield _format_sse_event("tool_results", {"results": result_summaries})

        assistant_content = complete_text if complete_text else "(工具调用中)"
        messages.append({"role": "assistant", "content": assistant_content})
        messages.append({"role": "user", "content": format_tool_results_for_llm(results)})
        verify_start_event = _format_workflow_stage_event(
            round_num,
            "verify",
            "start",
            policy=policy,
            reason="post_execute",
            details={
                "consecutive_tool_failures": runtime.consecutive_tool_failures,
                "gc_guard_repeat_count": runtime.gc_guard_repeat_count,
                "gc_guard_hit_total": runtime.gc_guard_hit_total,
            },
        )
        if verify_start_event:
            yield verify_start_event

        arbiter_escalation = next(
            (
                r.get("router_arbiter")
                for r in executed_results
                if isinstance(r.get("router_arbiter"), dict) and bool(r["router_arbiter"].get("escalated"))
            ),
            None,
        )
        if isinstance(arbiter_escalation, dict):
            runtime.stop_reason = "router_arbiter_escalation"
            logger.warning(
                "[AgenticLoop] Router arbiter escalation triggered in round %s, conflict_ticket=%s, delegate_turns=%s",
                round_num,
                arbiter_escalation.get("conflict_ticket", ""),
                arbiter_escalation.get("delegate_turns", 0),
            )
            verify_error_event = _format_workflow_stage_event(
                round_num,
                "verify",
                "error",
                policy=policy,
                reason="router_arbiter_escalation",
                decision="summary" if policy.enable_summary_round else "stop",
                details=arbiter_escalation,
            )
            if verify_error_event:
                yield verify_error_event
            if policy.enable_summary_round:
                needs_summary = True
                yield _format_sse_event("round_end", {"round": round_num, "has_more": True})
            else:
                yield _format_sse_event("round_end", {"round": round_num, "has_more": False})
            break

        if gc_guard_signal and gc_guard_signal.guard_hit:
            runtime.stop_reason = gc_guard_signal.stop_reason or "gc_budget_guard_hit"
            logger.warning(
                "[AgenticLoop] GC budget guard hit in round %s: fingerprint=%s repeat=%s threshold=%s artifact_ref=%s",
                round_num,
                gc_guard_signal.fingerprint,
                gc_guard_signal.repeat_count,
                gc_guard_signal.threshold,
                gc_guard_signal.artifact_ref or "<none>",
            )
            verify_error_event = _format_workflow_stage_event(
                round_num,
                "verify",
                "error",
                policy=policy,
                reason=runtime.stop_reason,
                decision="summary" if policy.enable_summary_round else "stop",
                details=gc_guard_signal.to_payload(),
            )
            if verify_error_event:
                yield verify_error_event
            if policy.enable_summary_round:
                needs_summary = True
                yield _format_sse_event("round_end", {"round": round_num, "has_more": True})
            else:
                yield _format_sse_event("round_end", {"round": round_num, "has_more": False})
            break

        if runtime.consecutive_tool_failures >= policy.max_consecutive_tool_failures:
            runtime.stop_reason = "tool_failures"
            logger.warning(
                f"[AgenticLoop] 连续 {runtime.consecutive_tool_failures} 轮工具全部失败，触发循环停止策略"
            )
            verify_error_event = _format_workflow_stage_event(
                round_num,
                "verify",
                "error",
                policy=policy,
                reason="tool_failures",
                decision="summary" if policy.enable_summary_round else "stop",
                details={
                    "consecutive_tool_failures": runtime.consecutive_tool_failures,
                    "threshold": policy.max_consecutive_tool_failures,
                },
            )
            if verify_error_event:
                yield verify_error_event
            if policy.enable_summary_round:
                needs_summary = True
                yield _format_sse_event("round_end", {"round": round_num, "has_more": True})
            else:
                yield _format_sse_event("round_end", {"round": round_num, "has_more": False})
            break

        verify_success_event = _format_workflow_stage_event(
            round_num,
            "verify",
            "success",
            policy=policy,
            reason="post_execute",
            decision="continue",
            details={"consecutive_tool_failures": runtime.consecutive_tool_failures},
        )
        if verify_success_event:
            yield verify_success_event
        yield _format_sse_event("round_end", {"round": round_num, "has_more": True})
        logger.info(f"[AgenticLoop] Round {round_num}: 工具结果已注入，继续下一轮")
    else:
        runtime.stop_reason = "max_rounds_exhausted"
        needs_summary = policy.enable_summary_round

    if needs_summary and policy.enable_summary_round:
        summary_round = runtime.round_num + 1 if runtime.round_num > 0 else policy.max_rounds + 1
        logger.warning(f"[AgenticLoop] 执行最终总结轮, reason={runtime.stop_reason}")
        yield _format_sse_event("round_start", {"round": summary_round, "summary": True, "reason": runtime.stop_reason})
        plan_start_event = _format_workflow_stage_event(
            summary_round,
            "plan",
            "start",
            policy=policy,
            reason="summary_round",
        )
        if plan_start_event:
            yield plan_start_event
        messages.append({"role": "user", "content": _build_summary_instruction(runtime, policy.max_rounds)})
        plan_success_event = _format_workflow_stage_event(
            summary_round,
            "plan",
            "success",
            policy=policy,
            reason="summary_round",
            details={"actionable_calls": 0},
        )
        if plan_success_event:
            yield plan_success_event
        execute_skip_event = _format_workflow_stage_event(
            summary_round,
            "execute",
            "skip",
            policy=policy,
            reason="summary_round",
        )
        if execute_skip_event:
            yield execute_skip_event
        verify_start_event = _format_workflow_stage_event(
            summary_round,
            "verify",
            "start",
            policy=policy,
            reason="summary_round",
        )
        if verify_start_event:
            yield verify_start_event

        async for chunk in llm_service.stream_chat_with_context(
            messages,
            get_config().api.temperature,
            model_override=model_override,
            tools=tool_definitions,
            tool_choice="none",
        ):
            if chunk.startswith("data: "):
                try:
                    data_str = chunk[6:].strip()
                    if data_str and data_str != "[DONE]":
                        decoded = base64.b64decode(data_str).decode("utf-8")
                        payload = json.loads(decoded)
                        if payload.get("type") == "tool_calls":
                            # 总结轮不接收工具调用事件
                            continue
                except Exception:
                    pass
            yield chunk

        verify_success_event = _format_workflow_stage_event(
            summary_round,
            "verify",
            "success",
            policy=policy,
            reason="summary_round",
            decision="stop",
        )
        if verify_success_event:
            yield verify_success_event
        yield _format_sse_event("round_end", {"round": summary_round, "has_more": False})
