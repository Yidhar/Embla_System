#!/usr/bin/env python3
"""
Agentic Tool Loop 核心引擎
实现单LLM agentic loop：模型在对话中发起工具调用，接收结果，再继续推理，直到不再需要工具。
"""

import asyncio
import base64
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from system.config import get_config, get_server_port
from .native_tools import get_native_tool_executor

logger = logging.getLogger(__name__)

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


async def execute_tool_calls(tool_calls: List[Dict[str, Any]], session_id: str) -> List[Dict[str, Any]]:
    """按 agentType 分组并行执行工具调用（不包含 live2d）。

    Returns:
        [{"tool_call": {...}, "result": "...", "status": "success|error", "service_name": "...", "tool_name": "..."}]
    """
    tasks = []
    for call in tool_calls:
        agent_type = call.get("agentType", "")
        if agent_type == "mcp":
            tasks.append(_execute_mcp_call(call))
        elif agent_type == "native":
            tasks.append(_execute_native_call(call, session_id))
        elif agent_type == "openclaw":
            tasks.append(_execute_openclaw_call(call, session_id))
        else:
            logger.warning(f"[AgenticLoop] 未知agentType: {agent_type}, 跳过: {call}")

    if not tasks:
        return []

    results = await asyncio.gather(*tasks, return_exceptions=True)
    final = []
    for r in results:
        if isinstance(r, Exception):
            final.append(
                {
                    "tool_call": {},
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
                                "run_cmd",
                                "search_keyword",
                                "query_docs",
                                "list_files",
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
                        "glob": {"type": "string"},
                        "case_sensitive": {"type": "boolean"},
                        "max_results": {"type": "integer", "minimum": 1, "maximum": 1000},
                        "max_file_size_kb": {"type": "integer", "minimum": 64, "maximum": 4096},
                        "start_line": {"type": "integer", "minimum": 1},
                        "end_line": {"type": "integer", "minimum": 1},
                        "max_chars": {"type": "integer", "minimum": 200, "maximum": 100000},
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


# ---------------------------------------------------------------------------
# Agentic Loop 核心
# ---------------------------------------------------------------------------


async def run_agentic_loop(
    messages: List[Dict[str, Any]],
    session_id: str,
    max_rounds: int = 500,
    model_override: Optional[Dict[str, str]] = None,
) -> AsyncGenerator[str, None]:
    """Agentic tool loop 核心（仅使用原生结构化 tool calling）。"""
    from .llm_service import get_llm_service

    llm_service = get_llm_service()
    tool_definitions = get_agentic_tool_definitions()

    consecutive_failures = 0  # 连续全部失败的轮次计数
    consecutive_validation_failures = 0  # 连续工具参数验证失败轮次
    needs_summary = False  # 是否需要进行最终总结轮

    for round_num in range(1, max_rounds + 1):
        if round_num > 1:
            yield _format_sse_event("round_start", {"round": round_num})

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
                        chunk_text = chunk_data.get("text", "")

                        if chunk_type == "content":
                            complete_text += chunk_text
                        elif chunk_type == "reasoning":
                            complete_reasoning += chunk_text
                        elif chunk_type == "tool_calls":
                            parsed_calls = json.loads(chunk_text)
                            if isinstance(parsed_calls, list):
                                for item in parsed_calls:
                                    if isinstance(item, dict):
                                        structured_tool_calls.append(item)
                            # 原生 tool_calls 事件不透传给前端，统一由 loop 生成 tool_calls/tool_results 事件
                            continue
                except Exception as e:
                    logger.warning(f"[AgenticLoop] 解析流式工具调用失败: {e}")

            yield chunk

        logger.debug(
            f"[AgenticLoop] Round {round_num} complete_text ({len(complete_text)} chars): {complete_text[:300]!r}"
        )

        actionable_calls, live2d_calls, validation_errors = _convert_structured_tool_calls(structured_tool_calls)
        validation_results = _build_validation_results(validation_errors)

        if live2d_calls:
            asyncio.create_task(_send_live2d_actions(live2d_calls, session_id))

        if not actionable_calls:
            if validation_results and round_num < max_rounds:
                consecutive_validation_failures += 1
                logger.warning(
                    f"[AgenticLoop] Round {round_num}: 工具参数验证失败 {len(validation_results)} 条 "
                    f"(连续 {consecutive_validation_failures} 轮)"
                )

                # 通知前端并注入反馈，让模型下一轮纠正调用
                validation_summaries = []
                for r in validation_results:
                    result_text = r.get("result", "")
                    display_result = result_text[:500] + "..." if len(result_text) > 500 else result_text
                    validation_summaries.append(
                        {
                            "service_name": r.get("service_name", "unknown"),
                            "tool_name": r.get("tool_name", ""),
                            "status": r.get("status", "unknown"),
                            "result": display_result,
                        }
                    )
                yield _format_sse_event("tool_results", {"results": validation_summaries})

                assistant_content = complete_text if complete_text else "(工具调用参数错误)"
                messages.append({"role": "assistant", "content": assistant_content})
                messages.append(
                    {
                        "role": "user",
                        "content": format_tool_results_for_llm(validation_results),
                    }
                )

                if consecutive_validation_failures >= 2:
                    logger.warning("[AgenticLoop] 连续工具参数错误，提前进入总结轮")
                    yield _format_sse_event("round_end", {"round": round_num, "has_more": True})
                    needs_summary = True
                    break

                yield _format_sse_event("round_end", {"round": round_num, "has_more": True})
                continue

            logger.info(f"[AgenticLoop] Round {round_num}: 无工具调用，循环结束")
            yield _format_sse_event("round_end", {"round": round_num, "has_more": False})
            break

        consecutive_validation_failures = 0
        logger.info(f"[AgenticLoop] Round {round_num}: 检测到 {len(actionable_calls)} 个工具调用")

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

        executed_results = await execute_tool_calls(actionable_calls, session_id)
        results = validation_results + executed_results

        all_failed = bool(executed_results) and all(r.get("status") == "error" for r in executed_results)
        if all_failed:
            consecutive_failures += 1
            logger.warning(
                f"[AgenticLoop] Round {round_num}: 本轮所有可执行工具调用失败 (连续 {consecutive_failures} 轮)"
            )
        else:
            consecutive_failures = 0

        result_summaries = []
        for r in results:
            result_text = r.get("result", "")
            display_result = result_text[:500] + "..." if len(result_text) > 500 else result_text
            result_summaries.append(
                {
                    "service_name": r.get("service_name", "unknown"),
                    "tool_name": r.get("tool_name", ""),
                    "status": r.get("status", "unknown"),
                    "result": display_result,
                }
            )
        yield _format_sse_event("tool_results", {"results": result_summaries})

        assistant_content = complete_text if complete_text else "(工具调用中)"
        messages.append({"role": "assistant", "content": assistant_content})
        messages.append({"role": "user", "content": format_tool_results_for_llm(results)})

        if consecutive_failures >= 2:
            logger.warning(f"[AgenticLoop] 连续 {consecutive_failures} 轮工具全部失败，提前终止循环")
            yield _format_sse_event("round_end", {"round": round_num, "has_more": True})
            needs_summary = True
            break

        yield _format_sse_event("round_end", {"round": round_num, "has_more": True})
        logger.info(f"[AgenticLoop] Round {round_num}: 工具结果已注入，继续下一轮")
    else:
        needs_summary = True

    if needs_summary:
        logger.warning("[AgenticLoop] 执行最终总结轮")
        yield _format_sse_event("round_start", {"round": max_rounds + 1, "summary": True})
        messages.append(
            {
                "role": "user",
                "content": (
                    "[系统提示] 工具调用轮次已用尽。请根据以上所有工具返回结果，直接回答用户的问题。"
                    "如果所有工具都失败了，请诚实告知用户当前无法完成该操作，并给出建议。"
                    "不要再发起任何工具调用。"
                ),
            }
        )

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

        yield _format_sse_event("round_end", {"round": max_rounds + 1, "has_more": False})
