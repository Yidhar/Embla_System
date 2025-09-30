#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP调度Agent - 基于博弈论的MCP工具调用调度器
负责智能调度和管理MCP工具调用，类似xiao8的电脑控制Agent分离架构
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
import uuid

from .mcp_task_manager import MCPTaskManager
from .mcp_capability_analyzer import MCPCapabilityAnalyzer

logger = logging.getLogger(__name__)

class MCPSchedulerAgent:
    """MCP调度Agent - 智能MCP工具调用调度器"""
    
    def __init__(self):
        """初始化MCP调度Agent"""
        self.task_manager = MCPTaskManager()
        self.capability_analyzer = MCPCapabilityAnalyzer()
        self.active_tasks: Dict[str, Dict[str, Any]] = {}
        self.completed_tasks: Dict[str, Dict[str, Any]] = {}
        # 运行指标与熔断状态
        self.total_calls: int = 0
        self.total_failures: int = 0
        self.total_latency_ms: float = 0.0
        self.circuit_open: bool = False
        self.circuit_fail_window: List[float] = []  # 记录最近失败时间戳
        self.circuit_threshold: int = 5  # 短期失败阈值
        self.circuit_window_sec: int = 30
        
        logger.info("MCP调度Agent初始化完成")
    
    async def handle_mcp_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """处理MCP调度请求"""
        try:
            task_id = request.get("task_id", str(uuid.uuid4()))
            query = request.get("query", "")
            tool_calls = request.get("tool_calls", [])
            session_id = request.get("session_id", "default")
            
            logger.info(f"收到MCP调度请求: {task_id}, 查询: {query[:100]}...")
            
            # 分析MCP能力
            capabilities = await self.capability_analyzer.analyze_capabilities(query, tool_calls)
            
            # 创建任务
            task_info = {
                "task_id": task_id,
                "query": query,
                "tool_calls": tool_calls,
                "session_id": session_id,
                "capabilities": capabilities,
                "status": "queued",
                "created_at": datetime.now().isoformat(),
                "results": []
            }
            
            self.active_tasks[task_id] = task_info
            
            # 执行MCP调度
            result = await self._execute_mcp_scheduling(task_info)
            
            # 更新任务状态
            task_info["status"] = "completed" if result.get("success", False) else "failed"
            task_info["completed_at"] = datetime.now().isoformat()
            task_info["result"] = result
            
            # 移动到已完成任务
            self.completed_tasks[task_id] = task_info
            if task_id in self.active_tasks:
                del self.active_tasks[task_id]
            
            return {
                "success": True,
                "task_id": task_id,
                "result": result,
                "message": "MCP调度完成"
            }
            
        except Exception as e:
            logger.error(f"MCP调度失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": f"MCP调度失败: {e}"
            }
    
    async def _execute_mcp_scheduling(self, task_info: Dict[str, Any]) -> Dict[str, Any]:
        """执行MCP调度逻辑"""
        try:
            query = task_info["query"]
            tool_calls = task_info["tool_calls"]
            capabilities = task_info["capabilities"]
            capability_snapshot = task_info.get("capability_snapshot")
            
            # 如果没有工具调用，尝试从查询中提取
            if not tool_calls:
                tool_calls = await self._extract_tool_calls_from_query(query)
            
            if not tool_calls:
                return {
                    "success": False,
                    "error": "未找到可执行的MCP工具调用",
                    "message": "无法从查询中提取工具调用"
                }
            
            # 先使用能力分析器过滤/排序工具调用（根据复杂度和可行性）
            try:
                ranked = []
                for tc in tool_calls:
                    score = 0
                    try:
                        score = self.capability_analyzer._calculate_tool_complexity(tc)  # 较高分代表复杂
                    except Exception:
                        score = 0
                    ranked.append((score, tc))
                # 简单策略：先执行低复杂度（易成功）的
                ranked.sort(key=lambda x: x[0])
                tool_calls = [tc for _, tc in ranked]
            except Exception as e:
                logger.debug(f"工具排序失败: {e}")

            # 并行执行（无显式依赖）
            start_ts = datetime.now()
            async def _run(tc):
                try:
                    return await self._execute_single_tool_call(tc)
                except Exception as e:
                    logger.error(f"工具调用执行失败: {e}")
                    return {"success": False, "error": str(e), "tool_call": tc}

            results = await asyncio.gather(*[_run(tc) for tc in tool_calls])
            
            # 统计结果
            success_count = sum(1 for r in results if r.get("success", False))
            total_count = len(results)
            latency_ms = (datetime.now() - start_ts).total_seconds() * 1000.0
            self.total_calls += 1
            self.total_latency_ms += latency_ms
            if success_count == 0:
                self.total_failures += 1
                # 熔断记录
                now = datetime.now().timestamp()
                self.circuit_fail_window.append(now)
                # 清理窗口
                self.circuit_fail_window = [t for t in self.circuit_fail_window if now - t <= self.circuit_window_sec]
                if len(self.circuit_fail_window) >= self.circuit_threshold:
                    self.circuit_open = True
            else:
                # 成功时尝试半开
                if self.circuit_open and success_count > 0:
                    self.circuit_open = False
            
            return {
                "success": success_count > 0,
                "message": f"MCP调度完成: {success_count}/{total_count} 个工具调用成功",
                "results": results,
                "summary": {
                    "total_tools": total_count,
                    "successful_tools": success_count,
                    "failed_tools": total_count - success_count
                },
                "latency_ms": latency_ms
            }
            
        except Exception as e:
            logger.error(f"MCP调度执行失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": f"MCP调度执行失败: {e}"
            }
    
    async def _extract_tool_calls_from_query(self, query: str) -> List[Dict[str, Any]]:
        """从查询中提取工具调用"""
        # 这里可以集成AI模型来智能提取工具调用
        # 暂时返回空列表，后续实现
        logger.info(f"从查询中提取工具调用: {query}")
        return []
    
    async def _execute_single_tool_call(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """执行单个工具调用"""
        try:
            # 这里需要集成实际的MCP调用逻辑
            # 暂时返回模拟结果
            logger.info(f"执行工具调用: {tool_call}")
            
            # 模拟工具调用执行
            await asyncio.sleep(0.1)  # 模拟执行时间
            
            return {
                "success": True,
                "tool_call": tool_call,
                "result": f"工具调用执行成功: {tool_call.get('tool_name', 'unknown')}",
                "execution_time": 0.1
            }
            
        except Exception as e:
            logger.error(f"工具调用执行失败: {e}")
            return {
                "success": False,
                "tool_call": tool_call,
                "error": str(e),
                "execution_time": 0.0
            }
    
    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        # 检查活跃任务
        if task_id in self.active_tasks:
            task = self.active_tasks[task_id]
            return {
                "task_id": task_id,
                "status": task["status"],
                "query": task["query"],
                "created_at": task["created_at"]
            }
        
        # 检查已完成任务
        if task_id in self.completed_tasks:
            task = self.completed_tasks[task_id]
            return {
                "task_id": task_id,
                "status": task["status"],
                "query": task["query"],
                "created_at": task["created_at"],
                "completed_at": task.get("completed_at"),
                "result": task.get("result")
            }
        
        return None
    
    async def get_active_tasks(self) -> List[Dict[str, Any]]:
        """获取活跃任务列表"""
        return [
            {
                "task_id": task_id,
                "status": task["status"],
                "query": task["query"],
                "created_at": task["created_at"]
            }
            for task_id, task in self.active_tasks.items()
        ]
    
    async def get_completed_tasks(self) -> List[Dict[str, Any]]:
        """获取已完成任务列表"""
        return [
            {
                "task_id": task_id,
                "status": task["status"],
                "query": task["query"],
                "created_at": task["created_at"],
                "completed_at": task.get("completed_at"),
                "success": task.get("result", {}).get("success", False)
            }
            for task_id, task in self.completed_tasks.items()
        ]
    
    def get_capabilities(self) -> Dict[str, Any]:
        """获取MCP调度能力"""
        return {
            "enabled": True,
            "active_tasks": len(self.active_tasks),
            "completed_tasks": len(self.completed_tasks),
            "capabilities": [
                "MCP工具调用调度",
                "智能任务分解",
                "并行工具执行",
                "结果聚合"
            ]
        }
    
    def get_status(self) -> Dict[str, Any]:
        """获取MCP调度Agent状态"""
        avg_latency = (self.total_latency_ms / self.total_calls) if self.total_calls else 0.0
        failure_rate = (self.total_failures / self.total_calls) if self.total_calls else 0.0
        return {
            "agent_name": "MCPSchedulerAgent",
            "version": "1.0.0",
            "status": "running",
            "capabilities": self.get_capabilities(),
            "task_manager": self.task_manager.get_status(),
            "capability_analyzer": self.capability_analyzer.get_status(),
            "metrics": {
                "total_calls": self.total_calls,
                "total_failures": self.total_failures,
                "failure_rate": round(failure_rate, 3),
                "avg_latency_ms": round(avg_latency, 2),
                "circuit_open": self.circuit_open,
                "active_tasks": len(self.active_tasks)
            }
        }
