#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务规划器 - 基于博弈论架构的任务规划和评估模块
负责分析任务可执行性，制定执行计划
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from langchain_openai import ChatOpenAI

from system.config import config
from mcpserver.mcp_manager import get_mcp_manager

logger = logging.getLogger(__name__)

@dataclass
class Task:
    """任务数据结构"""
    id: str
    title: str
    original_query: str
    server_id: Optional[str] = None
    steps: List[str] = field(default_factory=list)
    status: str = "queued"  # queued | running | done | failed
    meta: Dict[str, Any] = field(default_factory=dict)

class TaskPlanner:
    """任务规划器 - 评估任务可执行性并制定执行计划"""
    
    def __init__(self):
        self.llm = ChatOpenAI(
            model=config.api.model,
            base_url=config.api.base_url,
            api_key=config.api.api_key,
            temperature=0
        )
        self.mcp_manager = get_mcp_manager()
        self.task_pool: Dict[str, Task] = {}
    
    async def refresh_capabilities(self) -> Dict[str, Dict[str, Any]]:
        """刷新MCP服务能力"""
        try:
            available_services = self.mcp_manager.get_available_services_filtered()
            return available_services
        except Exception as e:
            logger.error(f"刷新服务能力失败: {e}")
            return {}
    
    async def assess_and_plan(self, task_id: str, query: str, register: bool = True) -> Task:
        """评估任务可执行性并制定计划"""
        try:
            # 只评估Agent服务（MCP已分离）
            capabilities = await self.refresh_capabilities()
            agent_services = capabilities.get("agent_services", [])
            
            # 构建Agent服务能力描述
            tools_brief = self._build_agent_capabilities_brief(agent_services)
            
            logger.info(f"[规划器] 任务 {task_id} - 发现 {len(agent_services)} 个Agent服务")
            
            # Agent服务决策
            agent_decision = await self._assess_agent_executability(query, agent_services)
            
            # 确定执行状态
            status = self._determine_task_status(agent_decision)
            
            # 创建任务对象
            task = Task(
                id=task_id,
                title=query[:50],
                original_query=query,
                server_id=None,  # Agent任务不需要server_id
                steps=[query],  # Agent任务直接使用原始查询
                status=status,
                meta={
                    "agent": agent_decision
                }
            )
            
            if register:
                self.task_pool[task.id] = task
            
            logger.info(f"[规划器] 任务 {task_id} 规划完成 - 状态: {status}")
            return task
            
        except Exception as e:
            logger.error(f"任务规划失败: {e}")
            # 返回失败任务
            return Task(
                id=task_id,
                title=query[:50],
                original_query=query,
                status="failed",
                meta={"error": str(e)}
            )
    
    def _build_agent_capabilities_brief(self, agent_services: List[Dict]) -> str:
        """构建Agent服务能力描述"""
        brief_lines = []
        
        # Agent服务
        for service in agent_services:
            name = service.get("name", "")
            description = service.get("description", "")
            tool_name = service.get("tool_name", "agent")
            
            if description:
                brief_lines.append(f"- Agent {name}({tool_name}): {description}")
            else:
                brief_lines.append(f"- Agent {name}({tool_name})")
        
        return "\n".join(brief_lines)
    
    # MCP评估方法已移除，MCP和Agent已分离
    
    async def _assess_agent_executability(self, query: str, agent_services: List[Dict]) -> Dict[str, Any]:
        """评估Agent服务可执行性"""
        try:
            if not agent_services:
                return {"can_execute": False, "reason": "无可用Agent服务"}
            
            # 构建Agent服务描述
            agent_brief = "\n".join([
                f"- {service.get('name', '')}: {service.get('description', '')}"
                for service in agent_services
            ])
            
            system_prompt = """你是一个任务规划代理。判断任务是否可以通过Agent服务执行。
输出严格JSON格式: {can_execute: bool, reason: string, agent_name: string|null}"""
            
            user_prompt = f"可用Agent服务:\n{agent_brief}\n\n任务: {query}"
            
            response = self.llm.invoke([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ])
            
            text = response.content.strip()
            if text.startswith("```"):
                text = text.replace("```json", "").replace("```", "").strip()
            
            import json
            result = json.loads(text)
            
            if result.get('can_execute'):
                agent_name = result.get('agent_name', 'unknown')
                logger.info(f"[Agent] ✅ 任务可由Agent '{agent_name}' 执行")
            else:
                reason = result.get('reason', '未提供原因')
                logger.info(f"[Agent] ❌ 任务无法由Agent执行: {reason}")
            
            return result
            
        except Exception as e:
            logger.error(f"Agent可执行性评估失败: {e}")
            return {
                "can_execute": False,
                "reason": f"评估失败: {e}",
                "agent_name": None
            }
    
    def _determine_task_status(self, agent_decision: Dict) -> str:
        """确定任务状态（只基于Agent决策）"""
        if agent_decision and agent_decision.get('can_execute'):
            return "queued"
        else:
            return "failed"
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        return self.task_pool.get(task_id)
    
    def update_task_status(self, task_id: str, status: str):
        """更新任务状态"""
        if task_id in self.task_pool:
            self.task_pool[task_id].status = status
            logger.info(f"任务 {task_id} 状态更新为: {status}")
    
    def list_tasks(self, status: Optional[str] = None) -> List[Task]:
        """列出任务"""
        tasks = list(self.task_pool.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return tasks
