#!/usr/bin/env python3
"""
LLM适配器模块
为game模块提供LLM调用接口，通过HTTP访问apiserver的LLM服务
"""

import asyncio
import aiohttp
import json
import logging
from typing import Optional

logger = logging.getLogger("LLMAdapter")

class LLMAdapter:
    """LLM适配器 - 为game模块提供LLM调用接口"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip('/')
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建HTTP会话"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def get_response(self, prompt: str, temperature: float = 0.7) -> str:
        """调用LLM服务获取响应"""
        try:
            session = await self._get_session()
            url = f"{self.base_url}/llm/chat"
            
            data = {
                "prompt": prompt,
                "temperature": temperature
            }
            
            async with session.post(url, json=data, timeout=120) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get("response", "无响应")
                else:
                    error_text = await response.text()
                    logger.error(f"LLM服务调用失败: {response.status} - {error_text}")
                    return f"LLM服务调用失败: {response.status}"
                    
        except asyncio.TimeoutError:
            logger.error("LLM服务调用超时")
            return "LLM服务调用超时"
        except Exception as e:
            logger.error(f"LLM服务调用异常: {e}")
            return f"LLM服务调用异常: {str(e)}"
    
    async def close(self):
        """关闭HTTP会话"""
        if self.session and not self.session.closed:
            await self.session.close()

# 全局LLM适配器实例
_llm_adapter: Optional[LLMAdapter] = None

def get_llm_adapter() -> LLMAdapter:
    """获取全局LLM适配器实例"""
    global _llm_adapter
    if _llm_adapter is None:
        _llm_adapter = LLMAdapter()
    return _llm_adapter

async def get_response(prompt: str, temperature: float = 0.7) -> str:
    """便捷函数：直接调用LLM适配器"""
    llm_adapter = get_llm_adapter()
    return await llm_adapter.get_response(prompt, temperature)
