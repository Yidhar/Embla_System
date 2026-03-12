import asyncio
import logging
import traceback
import weakref
from typing import Any, Dict, List, Optional, Sequence, Tuple

from system.asyncio_offload import offload_blocking
from system.config import AI_NAME, config

from .quintuple_extractor import extract_quintuples
from .quintuple_graph import (
    clear_quintuples_store,
    get_all_quintuples,
    get_vector_index_status,
    query_graph_by_keywords,
    store_quintuples,
)
from .quintuple_rag_query import query_knowledge, set_context
from .task_manager import start_auto_cleanup, task_manager

logger = logging.getLogger(__name__)


class GRAGMemoryManager:
    """GRAG知识图谱记忆管理器。"""

    def __init__(self):
        self.enabled = config.grag.enabled
        self.auto_extract = config.grag.auto_extract
        self.context_length = config.grag.context_length
        self.similarity_threshold = config.grag.similarity_threshold
        extraction_timeout_raw = getattr(config.grag, "extraction_timeout", 12)
        extraction_retries_raw = getattr(config.grag, "extraction_retries", 2)
        self.extraction_timeout = max(1, int(12 if extraction_timeout_raw is None else extraction_timeout_raw))
        self.extraction_retries = max(0, int(2 if extraction_retries_raw is None else extraction_retries_raw))
        self.recent_context: List[str] = []
        self.extraction_cache = set()
        self.active_tasks = set()

        if not self.enabled:
            logger.info("GRAG记忆系统已禁用")
            return

        try:
            from .quintuple_graph import GRAG_ENABLED, get_graph

            graph = get_graph()
            if graph is None and GRAG_ENABLED:
                logger.warning("GRAG已启用但无法连接到Neo4j，将继续使用文件存储")
            logger.info("GRAG记忆系统初始化成功")

            start_auto_cleanup()

            self._weak_ref = weakref.ref(self)
            task_manager.on_task_completed = self._on_task_completed_wrapper
            task_manager.on_task_failed = self._on_task_failed_wrapper
        except Exception as exc:
            logger.error(f"GRAG记忆系统初始化失败: {exc}")
            self.enabled = False

    @staticmethod
    def _build_turn_text(user_input: str, ai_response: str) -> str:
        user_text = str(user_input or "").strip()
        ai_text = str(ai_response or "").strip()
        if not user_text and not ai_text:
            return ""
        return f"用户: {user_text}\n{AI_NAME}: {ai_text}".strip()

    @staticmethod
    def _stringify_message_content(content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, dict):
                    item_type = str(item.get("type") or "").strip().lower()
                    if item_type == "text":
                        text_value = str(item.get("text") or "").strip()
                        if text_value:
                            parts.append(text_value)
                        continue
                    if item_type == "image_url":
                        parts.append("[image]")
                        continue
                    fallback = str(item.get("text") or item.get("content") or "").strip()
                    if fallback:
                        parts.append(fallback)
                        continue
                text_value = str(item or "").strip()
                if text_value:
                    parts.append(text_value)
            return "\n".join(parts).strip()
        if isinstance(content, dict):
            text_value = str(content.get("text") or content.get("content") or "").strip()
            if text_value:
                return text_value
        return str(content).strip()

    def _format_round_message(self, message: Dict[str, Any]) -> str:
        role = str(message.get("role") or "").strip().lower()
        content = self._stringify_message_content(message.get("content"))

        if role == "assistant":
            tool_calls = message.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                tool_names: List[str] = []
                for item in tool_calls:
                    if not isinstance(item, dict):
                        continue
                    function_payload = item.get("function") if isinstance(item.get("function"), dict) else {}
                    tool_name = str(function_payload.get("name") or item.get("name") or "").strip()
                    if tool_name:
                        tool_names.append(tool_name)
                if tool_names:
                    tool_line = f"[tool_calls] {', '.join(tool_names)}"
                    content = f"{content}\n{tool_line}".strip() if content else tool_line

        if not content and role != "tool":
            return ""

        if role == "system":
            speaker = "系统"
        elif role == "user":
            speaker = "用户"
        elif role == "assistant":
            speaker = AI_NAME
        elif role == "tool":
            tool_call_id = str(message.get("tool_call_id") or "").strip()
            speaker = f"工具[{tool_call_id}]" if tool_call_id else "工具"
        else:
            speaker = role or "消息"

        return f"{speaker}: {content}".strip()

    def _build_round_extraction_text(self, round_messages: Sequence[Dict[str, Any]]) -> str:
        lines: List[str] = []
        for message in round_messages or []:
            if not isinstance(message, dict):
                continue
            line = self._format_round_message(message)
            if line:
                lines.append(line)
        return "\n".join(lines).strip()

    def _remember_recent_turn(self, turn_text: str) -> None:
        normalized = str(turn_text or "").strip()
        if not normalized:
            return
        self.recent_context.append(normalized)
        if len(self.recent_context) > self.context_length:
            self.recent_context = self.recent_context[-self.context_length :]

    async def _submit_extraction_text(self, extraction_text: str) -> bool:
        normalized = str(extraction_text or "").strip()
        if not normalized:
            return False

        try:
            if not task_manager.is_running:
                logger.warning("任务管理器未运行，正在启动...")
                from .task_manager import start_task_manager

                await start_task_manager()
                await asyncio.sleep(1)

            logger.info(
                "任务管理器状态: running=%s, workers=%s",
                task_manager.is_running,
                len(task_manager.worker_tasks),
            )

            task_id = await task_manager.add_task(normalized)
            self.active_tasks.add(task_id)
            logger.info("已提交五元组提取任务: %s", task_id)
            return True
        except Exception as exc:
            logger.error("提交提取任务失败: %s", exc)
            return await self._extract_and_store_quintuples_fallback(normalized)

    async def add_conversation_memory(self, user_input: str, ai_response: str) -> bool:
        """兼容旧入口：按单轮用户+助手文本抽取。"""
        if not self.enabled:
            return False
        try:
            conversation_text = self._build_turn_text(user_input, ai_response)
            logger.info("添加对话记忆: %s...", conversation_text[:50])
            self._remember_recent_turn(conversation_text)
            if self.auto_extract:
                return await self._submit_extraction_text(conversation_text)
            return True
        except Exception as exc:
            logger.error("添加对话记忆失败: %s", exc)
            return False

    async def add_shell_round_memory(
        self,
        session_id: str,
        round_messages: Sequence[Dict[str, Any]],
        *,
        latest_user_input: str = "",
        latest_ai_response: str = "",
    ) -> bool:
        """Shell L2 专用入口：从“当轮完整消息列表”抽取五元组。"""
        if not self.enabled:
            return False
        try:
            round_text = self._build_round_extraction_text(round_messages)
            if not round_text:
                logger.warning("会话 %s 缺少可抽取的 Shell 轮次消息", session_id)
                return False

            logger.info("添加Shell轮次记忆[%s]: %s...", session_id, round_text[:80])
            self._remember_recent_turn(self._build_turn_text(latest_user_input, latest_ai_response))

            if self.auto_extract:
                return await self._submit_extraction_text(round_text)
            return True
        except Exception as exc:
            logger.error("添加Shell轮次记忆失败: %s", exc)
            return False

    def _on_task_completed_wrapper(self, task_id: str, quintuples: List):
        """包装回调方法，处理实例可能被销毁的情况。"""
        instance = self._weak_ref()
        if instance:
            asyncio.run_coroutine_threadsafe(
                instance._on_task_completed(task_id, quintuples),
                loop=asyncio.get_event_loop(),
            )

    def _on_task_failed_wrapper(self, task_id: str, error: str):
        """包装失败回调，确保超时/失败任务也能回收 active_tasks。"""
        instance = self._weak_ref()
        if instance:
            asyncio.run_coroutine_threadsafe(
                instance._on_task_failed(task_id, error),
                loop=asyncio.get_event_loop(),
            )

    async def _on_task_completed(self, task_id: str, quintuples: List) -> None:
        try:
            self.active_tasks.discard(task_id)
            logger.info("任务完成回调: %s, 提取到 %s 个五元组", task_id, len(quintuples))

            if not quintuples:
                logger.warning("任务 %s 未提取到五元组", task_id)
                return

            logger.debug("准备存储五元组: %s...", quintuples[:2])
            store_success = store_quintuples(quintuples)

            if store_success:
                logger.info("任务 %s 的五元组存储成功", task_id)
            else:
                logger.error("任务 %s 的五元组存储失败", task_id)
        except Exception as exc:
            logger.error("任务完成回调处理失败: %s", exc)

    async def _on_task_failed(self, task_id: str, error: str) -> None:
        try:
            self.active_tasks.discard(task_id)
            logger.error("任务失败回调: %s, 错误: %s", task_id, error)
        except Exception as exc:
            logger.error("任务失败回调处理失败: %s", exc)

    async def _extract_and_store_quintuples_fallback(self, text: str) -> bool:
        """回退到同步提取方法。"""
        try:
            import hashlib

            text_hash = hashlib.sha256(text.encode()).hexdigest()

            if text_hash in self.extraction_cache:
                logger.debug("跳过已处理的文本: %s...", text[:50])
                return True

            logger.info("使用回退方法提取五元组: %s...", text[:100])

            try:
                quintuples = await asyncio.wait_for(
                    offload_blocking(
                        extract_quintuples,
                        text,
                        timeout_seconds=self.extraction_timeout,
                        max_retries=self.extraction_retries,
                    ),
                    timeout=float(self.extraction_timeout + 2),
                )
            except asyncio.TimeoutError:
                logger.warning("五元组提取超时(%ss)，跳过本次提取", self.extraction_timeout)
                return False

            if not quintuples:
                logger.warning("未提取到五元组")
                return False

            logger.info("提取到 %s 个五元组，准备存储", len(quintuples))

            try:
                store_success = await asyncio.wait_for(
                    offload_blocking(store_quintuples, quintuples),
                    timeout=15.0,
                )
            except asyncio.TimeoutError:
                logger.warning("五元组存储超时，跳过本次存储")
                return False

            if store_success:
                self.extraction_cache.add(text_hash)
                logger.info("五元组存储成功")
                return True

            logger.error("五元组存储失败")
            return False
        except Exception as exc:
            logger.error("提取和存储五元组失败: %s", str(exc))
            logger.error(traceback.format_exc())
            return False

    async def query_memory(self, question: str) -> Optional[str]:
        """查询记忆。"""
        if not self.enabled:
            return None

        try:
            set_context(self.recent_context)
            result = await offload_blocking(query_knowledge, question)
            if result and "未在知识图谱中找到相关信息" not in result:
                logger.info("从记忆中找到相关信息")
                return result
            return None
        except Exception as exc:
            logger.error("查询记忆失败: %s", exc)
            return None

    async def get_relevant_memories(self, query: str, limit: int = 3) -> List[Tuple[str, str, str, str, str]]:
        """获取相关记忆（五元组格式）。"""
        if not self.enabled:
            return []

        try:
            quintuples = await offload_blocking(query_graph_by_keywords, [query])
            return quintuples[:limit]
        except Exception as exc:
            logger.error("获取相关记忆失败: %s", exc)
            return []

    def get_memory_stats(self) -> Dict[str, Any]:
        """获取记忆统计信息。"""
        if not self.enabled:
            return {"enabled": False}

        try:
            all_quintuples = get_all_quintuples()
            task_stats = task_manager.get_stats()
            return {
                "enabled": True,
                "total_quintuples": len(all_quintuples),
                "context_length": len(self.recent_context),
                "cache_size": len(self.extraction_cache),
                "active_tasks": len(self.active_tasks),
                "task_manager": task_stats,
                "vector_index": get_vector_index_status(),
            }
        except Exception as exc:
            logger.error("获取记忆统计失败: %s", exc)
            return {"enabled": False, "error": str(exc)}

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态。"""
        return task_manager.get_task_status(task_id)

    def get_all_task_status(self) -> List[Dict[str, Any]]:
        """获取所有任务状态。"""
        return task_manager.get_all_tasks()

    def cancel_task(self, task_id: str) -> bool:
        """取消任务。"""
        if task_id in self.active_tasks:
            self.active_tasks.discard(task_id)
        return task_manager.cancel_task(task_id)

    async def clear_memory(self) -> bool:
        """清空记忆。"""
        if not self.enabled:
            return False

        try:
            self.recent_context.clear()
            self.extraction_cache.clear()

            for task_id in list(self.active_tasks):
                task_manager.cancel_task(task_id)
            self.active_tasks.clear()

            clear_result = clear_quintuples_store()
            if not clear_result.get("ok", False):
                logger.error("清空图谱记忆失败: %s", clear_result)
                return False

            logger.info("记忆已清空: %s", clear_result)
            return True
        except Exception as exc:
            logger.error("清空记忆失败: %s", exc)
            return False


memory_manager = GRAGMemoryManager()
