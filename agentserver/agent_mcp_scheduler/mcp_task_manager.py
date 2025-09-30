#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP任务管理器 - 管理MCP工具调用的任务生命周期
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)

class TaskStatus(Enum):
    """任务状态枚举"""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class MCPTaskManager:
    """MCP任务管理器"""
    
    def __init__(self):
        """初始化任务管理器"""
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.task_queue: asyncio.Queue = asyncio.Queue()
        self.is_processing = False
        
        logger.info("MCP任务管理器初始化完成")
    
    async def create_task(self, task_id: str, query: str, tool_calls: List[Dict], 
                         session_id: str = "default") -> Dict[str, Any]:
        """创建新任务"""
        task_info = {
            "task_id": task_id,
            "query": query,
            "tool_calls": tool_calls,
            "session_id": session_id,
            "status": TaskStatus.QUEUED.value,
            "created_at": datetime.now().isoformat(),
            "started_at": None,
            "completed_at": None,
            "results": [],
            "error": None
        }
        
        self.tasks[task_id] = task_info
        await self.task_queue.put(task_info)
        
        logger.info(f"创建MCP任务: {task_id}")
        return task_info
    
    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务信息"""
        return self.tasks.get(task_id)
    
    async def update_task_status(self, task_id: str, status: TaskStatus, 
                                result: Optional[Dict[str, Any]] = None,
                                error: Optional[str] = None):
        """更新任务状态"""
        if task_id in self.tasks:
            task = self.tasks[task_id]
            task["status"] = status.value
            
            if status == TaskStatus.RUNNING:
                task["started_at"] = datetime.now().isoformat()
            elif status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                task["completed_at"] = datetime.now().isoformat()
            
            if result:
                task["results"].append(result)
            
            if error:
                task["error"] = error
            
            logger.info(f"任务状态更新: {task_id} -> {status.value}")
    
    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        if task_id in self.tasks:
            await self.update_task_status(task_id, TaskStatus.CANCELLED)
            logger.info(f"任务已取消: {task_id}")
            return True
        return False
    
    async def get_tasks_by_status(self, status: Optional[TaskStatus] = None) -> List[Dict[str, Any]]:
        """根据状态获取任务列表"""
        if status is None:
            return list(self.tasks.values())
        
        return [
            task for task in self.tasks.values()
            if task["status"] == status.value
        ]
    
    async def get_tasks_by_session(self, session_id: str) -> List[Dict[str, Any]]:
        """根据会话ID获取任务列表"""
        return [
            task for task in self.tasks.values()
            if task.get("session_id") == session_id
        ]
    
    async def cleanup_old_tasks(self, max_age_hours: int = 24) -> int:
        """清理旧任务"""
        from datetime import datetime, timedelta
        
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        cleaned_count = 0
        
        tasks_to_remove = []
        for task_id, task in self.tasks.items():
            if task["status"] in [TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value]:
                completed_at = task.get("completed_at")
                if completed_at:
                    try:
                        task_time = datetime.fromisoformat(completed_at)
                        if task_time < cutoff_time:
                            tasks_to_remove.append(task_id)
                    except ValueError:
                        # 如果时间格式错误，也删除
                        tasks_to_remove.append(task_id)
        
        for task_id in tasks_to_remove:
            del self.tasks[task_id]
            cleaned_count += 1
        
        if cleaned_count > 0:
            logger.info(f"清理了 {cleaned_count} 个旧任务")
        
        return cleaned_count
    
    def get_status(self) -> Dict[str, Any]:
        """获取任务管理器状态"""
        status_counts = {}
        for task in self.tasks.values():
            status = task["status"]
            status_counts[status] = status_counts.get(status, 0) + 1
        
        return {
            "total_tasks": len(self.tasks),
            "status_counts": status_counts,
            "queue_size": self.task_queue.qsize(),
            "is_processing": self.is_processing
        }
