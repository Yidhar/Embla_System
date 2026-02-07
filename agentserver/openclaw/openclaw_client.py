#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenClaw 客户端适配器
用于与 OpenClaw Gateway 进行通信

官方文档: https://docs.openclaw.ai/

API 端点:
- POST /hooks/agent - 发送消息给 Agent
- POST /hooks/wake - 触发系统事件
- POST /tools/invoke - 直接调用工具
"""

import logging
import uuid
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

import httpx

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class OpenClawTask:
    """OpenClaw 任务数据结构"""
    task_id: str
    message: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    session_key: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "message": self.message,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": self.result,
            "error": self.error,
            "session_key": self.session_key
        }


@dataclass
class OpenClawConfig:
    """OpenClaw 配置"""
    # OpenClaw Gateway 默认端口是 18789
    gateway_url: str = "http://127.0.0.1:18789"
    # Gateway 认证 token (对应 gateway.auth.token)
    gateway_token: Optional[str] = None
    # Hooks 认证 token (对应 hooks.token)
    hooks_token: Optional[str] = None
    # 请求超时时间（秒）
    timeout: int = 120
    # 默认参数
    default_model: Optional[str] = None
    default_channel: str = "last"

    # 兼容旧配置
    token: Optional[str] = None

    def __post_init__(self):
        # 如果只配置了 token，同时用于 gateway 和 hooks
        if self.token and not self.gateway_token:
            self.gateway_token = self.token
        if self.token and not self.hooks_token:
            self.hooks_token = self.token

    def get_gateway_headers(self) -> Dict[str, str]:
        """获取 Gateway 请求头"""
        headers = {"Content-Type": "application/json"}
        if self.gateway_token:
            headers["Authorization"] = f"Bearer {self.gateway_token}"
        return headers

    def get_hooks_headers(self) -> Dict[str, str]:
        """获取 Hooks 请求头"""
        headers = {"Content-Type": "application/json"}
        if self.hooks_token:
            headers["Authorization"] = f"Bearer {self.hooks_token}"
        return headers

    def get_headers(self) -> Dict[str, str]:
        """获取请求头（兼容旧代码）"""
        return self.get_gateway_headers()


class OpenClawClient:
    """
    OpenClaw 客户端

    基于官方文档实现:
    - https://docs.openclaw.ai/automation/webhook
    - https://docs.openclaw.ai/gateway/tools-invoke-http-api

    功能：
    1. 发送消息给 Agent (POST /hooks/agent)
    2. 触发系统事件 (POST /hooks/wake)
    3. 直接调用工具 (POST /tools/invoke)
    """

    def __init__(self, config: Optional[OpenClawConfig] = None):
        self.config = config or OpenClawConfig()
        self._tasks: Dict[str, OpenClawTask] = {}
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端（懒加载）"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=self.config.timeout
            )
        return self._http_client

    async def close(self):
        """关闭客户端"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    # ============ 核心 API ============

    async def send_message(
        self,
        message: str,
        session_key: Optional[str] = None,
        name: Optional[str] = None,
        channel: Optional[str] = None,
        to: Optional[str] = None,
        model: Optional[str] = None,
        wake_mode: str = "now",
        deliver: bool = False
    ) -> OpenClawTask:
        """
        发送消息给 OpenClaw Agent

        使用 POST /hooks/agent 端点
        文档: https://docs.openclaw.ai/automation/webhook

        Args:
            message: 消息内容 (必需)
            session_key: 会话标识，用于多轮对话
            name: hook 名称，用于会话摘要前缀 (如 "GitHub", "Naga")
            channel: 输出通道 (last, whatsapp, telegram, discord, slack 等)
            to: 接收者标识
            model: 模型覆盖 (如 "anthropic/claude-3-5-sonnet")
            wake_mode: 唤醒模式 ("now" 或 "next-heartbeat")
            deliver: 是否投递到通道

        Returns:
            OpenClawTask: 任务对象
        """
        task_id = str(uuid.uuid4())
        task = OpenClawTask(
            task_id=task_id,
            message=message,
            session_key=session_key or f"naga:{task_id}"
        )

        try:
            client = await self._get_client()

            # 构建请求体
            payload: Dict[str, Any] = {
                "message": message
            }

            # 可选参数
            if session_key:
                payload["sessionKey"] = session_key
            if name:
                payload["name"] = name
            if channel:
                payload["channel"] = channel
            elif self.config.default_channel:
                payload["channel"] = self.config.default_channel
            if to:
                payload["to"] = to
            if model:
                payload["model"] = model
            elif self.config.default_model:
                payload["model"] = self.config.default_model
            if wake_mode:
                payload["wakeMode"] = wake_mode
            if deliver:
                payload["deliver"] = deliver

            logger.info(f"[OpenClaw] 发送消息到 /hooks/agent: {message[:50]}...")

            task.started_at = datetime.now().isoformat()
            task.status = TaskStatus.RUNNING

            response = await client.post(
                f"{self.config.gateway_url}/hooks/agent",
                json=payload,
                headers=self.config.get_hooks_headers()
            )

            # /hooks/agent 返回 202 表示异步执行成功
            if response.status_code in (200, 202):
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now().isoformat()
                try:
                    task.result = response.json()
                except Exception:
                    task.result = {"raw": response.text}
                logger.info(f"[OpenClaw] 消息发送成功: {task_id}")
            else:
                task.status = TaskStatus.FAILED
                task.error = f"HTTP {response.status_code}: {response.text}"
                logger.error(f"[OpenClaw] 消息发送失败: {task.error}")

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            logger.error(f"[OpenClaw] 消息发送异常: {e}")

        self._tasks[task_id] = task
        return task

    async def wake(
        self,
        text: str,
        mode: str = "now"
    ) -> Dict[str, Any]:
        """
        触发系统事件

        使用 POST /hooks/wake 端点
        文档: https://docs.openclaw.ai/automation/webhook

        Args:
            text: 事件描述
            mode: 触发模式 ("now" 或 "next-heartbeat")

        Returns:
            响应结果
        """
        try:
            client = await self._get_client()

            payload = {
                "text": text,
                "mode": mode
            }

            logger.info(f"[OpenClaw] 触发系统事件: {text[:50]}...")

            response = await client.post(
                f"{self.config.gateway_url}/hooks/wake",
                json=payload,
                headers=self.config.get_hooks_headers()
            )

            if response.status_code == 200:
                logger.info("[OpenClaw] 系统事件触发成功")
                try:
                    return {"success": True, "result": response.json()}
                except Exception:
                    return {"success": True, "result": response.text}
            else:
                logger.error(f"[OpenClaw] 系统事件触发失败: {response.status_code}")
                return {"success": False, "error": response.text}

        except Exception as e:
            logger.error(f"[OpenClaw] 系统事件触发异常: {e}")
            return {"success": False, "error": str(e)}

    async def invoke_tool(
        self,
        tool: str,
        args: Optional[Dict[str, Any]] = None,
        action: Optional[str] = None,
        session_key: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        直接调用工具

        使用 POST /tools/invoke 端点
        文档: https://docs.openclaw.ai/gateway/tools-invoke-http-api

        Args:
            tool: 工具名称 (必需)
            args: 工具参数
            action: 动作映射到工具参数
            session_key: 目标会话标识
            dry_run: 预留功能

        Returns:
            工具执行结果
        """
        try:
            client = await self._get_client()

            payload: Dict[str, Any] = {
                "tool": tool
            }

            if args:
                payload["args"] = args
            if action:
                payload["action"] = action
            if session_key:
                payload["sessionKey"] = session_key
            if dry_run:
                payload["dryRun"] = dry_run

            logger.info(f"[OpenClaw] 调用工具: {tool}")

            response = await client.post(
                f"{self.config.gateway_url}/tools/invoke",
                json=payload,
                headers=self.config.get_gateway_headers()
            )

            if response.status_code == 200:
                logger.info(f"[OpenClaw] 工具调用成功: {tool}")
                try:
                    return {"success": True, "result": response.json()}
                except Exception:
                    return {"success": True, "result": response.text}
            elif response.status_code == 400:
                logger.error(f"[OpenClaw] 工具调用错误: {response.text}")
                return {"success": False, "error": "invalid_request", "detail": response.text}
            elif response.status_code == 401:
                logger.error("[OpenClaw] 认证失败")
                return {"success": False, "error": "unauthorized"}
            elif response.status_code == 404:
                logger.error(f"[OpenClaw] 工具不可用: {tool}")
                return {"success": False, "error": "tool_not_found", "tool": tool}
            else:
                logger.error(f"[OpenClaw] 工具调用失败: {response.status_code}")
                return {"success": False, "error": response.text}

        except Exception as e:
            logger.error(f"[OpenClaw] 工具调用异常: {e}")
            return {"success": False, "error": str(e)}

    # ============ 任务管理 ============

    def get_task(self, task_id: str) -> Optional[OpenClawTask]:
        """获取本地缓存的任务"""
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> List[OpenClawTask]:
        """获取所有本地缓存的任务"""
        return list(self._tasks.values())

    def get_tasks_by_status(self, status: TaskStatus) -> List[OpenClawTask]:
        """按状态获取任务"""
        return [t for t in self._tasks.values() if t.status == status]

    def clear_completed_tasks(self):
        """清理已完成的任务"""
        self._tasks = {
            k: v for k, v in self._tasks.items()
            if v.status not in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]
        }

    # ============ 健康检查 ============

    async def health_check(self) -> Dict[str, Any]:
        """
        检查 OpenClaw Gateway 健康状态

        Returns:
            健康状态信息
        """
        client = await self._get_client()

        try:
            # 尝试访问根路径或健康检查端点
            response = await client.get(
                f"{self.config.gateway_url}/",
                timeout=10,
                headers=self.config.get_gateway_headers()
            )

            if response.status_code == 200:
                return {
                    "status": "healthy",
                    "gateway_url": self.config.gateway_url
                }
            else:
                return {
                    "status": "unhealthy",
                    "gateway_url": self.config.gateway_url,
                    "error": f"HTTP {response.status_code}"
                }

        except Exception as e:
            return {
                "status": "unreachable",
                "gateway_url": self.config.gateway_url,
                "error": str(e)
            }


# 全局客户端实例（懒加载）
_openclaw_client: Optional[OpenClawClient] = None


def get_openclaw_client(config: Optional[OpenClawConfig] = None) -> OpenClawClient:
    """获取全局 OpenClaw 客户端实例"""
    global _openclaw_client
    if _openclaw_client is None:
        _openclaw_client = OpenClawClient(config)
    return _openclaw_client


def set_openclaw_config(config: OpenClawConfig):
    """设置 OpenClaw 配置并重新创建客户端"""
    global _openclaw_client
    _openclaw_client = OpenClawClient(config)
