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
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from system.config import get_config, get_server_port
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
    )


def _is_retryable_tool_failure(call: Dict[str, Any], result: Dict[str, Any]) -> bool:
    if bool(call.get("no_retry", False)):
        return False

    agent_type = str(call.get("agentType") or "").strip()
    if agent_type == "openclaw" and str(call.get("task_type") or "message") != "message":
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


# ---------------------------------------------------------------------------
# 工具执行
# ---------------------------------------------------------------------------


async def _execute_mcp_call(call: Dict[str, Any]) -> Dict[str, Any]:
    """执行单个MCP调用"""
    service_name = call.get("service_name", "")
    tool_name = call.get("tool_name", "")

    if not service_name and tool_name in {
        "ask_guide",
        "ask_guide_with_screenshot",
        "calculate_damage",
        "get_team_recommendation",
    }:
        service_name = "game_guide"
        call["service_name"] = service_name

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
        return {
            "tool_call": call,
            "result": result,
            "status": "success",
            "service_name": service_name,
            "tool_name": tool_name,
        }
    except Exception as e:
        logger.error(f"[AgenticLoop] MCP调用失败: service={service_name}, error={e}")
        return {
            "tool_call": call,
            "result": f"调用失败: {e}",
            "status": "error",
            "service_name": service_name,
            "tool_name": tool_name,
        }


async def _execute_openclaw_call(call: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    """执行单个OpenClaw调用"""
    import httpx

    native_executor = get_native_tool_executor()
    intercepted_call = native_executor.maybe_intercept_openclaw_call(call, session_id=session_id)
    if intercepted_call:
        logger.info(
            "[AgenticLoop] local-first拦截OpenClaw调用，改为native执行: %s",
            intercepted_call.get("tool_name", "unknown"),
        )
        result = await native_executor.execute(intercepted_call, session_id=session_id)
        # 保留原始调用，便于诊断
        result["tool_call"] = call
        result["service_name"] = "native"
        return result

    message = call.get("message", "")
    task_type = call.get("task_type", "message")

    if not message:
        return {
            "tool_call": call,
            "result": "缺少message字段",
            "status": "error",
            "service_name": "openclaw",
            "tool_name": task_type,
        }

    payload = {
        "message": message,
        "session_key": call.get("session_key", f"naga_{session_id}"),
        "name": "Naga",
        "wake_mode": "now",
        "timeout_seconds": 1200,
    }

    if task_type == "cron" and call.get("schedule"):
        payload["message"] = f"[定时任务 cron: {call.get('schedule')}] {message}"
    elif task_type == "reminder" and call.get("at"):
        payload["message"] = f"[提醒 在 {call.get('at')} 后] {message}"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout=150.0, connect=10.0)) as client:
            response = await client.post(
                f"http://localhost:{get_server_port('agent_server')}/openclaw/send",
                json=payload,
            )
            if response.status_code == 200:
                result_data = response.json()
                # 先检查 agent_server 返回的 success 标记
                if not result_data.get("success", True):
                    error_msg = result_data.get("error") or "OpenClaw任务执行失败"
                    return {
                        "tool_call": call,
                        "result": f"联网搜索失败: {error_msg}",
                        "status": "error",
                        "service_name": "openclaw",
                        "tool_name": task_type,
                    }
                # agent_server 返回两个字段：replies(列表，异步轮询时填充) 和 reply(字符串，同步完成时填充)
                replies = result_data.get("replies") or []
                if replies:
                    combined = "\n".join(replies)
                elif result_data.get("reply"):
                    combined = result_data["reply"]
                else:
                    combined = "任务已提交，暂无返回结果"
                return {
                    "tool_call": call,
                    "result": combined,
                    "status": "success",
                    "service_name": "openclaw",
                    "tool_name": task_type,
                }
            else:
                return {
                    "tool_call": call,
                    "result": f"HTTP {response.status_code}: {response.text[:200]}",
                    "status": "error",
                    "service_name": "openclaw",
                    "tool_name": task_type,
                }
    except Exception as e:
        logger.error(f"[AgenticLoop] OpenClaw调用失败: {e}")
        return {
            "tool_call": call,
            "result": f"调用失败: {e}",
            "status": "error",
            "service_name": "openclaw",
            "tool_name": task_type,
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
    if agent_type == "openclaw":
        return await _execute_openclaw_call(call, session_id)

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
    for attempt in range(1, max_attempts + 1):
        try:
            async with semaphore:
                result = await _execute_single_tool_call(call, session_id)
        except Exception as e:
            result = {
                "tool_call": call,
                "result": f"执行异常: {e}",
                "status": "error",
                "service_name": "unknown",
                "tool_name": "unknown",
            }

        if result.get("status") != "error":
            if attempt > 1:
                result["retry_attempts"] = attempt - 1
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

    parallel_limit = _clamp_int(max_parallel_calls, 8, 1, 64)
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


# ---------------------------------------------------------------------------
# 格式化
# ---------------------------------------------------------------------------


def format_tool_results_for_llm(results: List[Dict[str, Any]]) -> str:
    """将工具执行结果格式化为LLM可理解的文本"""
    parts = []
    total = len(results)
    for idx, r in enumerate(results, 1):
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
                            ],
                        },
                        "path": {"type": "string"},
                        "file_path": {"type": "string"},
                        "content": {"type": "string"},
                        "mode": {"type": "string", "enum": ["overwrite", "append"]},
                        "encoding": {"type": "string"},
                        "command": {"type": "string"},
                        "cmd": {"type": "string"},
                        "cwd": {"type": "string"},
                        "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 1200},
                        "keyword": {"type": "string"},
                        "query": {"type": "string"},
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
                        "max_chars": {"type": "integer", "minimum": 200, "maximum": 100000},
                        "max_output_chars": {"type": "integer", "minimum": 200, "maximum": 500000},
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
                "name": "openclaw_call",
                "description": "Invoke OpenClaw for web/browser/cross-app tasks.",
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "task_type": {"type": "string", "enum": ["message", "cron", "reminder"]},
                        "message": {"type": "string"},
                        "session_key": {"type": "string"},
                        "schedule": {"type": "string"},
                        "at": {"type": "string"},
                    },
                    "required": ["message"],
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
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    actionable_calls: List[Dict[str, Any]] = []
    live2d_calls: List[Dict[str, Any]] = []
    validation_errors: List[str] = []

    for idx, call in enumerate(structured_calls, 1):
        call_id = str(call.get("id") or f"tool_call_{idx}")
        tool_name = str(call.get("name") or "").strip()
        parse_error = call.get("parse_error")
        args = call.get("arguments")

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
            native_call = {"agentType": "native", **args, "_tool_call_id": call_id}
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
            }
            service_name = str(args.get("service_name") or "").strip()
            if service_name:
                merged_call["service_name"] = service_name

            arg_payload = args.get("arguments") or {}
            if not isinstance(arg_payload, dict):
                validation_errors.append(f"mcp_call.arguments 必须是对象: id={call_id}")
                continue
            merged_call.update(arg_payload)
            actionable_calls.append(merged_call)
            continue

        if tool_name == "openclaw_call":
            message = str(args.get("message") or "").strip()
            if not message:
                validation_errors.append(f"openclaw_call 缺少 message: id={call_id}")
                continue
            openclaw_call = {
                "agentType": "openclaw",
                "task_type": str(args.get("task_type") or "message"),
                "message": message,
                "_tool_call_id": call_id,
            }
            if args.get("session_key"):
                openclaw_call["session_key"] = args["session_key"]
            if args.get("schedule"):
                openclaw_call["schedule"] = args["schedule"]
            if args.get("at"):
                openclaw_call["at"] = args["at"]
            actionable_calls.append(openclaw_call)
            continue

        if tool_name == "live2d_action":
            action = str(args.get("action") or "").strip()
            if not action:
                validation_errors.append(f"live2d_action 缺少 action: id={call_id}")
                continue
            live2d_calls.append({"agentType": "live2d", "action": action, "_tool_call_id": call_id})
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

        async for chunk in llm_service.stream_chat_with_context(
            messages,
            get_config().api.temperature,
            model_override=model_override,
            tools=tool_definitions,
            tool_choice="auto",
        ):
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
                        elif chunk_type == "reasoning":
                            if isinstance(chunk_payload, str):
                                complete_reasoning += chunk_payload
                        elif chunk_type == "tool_calls":
                            parsed_calls = _parse_structured_tool_calls_payload(chunk_payload)
                            structured_tool_calls.extend(parsed_calls)
                            # 原生 tool_calls 事件不透传给前端，统一由 loop 生成 tool_calls/tool_results 事件
                            continue
                except Exception as e:
                    logger.warning(f"[AgenticLoop] 解析流式工具调用失败: {e}")

            yield chunk

        logger.debug(
            f"[AgenticLoop] Round {round_num} complete_text ({len(complete_text)} chars): {complete_text[:300]!r}"
        )

        actionable_calls, live2d_calls, validation_errors = _convert_structured_tool_calls(structured_tool_calls)
        legacy_protocol_error = _detect_legacy_tool_protocol_violation(complete_text, structured_tool_calls)
        if legacy_protocol_error:
            validation_errors.append(legacy_protocol_error)
        validation_results = _build_validation_results(validation_errors)

        if live2d_calls:
            asyncio.create_task(_send_live2d_actions(live2d_calls, session_id))

        if actionable_calls:
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
            no_action_reason = "pending_tool_intent" if _looks_like_pending_tool_intent(complete_text) else "no_actionable_calls"
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
            pending_tool_intent = _looks_like_pending_tool_intent(complete_text)

            should_retry_no_tool = (
                (pending_tool_intent or policy.inject_no_tool_feedback)
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
                if pending_tool_intent:
                    feedback_text = (
                        "[系统反馈] 你上一轮表示将使用工具，但没有实际发起函数调用。"
                        "请立即调用合适函数继续执行；只有在无需任何工具时才直接给最终答案。"
                    )
                else:
                    feedback_text = (
                        "[系统反馈] 你上一轮没有发起任何工具调用。"
                        "如果任务仍需要外部信息、文件操作、命令执行或网络能力，请立即调用合适函数并继续执行。"
                        "只有在无需任何工具时才直接给最终答案。"
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

        executed_results = await execute_tool_calls(
            actionable_calls,
            session_id,
            max_parallel_calls=policy.max_parallel_tool_calls,
            retry_failed=policy.retry_failed_tool_calls,
            max_retries=policy.max_tool_retries,
            retry_backoff_seconds=policy.retry_backoff_seconds,
        )
        results = validation_results + executed_results

        runtime.total_tool_calls += len(actionable_calls)
        success_count = sum(1 for r in executed_results if r.get("status") == "success")
        error_count = sum(1 for r in executed_results if r.get("status") == "error")
        runtime.total_tool_success += success_count
        runtime.total_tool_errors += error_count

        all_failed = bool(executed_results) and success_count == 0
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
                "success_count": success_count,
                "error_count": error_count,
            },
        )
        if execute_finish_event:
            yield execute_finish_event

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
            details={"consecutive_tool_failures": runtime.consecutive_tool_failures},
        )
        if verify_start_event:
            yield verify_start_event

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
