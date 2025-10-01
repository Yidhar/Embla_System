#!/usr/bin/env python3
"""
LLM服务模块
提供统一的LLM调用接口，替代conversation_core.py中的get_response方法
"""

import logging
import sys
import os
from typing import Optional, Dict, Any

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nagaagent_core.core import AsyncOpenAI
from nagaagent_core.api import FastAPI, HTTPException
from system.config import config

# 配置日志
logger = logging.getLogger("LLMService")

class LLMService:
    """LLM服务类 - 提供统一的LLM调用接口"""
    
    def __init__(self):
        self.async_client: Optional[AsyncOpenAI] = None
        self._initialize_client()
    
    def _initialize_client(self):
        """初始化OpenAI客户端"""
        try:
            self.async_client = AsyncOpenAI(
                api_key=config.api.api_key, 
                base_url=config.api.base_url.rstrip('/') + '/'
            )
            logger.info("LLM服务客户端初始化成功")
        except Exception as e:
            logger.error(f"LLM服务客户端初始化失败: {e}")
            self.async_client = None
    
    async def get_response(self, prompt: str, temperature: float = 0.7) -> str:
        """为其他模块提供API调用接口"""
        if not self.async_client:
            self._initialize_client()
            if not self.async_client:
                return f"LLM服务不可用: 客户端初始化失败"
        
        try:
            response = await self.async_client.chat.completions.create(
                model=config.api.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=config.api.max_tokens
            )
            return response.choices[0].message.content
        except RuntimeError as e:
            if "handler is closed" in str(e):
                logger.debug(f"忽略连接关闭异常，重新创建客户端: {e}")
                # 重新创建客户端并重试
                self._initialize_client()
                if self.async_client:
                    response = await self.async_client.chat.completions.create(
                        model=config.api.model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=temperature,
                        max_tokens=config.api.max_tokens
                    )
                    return response.choices[0].message.content
                else:
                    return f"LLM服务不可用: 重连失败"
            else:
                logger.error(f"API调用失败: {e}")
                return f"API调用出错: {str(e)}"
        except Exception as e:
            logger.error(f"API调用失败: {e}")
            return f"API调用出错: {str(e)}"
    
    def is_available(self) -> bool:
        """检查LLM服务是否可用"""
        return self.async_client is not None

# 全局LLM服务实例
_llm_service: Optional[LLMService] = None

def get_llm_service() -> LLMService:
    """获取全局LLM服务实例"""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service

# 创建独立的LLM服务API
llm_app = FastAPI(
    title="LLM Service API",
    description="LLM服务API",
    version="1.0.0"
)

@llm_app.post("/llm/chat")
async def llm_chat(request: Dict[str, Any]):
    """LLM聊天接口 - 为其他模块提供LLM调用服务"""
    try:
        prompt = request.get("prompt", "")
        temperature = request.get("temperature", 0.7)
        
        if not prompt:
            raise HTTPException(status_code=400, detail="prompt参数不能为空")
        
        llm_service = get_llm_service()
        response = await llm_service.get_response(prompt, temperature)
        
        return {
            "status": "success",
            "response": response,
            "temperature": temperature
        }
        
    except Exception as e:
        logger.error(f"LLM聊天接口异常: {e}")
        raise HTTPException(status_code=500, detail=f"LLM服务异常: {str(e)}")

