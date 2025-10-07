#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务调度器 - 提供轻量级内存调度与状态查询"""

import asyncio  # 异步支持 #
import uuid  # 任务ID #
from typing import Any, Dict, List, Optional  # 类型标注 #


class _TaskScheduler:
    """内存任务调度器 - 单例由get_task_scheduler提供"""

    def __init__(self) -> None:
        self.task_registry: Dict[str, Dict[str, Any]] = {}  # 任务注册表 #
        self._lock = asyncio.Lock()  # 并发锁 #

    async def schedule_parallel_execution(self, tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """并行调度执行给定任务列表，返回结果列表"""
        if not tasks:
            return []  # 空任务直接返回 #

        async def _run_task(task: Dict[str, Any]) -> Dict[str, Any]:
            task_id = task.get("id") or str(uuid.uuid4())  # 任务ID #
            async with self._lock:
                self.task_registry[task_id] = {
                    "id": task_id,
                    "type": task.get("type") or "processor",
                    "status": "running",
                    "params": task.get("params") or {},
                    "context": task.get("context"),
                }  # 注册并置为running #

            try:
                # 占位执行：此处可接入真实执行器 #
                await asyncio.sleep(0)  # 让出事件循环 #
                result = {
                    "success": True,
                    "result": None,
                    "task_type": self.task_registry[task_id]["type"],
                }  # 成功占位结果 #
                return result
            except Exception as e:  # noqa: BLE001 #
                return {"success": False, "error": str(e)}  # 失败结果 #
            finally:
                async with self._lock:
                    entry = self.task_registry.get(task_id)
                    if entry is not None:
                        entry["status"] = "completed"  # 置为完成 #

        coros = [_run_task(t) for t in tasks]  # 任务协程列表 #
        return await asyncio.gather(*coros, return_exceptions=False)  # 并行执行 #

    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """查询指定任务状态"""
        async with self._lock:
            return self.task_registry.get(task_id)  # 返回任务条目 #

    async def get_running_tasks(self) -> List[Dict[str, Any]]:
        """获取运行中任务列表"""
        async with self._lock:
            return [t for t in self.task_registry.values() if t.get("status") == "running"]  # 过滤运行中 #


_SCHEDULER: Optional[_TaskScheduler] = None  # 单例引用 #


def get_task_scheduler() -> _TaskScheduler:
    """获取全局任务调度器单例"""
    global _SCHEDULER  # 单例全局 #
    if _SCHEDULER is None:
        _SCHEDULER = _TaskScheduler()  # 初始化 #
    return _SCHEDULER  # 返回实例 #


