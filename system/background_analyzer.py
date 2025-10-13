#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
后台意图分析器 - 基于博弈论的对话分析机制
分析对话片段，提取潜在任务意图
"""

import asyncio
import logging
from typing import Dict, Any, List
from langchain_openai import ChatOpenAI
from system.config import get_prompt

logger = logging.getLogger(__name__)

class ConversationAnalyzer:
    """
    对话分析器模块：分析语音对话轮次以推断潜在任务意图
    输入是跨服务器的文本转录片段；输出是零个或多个标准化的任务查询
    """
    def __init__(self):
        # 使用Naga的配置系统
        try:
            from system.config import config
            self.llm = ChatOpenAI(
                model=config.api.model,
                base_url=config.api.base_url,
                api_key=config.api.api_key,
                temperature=0
            )
        except ImportError:
            # 降级配置
            self.llm = ChatOpenAI(
                model="gpt-3.5-turbo",
                base_url="https://api.openai.com/v1",
                api_key="sk-placeholder",
                temperature=0
            )
            logger.warning("无法导入配置，使用默认LLM设置")

    def _build_prompt(self, messages: List[Dict[str, str]]) -> str:
        lines = []
        for m in messages[-20:]:
            role = m.get('role', 'user')
            text = m.get('text', '')
            # 清理文本，移除可能导致格式化问题的字符
            text = text.replace('{', '{{').replace('}', '}}')
            lines.append(f"{role}: {text}")
        conversation = "\n".join(lines)
        
        # 获取可用的MCP工具信息，注入到意图识别中
        try:
            from mcpserver.mcp_registry import get_all_services_info
            services_info = get_all_services_info()
            
            # 构建工具信息摘要
            tools_summary = []
            for name, info in services_info.items():
                display_name = info.get("display_name", name)
                description = info.get("description", "")
                tools = [t.get("name") for t in info.get("available_tools", [])]
                
                if tools:
                    tools_summary.append(f"- {display_name}: {description} (工具: {', '.join(tools)})")
                else:
                    tools_summary.append(f"- {display_name}: {description}")
            
            if tools_summary:
                available_tools = "\n".join(tools_summary)
                # 将工具信息注入到对话分析提示词中
                return get_prompt("conversation_analyzer_prompt", 
                                conversation=conversation,
                                available_tools=f"\n\n【可用MCP工具】\n{available_tools}\n")
        except Exception as e:
            logger.debug(f"获取MCP工具信息失败: {e}")
        
        return get_prompt("conversation_analyzer_prompt", conversation=conversation)

    def analyze(self, messages: List[Dict[str, str]]):
        prompt = self._build_prompt(messages)
        resp = self.llm.invoke([
            {"role": "system", "content": "你是精确的任务意图提取器与MCP调用规划器。"},
            {"role": "user", "content": prompt},
        ])
        text = resp.content.strip()
        import json, re
        tool_calls: List[Dict[str, Any]] = []

        # 提取可能出现的多个 MCP 调用 JSON 对象（宽松匹配，逐个解析）
        try:
            code_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
            # 若没有代码块，尝试直接匹配花括号对象
            if not code_blocks:
                code_blocks = re.findall(r"\{[\s\S]*?\}", text)

            parsed_objects = []
            for blk in code_blocks:
                blk_clean = blk.strip()
                try:
                    parsed = json.loads(blk_clean)
                    parsed_objects.append(parsed)
                except Exception:
                    continue

            # 第一个对象预期为主 JSON（reason/tasks），其余可能为 MCP 调用块
            main_obj = {"tasks": [], "reason": ""}
            for obj in parsed_objects:
                if isinstance(obj, dict) and "tasks" in obj and "reason" in obj:
                    main_obj = obj
                    break

            for obj in parsed_objects:
                if isinstance(obj, dict) and obj.get("agentType") == "mcp":
                    tool_calls.append(obj)

            if not main_obj.get("tasks") and not tool_calls:
                # 若未能可靠解析，退回整体尝试
                try:
                    main_obj = json.loads(text)
                except Exception:
                    pass

            if tool_calls:
                main_obj["tool_calls"] = tool_calls

            if not main_obj.get("reason"):
                main_obj["reason"] = main_obj.get("reason", "") or ""

            return main_obj
        except Exception as e:
            logger.error(f"解析MCP调用块失败: {e}")
            return {"tasks": [], "reason": f"parse error: {e}", "raw": text, "tool_calls": []}


class BackgroundAnalyzer:
    """后台分析器 - 管理异步意图分析"""
    
    def __init__(self):
        self.analyzer = ConversationAnalyzer()
        self.running_analyses = {}
    
    async def analyze_intent_async(self, messages: List[Dict[str, str]], session_id: str):
        """异步意图分析 - 基于博弈论的背景分析机制"""
        try:
            loop = asyncio.get_running_loop()
            # Offload sync LLM call to threadpool to avoid blocking event loop
            analysis = await loop.run_in_executor(None, self.analyzer.analyze, messages)
        except Exception as e:
            logger.error(f"意图分析失败: {e}")
            return {"has_tasks": False, "reason": f"分析失败: {e}", "tasks": [], "priority": "low"}
        
        try:
            import uuid as _uuid
            tasks = analysis.get("tasks", []) if isinstance(analysis, dict) else []
            
            if not tasks:
                logger.debug(f"会话 {session_id} 未发现可执行任务")
                return {"has_tasks": False, "reason": "未发现可执行任务", "tasks": [], "priority": "low"}
            
            logger.info(f"会话 {session_id} 发现 {len(tasks)} 个潜在任务")
            
            # 返回分析结果
            result = {
                "has_tasks": True,
                "reason": analysis.get("reason", "发现潜在任务"),
                "tasks": tasks,
                "priority": "medium"  # 可以根据任务数量或类型调整优先级
            }
            
            # 记录任务详情
            for task in tasks:
                logger.info(f"发现任务: {task}")
            
            return result
                
        except Exception as e:
            logger.error(f"任务处理失败: {e}")
            return {"has_tasks": False, "reason": f"处理失败: {e}", "tasks": [], "priority": "low"}


# 全局分析器实例
_background_analyzer = None

def get_background_analyzer() -> BackgroundAnalyzer:
    """获取全局后台分析器实例"""
    global _background_analyzer
    if _background_analyzer is None:
        _background_analyzer = BackgroundAnalyzer()
    return _background_analyzer
