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
from system.config import config, logger
from system.coding_intent import extract_latest_user_message as extract_latest_user_message_shared
from system.coding_intent import requires_codex_for_messages

from system.config import get_prompt

if TYPE_CHECKING:
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
_CODEX_SERVICE_ALIASES = {"codex-cli", "codex-mcp"}
_CODEX_TOOL_ALIASES = {"ask-codex", "brainstorm", "help", "ping"}
_MUTATING_NATIVE_TOOL_NAMES = {"write_file", "git_checkout_file"}


def _extract_latest_user_message(messages: List[Dict[str, str]]) -> str:
    return extract_latest_user_message_shared(messages)


def _looks_like_coding_request(text: str) -> bool:
    lowered = (text or "").lower()
    if any(keyword in lowered for keyword in _CODING_KEYWORDS):
        return True
    return requires_codex_for_messages([{"role": "user", "content": text or ""}])


def _is_codex_mcp_call(call: Dict[str, Any]) -> bool:
    if str(call.get("agentType", "")).strip().lower() != "mcp":
        return False
    service = str(call.get("service_name", "")).strip().lower()
    tool = str(call.get("tool_name", "")).strip().lower()
    if tool in _CODEX_TOOL_ALIASES and (not service or service in _CODEX_SERVICE_ALIASES):
        return True
    return service in _CODEX_SERVICE_ALIASES


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

        # 加载主分析提示词
        base_prompt = get_prompt(
            "conversation_analyzer_prompt",
            conversation=conversation,
            available_tools=available_tools,
        )

        # 加载工具调度提示词（独立文件，拼接到主提示词后面）
        try:
            available_mcp_tools = self._get_mcp_tools_description()
            tool_dispatch = get_prompt(
                "tool_dispatch_prompt",
                available_mcp_tools=available_mcp_tools,
            )
            return base_prompt + "\n" + tool_dispatch
        except Exception as e:
            logger.debug(f"加载工具调度提示词失败，仅使用基础提示词: {e}")
            return base_prompt

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

        # 使用简化的非标准JSON解析
        result = self._analyze_with_non_standard_json(prompt)
        if result and result.get("tool_calls"):
            return result

        # 解析失败
        logger.info("[ConversationAnalyzer] 未发现可执行任务")
        return {"tasks": [], "reason": "未发现可执行任务", "raw": "", "tool_calls": []}

    def _analyze_with_non_standard_json(self, prompt: str) -> Optional[Dict]:
        """非标准JSON格式解析 - 直接调用LLM，避免嵌套线程池"""
        logger.info("[ConversationAnalyzer] 尝试非标准JSON格式解析")
        try:
            if self.llm is None:
                raise RuntimeError("ConversationAnalyzer LLM is not initialized")

            # Call LLM directly and avoid nested threadpool invocations.
            resp = self.llm.invoke(
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

            logger.info(f"[ConversationAnalyzer] LLM响应完成，响应长度: {len(text)}")
            logger.info(f"[ConversationAnalyzer] LLM原始响应内容: {text}")

            # 解析非标准JSON格式
            tool_calls = self._parse_non_standard_json(text)

            if tool_calls:
                logger.info(f"[ConversationAnalyzer] 非标准JSON解析成功，发现 {len(tool_calls)} 个工具调用")
                return {
                    "tasks": [],
                    "reason": f"非标准JSON解析成功，发现 {len(tool_calls)} 个工具调用",
                    "tool_calls": tool_calls,
                }
            else:
                logger.info("[ConversationAnalyzer] 未发现工具调用")
                return None

        except Exception as e:
            logger.error(f"[ConversationAnalyzer] 非标准JSON解析失败: {e}")
            return None

    def _parse_non_standard_json(self, text: str) -> List[Dict[str, Any]]:
        """解析非标准JSON格式。

        兼容场景：
        - LLM输出全角括号/标点（如｛｝），导致下游解析器无法识别
        - LLM输出在JSON前后夹杂少量说明文字
        """

        normalized_text = self._normalize_fullwidth_json_chars(text)

        # 优先使用核心库解析器（如果可用）
        try:
            from system.parsing import parse_non_standard_json

            tool_calls = parse_non_standard_json(normalized_text)
            if tool_calls:
                return tool_calls
        except Exception as e:
            logger.debug(f"parse_non_standard_json不可用或解析失败，尝试回退解析: {e}")

        # 回退：从文本中提取一个或多个JSON对象并解析
        return self._fallback_extract_json_objects(normalized_text)

    @staticmethod
    def _normalize_fullwidth_json_chars(text: str) -> str:
        """将常见全角JSON相关字符归一化为ASCII。

        仅做保守替换，避免影响普通文本内容。
        """
        if not text:
            return text

        translation_table = str.maketrans(
            {
                "｛": "{",
                "｝": "}",
                "：": ":",
                "，": ",",
                "“": '"',
                "”": '"',
                "‘": "'",
                "’": "'",
            }
        )
        return text.translate(translation_table)

    def _fallback_extract_json_objects(self, text: str) -> List[Dict[str, Any]]:
        """从文本中提取JSON对象（支持多个），并用json5/json解析。

        返回值统一为List[Dict]；无法解析时返回空列表。
        """

        def _loads(s: str) -> Any:
            try:
                import json5 as _json5

                return _json5.loads(s)
            except Exception:
                import json as _json

                return _json.loads(s)

        objects: List[Dict[str, Any]] = []
        start: Optional[int] = None
        depth = 0

        for i, ch in enumerate(text):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start is not None:
                        candidate = text[start : i + 1].strip()
                        start = None

                        # 跳过空对象（表示“无任务”）
                        if candidate in ("{}", "{ }"):
                            continue

                        try:
                            parsed = _loads(candidate)
                        except Exception:
                            continue

                        if isinstance(parsed, dict):
                            objects.append(parsed)
                        elif isinstance(parsed, list):
                            for item in parsed:
                                if isinstance(item, dict):
                                    objects.append(item)

        # 只保留形如工具调用的对象（避免误解析到无关JSON）
        filtered: List[Dict[str, Any]] = []
        for obj in objects:
            agent_type = obj.get("agentType")
            if isinstance(agent_type, str) and agent_type:
                filtered.append(obj)

        return filtered


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

    def _enforce_coding_codex_route(
        self,
        tool_calls: List[Dict[str, Any]],
        messages: List[Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        latest_user_request = _extract_latest_user_message(messages)
        if not (_looks_like_coding_request(latest_user_request) or requires_codex_for_messages(messages)):
            return tool_calls

        normalized_calls = list(tool_calls)
        has_codex = any(_is_codex_mcp_call(call) for call in normalized_calls)
        if has_codex:
            return normalized_calls

        dropped_mutating = 0
        passthrough_calls: List[Dict[str, Any]] = []
        for call in normalized_calls:
            if _is_mutating_native_call(call):
                dropped_mutating += 1
                continue
            passthrough_calls.append(call)

        codex_call = {
            "agentType": "mcp",
            "service_name": "codex-cli",
            "tool_name": "ask-codex",
            "message": latest_user_request or "Complete the pending coding task in current repository.",
            "sandboxMode": "workspace-write",
            "approvalPolicy": "on-failure",
        }
        rewritten = [codex_call, *passthrough_calls]
        logger.info(
            "[BackgroundAnalyzer] coding request routed to codex first; inserted ask-codex call, dropped_mutating=%s",
            dropped_mutating,
        )
        return rewritten

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
            loop = asyncio.get_running_loop()
            # Offload sync LLM call to threadpool to avoid blocking event loop
            logger.info("[博弈论] 在线程池中执行LLM分析...")

            # 添加异步超时机制
            try:
                analysis = await asyncio.wait_for(
                    loop.run_in_executor(None, self.analyzer.analyze, messages),
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
                tool_calls = self._enforce_coding_codex_route(tool_calls, messages)

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
            live2d_calls = [tc for tc in tool_calls if tc.get("agentType") == "live2d"]
            mcp_calls = [tc for tc in tool_calls if tc.get("agentType") == "mcp"]

            if live2d_calls:
                await self._send_live2d_actions(live2d_calls, session_id)

            if mcp_calls:
                await self._send_to_mcp(mcp_calls, session_id)

        except Exception as e:
            logger.error(f"工具调用分发失败: {e}")
    async def _send_live2d_actions(self, live2d_calls: List[Dict[str, Any]], session_id: str):
        """将 Live2D 动作发送到 UI"""
        try:
            from system.config import get_server_port

            client = self._get_http_client()

            for call in live2d_calls:
                action_name = call.get("action", "")
                if not action_name:
                    continue

                payload = {
                    "session_id": session_id,
                    "action": "live2d_action",
                    "action_name": action_name,
                }

                response = await client.post(
                    f"http://localhost:{get_server_port('api_server')}/ui_notification",
                    json=payload,
                )
                if response.status_code == 200:
                    logger.info(f"[Live2D] 动作已发送到 UI: {action_name}")
                else:
                    logger.error(f"[Live2D] 动作发送失败: {response.status_code}")

        except Exception as e:
            logger.error(f"[Live2D] 发送动作到 UI 失败: {e}")

    async def _send_to_mcp(self, mcp_calls: List[Dict[str, Any]], session_id: str):
        """将MCP工具调用直接 in-process 路由到 MCPManager（多个调用并行执行）"""
        try:
            from mcpserver.mcp_manager import get_mcp_manager

            manager = get_mcp_manager()

            async def _execute_one(call: Dict[str, Any]):
                call = _normalize_codex_mcp_call_payload(call)
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

                if not service_name and tool_name in {"ask-codex", "brainstorm", "help", "ping"}:
                    service_name = "codex-cli"
                    call["service_name"] = service_name

                if tool_name == "ask-codex":
                    call.setdefault("sandboxMode", "workspace-write")
                    call.setdefault("approvalPolicy", "on-failure")

                if not service_name and not tool_name:
                    logger.warning("[MCP] 工具调用缺少service_name和tool_name，跳过: %s", call)
                    return
                try:
                    prompt_len = len(str(call.get("prompt") or "")) if tool_name == "ask-codex" else 0
                    logger.info(
                        "[MCP] 调用开始 id=%s service=%s tool=%s prompt_len=%s payload_keys=%s",
                        call_id,
                        service_name or "<missing>",
                        tool_name or "<missing>",
                        prompt_len,
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

