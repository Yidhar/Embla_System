#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
后台意图分析器 - 基于博弈论的对话分析机制
分析对话片段，提取潜在任务意图
"""

import asyncio
import json
import time
from typing import Dict, Any, List, Optional, Tuple, TYPE_CHECKING
from urllib.parse import urlparse
from system.asyncio_offload import offload_blocking
from system.config import config, logger
from system.coding_intent import extract_latest_user_message as extract_latest_user_message_shared
from system.coding_intent import requires_core_execution_for_messages
from autonomous.router_engine import RouterRequest, TaskRouterEngine

from system.config import get_prompt

if TYPE_CHECKING:
    import httpx
    from langchain_openai import ChatOpenAI


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
_MUTATING_NATIVE_TOOL_NAMES = {"write_file", "git_checkout_file"}
_PROMPT_ROUTE_ENGINE = TaskRouterEngine()


def _extract_latest_user_message(messages: List[Dict[str, str]]) -> str:
    return extract_latest_user_message_shared(messages)


def _infer_analysis_complexity(latest_user_message: str) -> str:
    size = len(str(latest_user_message or ""))
    if size >= 320:
        return "high"
    if size >= 120:
        return "medium"
    return "low"


def _infer_analysis_risk_level(messages: List[Dict[str, str]], latest_user_message: str) -> str:
    latest = str(latest_user_message or "").lower()
    readonly_markers = (
        "不要修改",
        "不要改",
        "不做修改",
        "只读",
        "read only",
        "read-only",
        "no write",
    )
    if any(marker in latest for marker in readonly_markers):
        return "read_only"
    if any(token in latest for token in ("deploy", "发布", "上线", "rollback", "回滚", "secrets", "密钥")):
        return "deploy"
    if _looks_like_coding_request(latest_user_message) or requires_core_execution_for_messages(messages):
        return "write_repo"
    return "read_only"


def _build_router_request_for_messages(messages: List[Dict[str, str]]) -> RouterRequest:
    latest_user_message = _extract_latest_user_message(messages)
    return RouterRequest(
        task_id="background_analyzer",
        description=latest_user_message,
        estimated_complexity=_infer_analysis_complexity(latest_user_message),
        requested_role="",
        risk_level=_infer_analysis_risk_level(messages, latest_user_message),
        budget_remaining=6000,
        trace_id="background_analyzer",
        session_id="background_analyzer",
    )


def _derive_prompt_route_metadata(messages: List[Dict[str, str]]) -> Dict[str, str]:
    request = _build_router_request_for_messages(messages)
    decision = _PROMPT_ROUTE_ENGINE.route(request)
    return {
        "prompt_profile": str(decision.prompt_profile),
        "injection_mode": str(decision.injection_mode),
        "delegation_intent": str(decision.delegation_intent),
        "selected_role": str(decision.selected_role),
    }


def _looks_like_coding_request(text: str) -> bool:
    lowered = (text or "").lower()
    if any(keyword in lowered for keyword in _CODING_KEYWORDS):
        return True
    return requires_core_execution_for_messages([{"role": "user", "content": text or ""}])


def _is_mutating_native_call(call: Dict[str, Any]) -> bool:
    if str(call.get("agentType", "")).strip().lower() != "native":
        return False
    tool_name = str(call.get("tool_name", "")).strip().lower()
    return tool_name in _MUTATING_NATIVE_TOOL_NAMES


def _shorten_for_log(value: Any, limit: int = 300) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _normalize_mcp_call_payload(call: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(call or {})
    nested_args = normalized.get("arguments")
    if isinstance(nested_args, dict):
        for key, value in nested_args.items():
            normalized.setdefault(key, value)
    return normalized


def _extract_mcp_result_status(raw_result: Any) -> Tuple[str, str]:
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


class ConversationAnalyzer:
    """
    对话分析器模块：分析语音对话轮次以推断潜在任务意图
    输入是跨服务器的文本转录片段；输出是零个或多个标准化的任务查询
    """

    def __init__(self):
        self.llm: Optional["ChatOpenAI"] = None

        # Delayed import to avoid startup import races across multi-threaded boot.
        from langchain_openai import ChatOpenAI

        self.llm = ChatOpenAI(
            model=config.api.model,
            base_url=self._normalize_google_openai_compat_base_url(config.api.base_url or ""),
            api_key=config.api.api_key,  # type: ignore[arg-type]
            temperature=0,
        )

    @staticmethod
    def _normalize_google_openai_compat_base_url(raw_base_url: str) -> str:
        base = (raw_base_url or "").strip().rstrip("/")
        if not base:
            return base

        parsed = urlparse(base if "://" in base else f"https://{base}")
        host = (parsed.netloc or "").strip().lower()
        if "generativelanguage.googleapis.com" not in host:
            return base

        path = (parsed.path or "").rstrip("/")
        lowered_path = path.lower()

        models_idx = lowered_path.find("/models/")
        if models_idx != -1:
            path = path[:models_idx]
            lowered_path = path.lower()

        for suffix in ("/openai/chat/completions", "/chat/completions", "/completions"):
            if lowered_path.endswith(suffix):
                path = path[: -len(suffix)]
                lowered_path = path.lower()
                break

        if lowered_path.endswith("/openai"):
            path = path[: -len("/openai")]
            lowered_path = path.lower()

        if "/v1alpha" in lowered_path:
            version_path = "/v1alpha"
        elif "/v1beta" in lowered_path:
            version_path = "/v1beta"
        elif "/v1/" in lowered_path or lowered_path.endswith("/v1"):
            version_path = "/v1"
        else:
            version_path = "/v1beta"

        scheme = parsed.scheme or "https"
        return f"{scheme}://{parsed.netloc}{version_path}/openai"

    def _build_prompt(self, messages: List[Dict[str, str]]) -> str:
        lines = []
        for m in messages[-config.api.max_history_rounds :]:
            role = m.get("role", "user")
            # 修复：使用content字段而不是text字段
            content = m.get("content", "")
            # 清理文本，移除可能导致格式化问题的字符
            content = content.replace("{", "{{").replace("}", "}}")
            lines.append(f"{role}: {content}")
        conversation = "\n".join(lines)

        available_tools = ""
        route_meta = _derive_prompt_route_metadata(messages)
        route_hint = (
            "\n[ROUTER_HINT]"
            f" prompt_profile={route_meta.get('prompt_profile', '')}"
            f" injection_mode={route_meta.get('injection_mode', '')}"
            f" delegation_intent={route_meta.get('delegation_intent', '')}"
            f" selected_role={route_meta.get('selected_role', '')}"
        )

        # 加载主分析提示词
        base_prompt = get_prompt(
            "conversation_analyzer_prompt",
            conversation=conversation,
            available_tools=available_tools,
            prompt_profile=route_meta.get("prompt_profile", ""),
            injection_mode=route_meta.get("injection_mode", ""),
            delegation_intent=route_meta.get("delegation_intent", ""),
            selected_role=route_meta.get("selected_role", ""),
        )

        # 加载工具调度提示词（独立文件，拼接到主提示词后面）
        try:
            available_mcp_tools = self._get_mcp_tools_description()
            tool_dispatch = get_prompt(
                "tool_dispatch_prompt",
                available_mcp_tools=available_mcp_tools,
                prompt_profile=route_meta.get("prompt_profile", ""),
                injection_mode=route_meta.get("injection_mode", ""),
                delegation_intent=route_meta.get("delegation_intent", ""),
                selected_role=route_meta.get("selected_role", ""),
            )
            return base_prompt + route_hint + "\n" + tool_dispatch
        except Exception as e:
            logger.debug(f"加载工具调度提示词失败，仅使用基础提示词: {e}")
            return base_prompt + route_hint

    def _get_mcp_tools_description(self) -> str:
        """获取MCP可用工具描述，供提示词注入。自动触发注册（幂等）。"""
        try:
            from mcpserver.mcp_registry import auto_register_mcp

            auto_register_mcp()  # 幂等，重复调用不会重新注册

            from mcpserver.mcp_manager import get_mcp_manager

            manager = get_mcp_manager()
            desc = manager.format_available_services()
            return desc if desc else "（暂无MCP服务注册）"
        except Exception:
            return "（MCP服务未启动）"

    def analyze(self, messages: List[Dict[str, str]]):
        logger.info(f"[ConversationAnalyzer] 开始分析对话，消息数量: {len(messages)}")
        prompt = self._build_prompt(messages)
        logger.info(f"[ConversationAnalyzer] 构建提示词完成，长度: {len(prompt)}")

        result = self._analyze_with_function_calling(prompt)
        if result and result.get("tool_calls"):
            return result

        logger.info("[ConversationAnalyzer] 未发现可执行任务")
        return {"tasks": [], "reason": "未发现可执行任务", "raw": "", "tool_calls": []}

    def _analyze_with_function_calling(self, prompt: str) -> Optional[Dict]:
        """Strict mode: only accept native function-calling tool_calls."""
        logger.info("[ConversationAnalyzer] 尝试原生 function calling 解析")
        try:
            if self.llm is None:
                raise RuntimeError("ConversationAnalyzer LLM is not initialized")

            from agents.tool_loop import convert_structured_tool_calls, get_agentic_tool_definitions

            llm_with_tools = self.llm.bind_tools(get_agentic_tool_definitions(), tool_choice="auto")
            resp = llm_with_tools.invoke(
                [
                    {"role": "system", "content": "You are a precise intent extractor and MCP tool planning assistant."},
                    {"role": "user", "content": prompt},
                ]
            )

            raw_content: Any = getattr(resp, "content", "")
            if isinstance(raw_content, str):
                text = raw_content.strip()
            else:
                text = str(raw_content).strip()

            logger.info(f"[ConversationAnalyzer] LLM响应完成，正文长度: {len(text)}")
            structured_calls = self._extract_structured_tool_calls(resp)
            logger.info(f"[ConversationAnalyzer] 提取到结构化 tool_calls: {len(structured_calls)}")
            tool_calls, validation_errors = convert_structured_tool_calls(
                structured_calls,
                session_id=None,
                trace_id=None,
            )
            if validation_errors:
                logger.warning("[ConversationAnalyzer] function-calling 参数校验失败: %s", " | ".join(validation_errors))

            if tool_calls:
                logger.info(f"[ConversationAnalyzer] function-calling 解析成功，发现 {len(tool_calls)} 个工具调用")
                return {
                    "tasks": [],
                    "reason": f"function-calling 解析成功，发现 {len(tool_calls)} 个工具调用",
                    "tool_calls": tool_calls,
                }
            logger.info("[ConversationAnalyzer] 未发现结构化工具调用")
            return None

        except Exception as e:
            logger.error(f"[ConversationAnalyzer] function-calling 解析失败: {e}")
            return None

    @staticmethod
    def _normalize_structured_tool_call(raw_call: Dict[str, Any], index: int) -> Optional[Dict[str, Any]]:
        if not isinstance(raw_call, dict):
            return None
        call_id = str(raw_call.get("id") or f"tool_call_{index}").strip() or f"tool_call_{index}"
        name = str(raw_call.get("name") or "").strip()
        args = raw_call.get("args")
        parse_error = ""

        function_payload = raw_call.get("function")
        if not name and isinstance(function_payload, dict):
            name = str(function_payload.get("name") or "").strip()
            args = function_payload.get("arguments")

        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception as exc:
                parse_error = str(exc)
                args = {}
        if args is None:
            args = {}
        if not isinstance(args, dict):
            parse_error = parse_error or f"arguments must be object, got {type(args).__name__}"
            args = {}

        if not name:
            return None
        payload: Dict[str, Any] = {"id": call_id, "name": name, "arguments": args}
        if parse_error:
            payload["parse_error"] = parse_error
        return payload

    def _extract_structured_tool_calls(self, response: Any) -> List[Dict[str, Any]]:
        raw_calls: List[Any] = []

        response_tool_calls = getattr(response, "tool_calls", None)
        if isinstance(response_tool_calls, list):
            raw_calls.extend(response_tool_calls)

        additional_kwargs = getattr(response, "additional_kwargs", None)
        if isinstance(additional_kwargs, dict):
            nested = additional_kwargs.get("tool_calls")
            if isinstance(nested, list):
                raw_calls.extend(nested)

        normalized: List[Dict[str, Any]] = []
        for index, item in enumerate(raw_calls, start=1):
            normalized_call = self._normalize_structured_tool_call(item, index)
            if normalized_call is not None:
                normalized.append(normalized_call)
        return normalized


class BackgroundAnalyzer:
    """后台分析器 - 管理异步意图分析"""

    def __init__(self):
        self.analyzer = ConversationAnalyzer()
        self.running_analyses = {}
        self._http_client: Optional["httpx.AsyncClient"] = None

    def _get_http_client(self) -> "httpx.AsyncClient":
        """获取共享的 httpx.AsyncClient 实例（lazy init）"""
        if self._http_client is None or self._http_client.is_closed:
            import httpx

            self._http_client = httpx.AsyncClient(timeout=httpx.Timeout(timeout=150.0, connect=10.0))
        return self._http_client

    def _enforce_coding_route(
        self,
        tool_calls: List[Dict[str, Any]],
        messages: List[Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        # Coding-route force injection has been retired; keep original plan intact.
        return list(tool_calls)

    async def analyze_intent_async(self, messages: List[Dict[str, str]], session_id: str):
        """异步意图分析 - 基于博弈论的背景分析机制"""
        # 检查是否已经有分析在进行中
        if session_id in self.running_analyses:
            logger.info(f"[博弈论] 会话 {session_id} 已有意图分析在进行中，跳过重复执行")
            return {"has_tasks": False, "reason": "已有分析在进行中", "tasks": [], "priority": "low"}

        # 创建独立的意图分析会话
        analysis_session_id = f"analysis_{session_id}_{int(time.time())}"
        logger.info(f"[博弈论] 创建独立分析会话: {analysis_session_id}")

        # 标记分析开始
        self.running_analyses[session_id] = analysis_session_id

        await self._notify_ui_tool_status(
            session_id=session_id,
            message="正在检测工具调用",
            stage="detecting",
            auto_hide_ms=0,
        )

        try:
            logger.info(f"[博弈论] 开始异步意图分析，消息数量: {len(messages)}")
            # Offload sync LLM call away from the event loop.
            logger.info("[博弈论] 在线程池中执行LLM分析...")

            # 添加异步超时机制
            try:
                analysis = await asyncio.wait_for(
                    offload_blocking(self.analyzer.analyze, messages),
                    timeout=60.0,  # 60秒超时
                )
                logger.info(f"[博弈论] LLM分析完成，结果类型: {type(analysis)}")
            except asyncio.TimeoutError:
                logger.error("[博弈论] 意图分析超时（60秒）")
                return {"has_tasks": False, "reason": "意图分析超时", "tasks": [], "priority": "low"}

        except Exception as e:
            logger.error(f"[博弈论] 意图分析失败: {e}")
            import traceback

            logger.error(f"[博弈论] 详细错误信息: {traceback.format_exc()}")
            return {"has_tasks": False, "reason": f"分析失败: {e}", "tasks": [], "priority": "low"}

        try:
            tasks = analysis.get("tasks", []) if isinstance(analysis, dict) else []
            tool_calls = analysis.get("tool_calls", []) if isinstance(analysis, dict) else []
            if isinstance(tool_calls, list):
                tool_calls = self._enforce_coding_route(tool_calls, messages)

            if not tasks and not tool_calls:
                await self._notify_ui_tool_status(
                    session_id=session_id,
                    message="未检测到工具调用",
                    stage="none",
                    auto_hide_ms=1200,
                )
                return {"has_tasks": False, "reason": "未发现可执行任务", "tasks": [], "priority": "low"}

            logger.info(
                f"[博弈论] 分析会话 {analysis_session_id} 发现 {len(tasks)} 个任务和 {len(tool_calls)} 个工具调用"
            )

            # 处理工具调用 - 根据agentType分发到不同服务器
            if tool_calls:
                # 通知UI工具调用开始
                await self._notify_ui_tool_calls(tool_calls, session_id)
                await self._dispatch_tool_calls(tool_calls, session_id, analysis_session_id)

            # 返回分析结果
            result = {
                "has_tasks": True,
                "reason": analysis.get("reason", "发现潜在任务"),
                "tasks": tasks,
                "tool_calls": tool_calls,
                "priority": "medium",  # 可以根据任务数量或类型调整优先级
            }

            # 记录任务详情
            for task in tasks:
                logger.info(f"发现任务: {task}")
            for tool_call in tool_calls:
                logger.info(f"发现工具调用: {tool_call}")

            return result

        except Exception as e:
            logger.error(f"任务处理失败: {e}")
            return {"has_tasks": False, "reason": f"处理失败: {e}", "tasks": [], "priority": "low"}
        finally:
            # 清除分析状态标记
            if session_id in self.running_analyses:
                del self.running_analyses[session_id]
                logger.info(f"[博弈论] 会话 {session_id} 分析状态已清除")

    async def _notify_ui_tool_calls(self, tool_calls: List[Dict[str, Any]], session_id: str):
        """批量通知UI工具调用开始 - 优化网络请求"""
        try:
            notification_payload = {
                "session_id": session_id,
                "tool_calls": [
                    {
                        "tool_name": tool_call.get("tool_name", "未知工具"),
                        "service_name": tool_call.get("service_name", "未知服务"),
                        "status": "starting",
                    }
                    for tool_call in tool_calls
                ],
                "stage": "executing",
                "auto_hide_ms": 0,
                "message": f"检测到{len(tool_calls)}个工具调用，执行中",
            }

            from system.config import get_server_port

            await self._get_http_client().post(
                f"http://localhost:{get_server_port('api_server')}/tool_notification", json=notification_payload
            )

        except Exception as e:
            logger.error(f"批量通知UI工具调用失败: {e}")

    async def _notify_ui_tool_status(self, session_id: str, message: str, stage: str, auto_hide_ms: int) -> None:
        """通知UI显示工具调用相关状态"""
        try:
            from system.config import get_server_port

            notification_payload = {
                "session_id": session_id,
                "tool_calls": [],
                "stage": stage,
                "auto_hide_ms": auto_hide_ms,
                "message": message,
            }

            await self._get_http_client().post(
                f"http://localhost:{get_server_port('api_server')}/tool_notification",
                json=notification_payload,
            )
        except Exception as e:
            logger.error(f"通知UI工具状态失败: {e}")

    async def _dispatch_tool_calls(
        self, tool_calls: List[Dict[str, Any]], session_id: str, analysis_session_id: Optional[str] = None
    ):
        """将工具调用分发到不同服务"""
        try:
            mcp_calls = [tc for tc in tool_calls if tc.get("agentType") == "mcp"]

            if mcp_calls:
                await self._send_to_mcp(mcp_calls, session_id)

        except Exception as e:
            logger.error(f"工具调用分发失败: {e}")

    async def _send_to_mcp(self, mcp_calls: List[Dict[str, Any]], session_id: str):
        """将MCP工具调用直接 in-process 路由到 MCPManager（多个调用并行执行）"""
        try:
            from mcpserver.mcp_manager import get_mcp_manager

            manager = get_mcp_manager()

            async def _execute_one(call: Dict[str, Any]):
                call = _normalize_mcp_call_payload(call)
                service_name = call.get("service_name", "")
                tool_name = call.get("tool_name", "")
                call_id = str(call.get("_tool_call_id") or f"bg_mcp_{tool_name or 'unknown'}")

                if not service_name and tool_name in {
                    "ask_guide",
                    "ask_guide_with_screenshot",
                    "calculate_damage",
                    "get_team_recommendation",
                }:
                    service_name = "game_guide"
                    call["service_name"] = service_name

                if not service_name and not tool_name:
                    logger.warning("[MCP] 工具调用缺少service_name和tool_name，跳过: %s", call)
                    return
                try:
                    logger.info(
                        "[MCP] 调用开始 id=%s service=%s tool=%s payload_keys=%s",
                        call_id,
                        service_name or "<missing>",
                        tool_name or "<missing>",
                        sorted(call.keys()),
                    )
                    result = await manager.unified_call(service_name, call)
                    mcp_status, detail = _extract_mcp_result_status(result)
                    if mcp_status == "error":
                        logger.warning(
                            "[MCP] 调用失败 id=%s service=%s tool=%s detail=%s",
                            call_id,
                            service_name,
                            tool_name,
                            detail,
                        )
                    else:
                        logger.info(
                            "[MCP] 调用成功 id=%s service=%s tool=%s detail=%s",
                            call_id,
                            service_name,
                            tool_name,
                            detail,
                        )
                    await self._notify_ui_mcp_result(session_id, service_name, tool_name, result)
                except Exception as e:
                    logger.error("[MCP] 调用异常 id=%s service=%s tool=%s error=%s", call_id, service_name, tool_name, e)
                    await self._notify_ui_mcp_result(
                        session_id, service_name, tool_name, f'{{"status": "error", "message": "{e}"}}'
                    )

            # 多个 MCP 调用并行执行
            await asyncio.gather(*[_execute_one(call) for call in mcp_calls], return_exceptions=True)

        except Exception as e:
            logger.error(f"[MCP] 发送MCP工具调用失败: {e}")

    async def _notify_ui_mcp_result(self, session_id: str, service_name: str, tool_name: str, result: str):
        """将 MCP 工具调用结果推送到 UI"""
        try:
            from system.config import get_server_port

            payload = {
                "session_id": session_id,
                "action": "show_mcp_result",
                "service_name": service_name,
                "tool_name": tool_name,
                "result": result,
            }

            await self._get_http_client().post(
                f"http://localhost:{get_server_port('api_server')}/ui_notification",
                json=payload,
            )
            status, detail = _extract_mcp_result_status(result)
            logger.info(
                "[MCP] 结果已推送到 UI: service=%s tool=%s status=%s detail=%s",
                service_name,
                tool_name,
                status,
                detail,
            )
        except Exception as e:
            logger.error(f"[MCP] 推送结果到 UI 失败: {e}")


_background_analyzer = None


def get_background_analyzer() -> BackgroundAnalyzer:
    """获取全局后台分析器实例"""
    global _background_analyzer
    if _background_analyzer is None:
        _background_analyzer = BackgroundAnalyzer()
    return _background_analyzer
