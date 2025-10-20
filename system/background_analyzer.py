#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
后台意图分析器 - 基于博弈论的对话分析机制
分析对话片段，提取潜在任务意图
"""

import asyncio
from typing import Dict, Any, List
from system.config import config, logger
from langchain_openai import ChatOpenAI

from system.config import get_prompt

class ConversationAnalyzer:
    """
    对话分析器模块：分析语音对话轮次以推断潜在任务意图
    输入是跨服务器的文本转录片段；输出是零个或多个标准化的任务查询
    """
    def __init__(self):
        self.llm = ChatOpenAI(
            model=config.api.model,
            base_url=config.api.base_url,
            api_key=config.api.api_key,
            temperature=0
        )

    def _build_prompt(self, messages: List[Dict[str, str]]) -> str:
        lines = []
        for m in messages[-config.api.max_history_rounds:]:
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

        # 首先尝试解析 [TOOL_CALL] 格式
        tool_call_pattern = r'\[TOOL_CALL\](.*?)\[/TOOL_CALL\]'
        tool_call_matches = re.findall(tool_call_pattern, text, re.DOTALL)
        
        if tool_call_matches:
            for match in tool_call_matches:
                try:
                    # 解析 TOOL_CALL 格式
                    lines = match.strip().split('\n')
                    tool_call = {}
                    for line in lines:
                        if ':' in line:
                            key, value = line.split(':', 1)
                            key = key.strip()
                            value = value.strip()
                            
                            if key == 'service':
                                tool_call['service_name'] = value
                            elif key == 'tool':
                                tool_call['tool_name'] = value
                            elif key == 'params':
                                try:
                                    tool_call['params'] = json.loads(value)
                                except:
                                    tool_call['params'] = {}
                    
                    if 'service_name' in tool_call and 'tool_name' in tool_call:
                        tool_call['agentType'] = 'mcp'
                        tool_calls.append(tool_call)
                        
                except Exception as e:
                    logger.error(f"解析TOOL_CALL格式失败: {e}")
                    continue

        # 如果没有找到TOOL_CALL格式，尝试解析JSON格式
        if not tool_calls:
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
                    if isinstance(obj, dict) and obj.get("agentType") in ["mcp", "agent"]:
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
        
        # 如果有TOOL_CALL格式的工具调用，返回结果
        return {
            "tasks": [],
            "reason": f"发现 {len(tool_calls)} 个工具调用",
            "tool_calls": tool_calls
        }


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
            tool_calls = analysis.get("tool_calls", []) if isinstance(analysis, dict) else []
            
            if not tasks and not tool_calls:
                logger.debug(f"会话 {session_id} 未发现可执行任务")
                return {"has_tasks": False, "reason": "未发现可执行任务", "tasks": [], "priority": "low"}
            
            logger.info(f"会话 {session_id} 发现 {len(tasks)} 个任务和 {len(tool_calls)} 个工具调用")
            
            # 处理工具调用 - 根据agentType分发到不同服务器
            if tool_calls:
                await self._dispatch_tool_calls(tool_calls, session_id)
            
            # 返回分析结果
            result = {
                "has_tasks": True,
                "reason": analysis.get("reason", "发现潜在任务"),
                "tasks": tasks,
                "tool_calls": tool_calls,
                "priority": "medium"  # 可以根据任务数量或类型调整优先级
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

    async def _dispatch_tool_calls(self, tool_calls: List[Dict[str, Any]], session_id: str):
        """根据agentType将工具调用分发到相应的服务器"""
        try:
            import httpx
            import uuid
            
            # 按agentType分组
            mcp_calls = []
            agent_calls = []
            
            for tool_call in tool_calls:
                agent_type = tool_call.get("agentType", "")
                if agent_type == "mcp":
                    mcp_calls.append(tool_call)
                elif agent_type == "agent":
                    agent_calls.append(tool_call)
            
            # 分发MCP任务到MCP服务器
            if mcp_calls:
                await self._send_to_mcp_server(mcp_calls, session_id)
            
            # 分发Agent任务到agentserver
            if agent_calls:
                await self._send_to_agent_server(agent_calls, session_id)
                
        except Exception as e:
            logger.error(f"工具调用分发失败: {e}")
    
    async def _send_to_mcp_server(self, mcp_calls: List[Dict[str, Any]], session_id: str):
        """发送MCP任务到MCP服务器"""
        try:
            import httpx
            import uuid
            
            # 构建MCP服务器请求
            mcp_payload = {
                "query": f"批量MCP工具调用 ({len(mcp_calls)} 个)",
                "tool_calls": mcp_calls,
                "session_id": session_id,
                "request_id": str(uuid.uuid4()),
                "callback_url": "http://localhost:8001/tool_result_callback"
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "http://localhost:8003/schedule",
                    json=mcp_payload
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"MCP任务调度成功: {result.get('task_id', 'unknown')}")
                else:
                    logger.error(f"MCP任务调度失败: {response.status_code} - {response.text}")
                    
        except Exception as e:
            logger.error(f"发送MCP任务失败: {e}")
    
    async def _send_to_agent_server(self, agent_calls: List[Dict[str, Any]], session_id: str):
        """发送Agent任务到agentserver"""
        try:
            import httpx
            import uuid
            
            # 构建agentserver请求
            agent_payload = {
                "messages": [
                    {"role": "user", "content": f"执行Agent任务: {agent_call.get('instruction', '')}"}
                    for agent_call in agent_calls
                ],
                "session_id": session_id
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "http://localhost:8002/analyze_and_execute",
                    json=agent_payload
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Agent任务调度成功: {result.get('status', 'unknown')}")
                else:
                    logger.error(f"Agent任务调度失败: {response.status_code} - {response.text}")
                    
        except Exception as e:
            logger.error(f"发送Agent任务失败: {e}")


# 全局分析器实例
_background_analyzer = None

def get_background_analyzer() -> BackgroundAnalyzer:
    """获取全局后台分析器实例"""
    global _background_analyzer
    if _background_analyzer is None:
        _background_analyzer = BackgroundAnalyzer()
    return _background_analyzer
