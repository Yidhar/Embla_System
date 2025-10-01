#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务调度器 - 基于博弈论的任务调度机制
整合后台分析和并行执行，作为agentserver的调度中心
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
import uuid
from system.background_analyzer import get_background_analyzer
from agentserver.parallel_executor import get_parallel_executor
from agentserver.task_deduper import get_task_deduper
from agentserver.computer_use_scheduler import get_computer_use_scheduler

logger = logging.getLogger(__name__)

class TaskScheduler:
    """任务调度器 - 基于博弈论的调度机制"""
    
    def __init__(self):
        self.analyzer = get_background_analyzer()
        self.executor = get_parallel_executor()
        self.deduper = get_task_deduper()
        self.computer_use_scheduler = get_computer_use_scheduler()
        # MCP调度器已移除，MCP和Agent已分离
        self.scheduled_tasks = {}
        self.task_registry: Dict[str, Dict[str, Any]] = {}
    
    async def schedule_background_analysis(self, session_id: str, messages: List[Dict[str, str]]):
        """调度后台分析 - 基于博弈论的背景分析机制"""
        try:
            logger.info(f"开始后台分析会话 {session_id}")
            
            # 异步执行意图分析
            analysis = await self.analyzer.analyze_intent_async(messages, session_id)
            
            # 引入工具调用循环：意图识别 → 执行工具 → 更新上下文 → 继续识别（最多2轮） # 注释
            await self._run_intent_mcp_loop(session_id, messages, initial_analysis=analysis, max_iterations=2)
            
            logger.info(f"会话 {session_id} 后台分析完成")
            
        except Exception as e:
            logger.error(f"后台分析失败: {e}")

    async def _run_intent_mcp_loop(self, session_id: str, messages: List[Dict[str, str]], initial_analysis: Optional[Dict[str, Any]] = None, max_iterations: int = 2):
        """意图识别-工具调用循环（最多N轮）"""  # 注释
        try:
            history = list(messages)  # 浅拷贝，避免外部引用受影响 # 注释
            analysis = initial_analysis or {}
            for _ in range(max_iterations):  # 迭代次数 # 注释
                tool_calls = (analysis or {}).get("tool_calls") or []
                if not tool_calls:
                    break  # 无工具调用时结束 # 注释
                # 取最近一条用户消息作为query # 注释
                query = ""
                for m in reversed(history):
                    if m.get("role") == "user":
                        query = m.get("content") or m.get("text") or ""
                        if query:
                            break
                task_id = str(uuid.uuid4())
                result = await self.schedule_mcp_task(
                    task_id=task_id,
                    query=query,
                    tool_calls=tool_calls,
                    session_id=session_id,
                    capability_snapshot=(analysis or {}).get("capability_snapshot")
                )
                # 将工具结果追加到上下文，供下一轮识别 # 注释
                result_text = str(result.get("result")) if isinstance(result, dict) else str(result)
                history.append({"role": "assistant", "content": f"工具执行结果：{result_text}"})
                # 下一轮意图识别 # 注释
                analysis = await self.analyzer.analyze_intent_async(history[-6:], session_id)
        except Exception as e:
            logger.error(f"意图-工具循环失败: {e}")
    
    async def schedule_parallel_execution(self, tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """调度并行执行"""
        try:
            logger.info(f"开始并行执行 {len(tasks)} 个任务")
            
            # 执行并行任务
            results = await self.executor.execute_parallel_tasks(tasks)
            
            logger.info(f"并行执行完成，处理了 {len(results)} 个任务")
            return results
            
        except Exception as e:
            logger.error(f"并行执行失败: {e}")
            return []

    # MCP任务调度已移除，MCP和Agent已分离
    
    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        task_info = self.executor.get_task_status(task_id)
        if not task_info:
            return None
        
        return {
            "task_id": task_info.id,
            "type": task_info.type,
            "status": task_info.status,
            "start_time": task_info.start_time,
            "result": task_info.result,
            "error": task_info.error
        }
    
    async def get_running_tasks(self) -> List[Dict[str, Any]]:
        """获取运行中的任务"""
        running_tasks = self.executor.get_running_tasks()
        return [
            {
                "task_id": task.id,
                "type": task.type,
                "status": task.status,
                "start_time": task.start_time,
                "pid": task.pid
            }
            for task in running_tasks
        ]
    
    def _collect_existing_task_descriptions(self, session_id: Optional[str] = None) -> List[tuple[str, str]]:
        """收集现有任务描述 - 基于博弈论的任务收集机制"""
        items: List[tuple[str, str]] = []
        
        # 从任务注册表收集
        for tid, info in self.task_registry.items():
            try:
                if info.get("status") in ("queued", "running"):
                    if session_id and info.get("session_id") not in (None, session_id):
                        continue
                    params = info.get("params") or {}
                    desc = params.get("query") or params.get("instruction") or ""
                    if desc:
                        items.append((tid, desc))
            except Exception:
                continue
        
        return items
    
    def _is_duplicate_task(self, query: str, session_id: Optional[str] = None) -> tuple[bool, Optional[str]]:
        """判断任务是否重复 - 基于博弈论的重复检测机制"""
        try:
            if not self.deduper:
                return False, None
            
            candidates = self._collect_existing_task_descriptions(session_id)
            result = self.deduper.judge(query, candidates)
            
            return result.get("duplicate", False), result.get("matched_id")
        except Exception as e:
            logger.error(f"任务去重判断失败: {e}")
            return False, None
    
    async def schedule_computer_use_task(self, task_id: str, instruction: str, screenshot: Optional[bytes] = None, session_id: Optional[str] = None):
        """调度电脑控制任务 - 基于博弈论的电脑控制调度机制"""
        try:
            # 检查是否重复
            is_duplicate, matched_id = self._is_duplicate_task(instruction, session_id)
            if is_duplicate:
                logger.info(f"任务重复，跳过: {instruction} (匹配: {matched_id})")
                return
            
            # 注册任务
            self.task_registry[task_id] = {
                "id": task_id,
                "type": "computer_use",
                "status": "queued",
                "params": {"instruction": instruction, "screenshot": screenshot},
                "session_id": session_id
            }
            
            # 排队到电脑控制调度器
            await self.computer_use_scheduler.queue_computer_use_task(task_id, instruction, screenshot)
            
            logger.info(f"电脑控制任务已调度: {task_id}")
            
        except Exception as e:
            logger.error(f"电脑控制任务调度失败: {e}")
    
    def get_computer_use_status(self) -> Dict[str, Any]:
        """获取电脑控制状态"""
        return {
            "is_busy": self.computer_use_scheduler.is_computer_use_busy(),
            "active_task_id": self.computer_use_scheduler.get_active_task_id()
        }
    


# 全局调度器实例
_task_scheduler = None

def get_task_scheduler() -> TaskScheduler:
    """获取全局任务调度器实例"""
    global _task_scheduler
    if _task_scheduler is None:
        _task_scheduler = TaskScheduler()
    return _task_scheduler
