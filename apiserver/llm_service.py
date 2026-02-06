#!/usr/bin/env python3
"""
LLM服务模块
提供统一的LLM调用接口，替代conversation_core.py中的get_response方法
"""

import logging
import sys
import os
import asyncio
from typing import Optional, Dict, Any, List

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
    
    async def chat_with_context(self, messages: List[Dict], temperature: float = 0.7) -> str:
        """带上下文的聊天调用"""
        if not self.async_client:
            self._initialize_client()
            if not self.async_client:
                return f"LLM服务不可用: 客户端初始化失败"
        
        try:
            response = await self.async_client.chat.completions.create(
                model=config.api.model,
                messages=messages,
                temperature=temperature,
                max_tokens=config.api.max_tokens
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"上下文聊天调用失败: {e}")
            return f"聊天调用出错: {str(e)}"
    
    async def stream_chat_with_context(self, messages: List[Dict], temperature: float = 0.7):
        """带上下文的流式聊天调用"""
        if not self.async_client:
            self._initialize_client()
            if not self.async_client:
                yield f"data: error:LLM服务不可用: 客户端初始化失败\n\n"
                return

        try:
            import aiohttp
            import json
            import base64
            import codecs

            # 流式操作：无总超时，缩短读取超时避免僵死连接
            timeout = aiohttp.ClientTimeout(total=None, connect=60, sock_read=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                try:
                    async with session.post(
                        f"{config.api.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {config.api.api_key}",
                            "Content-Type": "application/json",
                            "Accept": "text/event-stream",
                            "Connection": "keep-alive"
                        },
                        json={
                            "model": config.api.model,
                            "messages": messages,
                            "temperature": temperature,
                            "max_tokens": config.api.max_tokens,
                            "stream": True
                        }
                    ) as resp:
                        if resp.status != 200:
                            error_detail = await resp.text()
                            logger.error(f"LLM API 错误详情: {error_detail}")
                            yield f"data: error:LLM API调用失败 (状态码: {resp.status})\n\n"
                            return

                        # 标记是否已收到 [DONE] 消息
                        received_done = False
                        # 字节缓冲区，用于处理可能被截断的 UTF-8 多字节字符
                        byte_buffer = b""
                        # 文本缓冲区，用于处理分块的 SSE 行
                        text_buffer = ""
                        # UTF-8 增量解码器，正确处理多字节字符
                        utf8_decoder = codecs.getincrementaldecoder('utf-8')('replace')

                        async for chunk in resp.content.iter_chunked(1024):
                            if not chunk:
                                break

                            # 如果已经收到 [DONE]，停止处理
                            if received_done:
                                break

                            # 累积字节数据
                            byte_buffer += chunk

                            # 使用增量解码器处理，正确处理被截断的多字节字符
                            try:
                                decoded_text = utf8_decoder.decode(byte_buffer, final=False)
                                byte_buffer = b""  # 成功解码后清空字节缓冲区
                            except Exception as decode_err:
                                # 解码出错时记录日志，使用 replace 模式继续
                                logger.debug(f"UTF-8 增量解码异常: {decode_err}")
                                decoded_text = byte_buffer.decode('utf-8', errors='replace')
                                byte_buffer = b""

                            text_buffer += decoded_text

                            # 处理每一行
                            lines = text_buffer.split('\n')
                            # 保留最后一行（可能不完整）
                            text_buffer = lines[-1] if lines else ""

                            for line in lines[:-1]:
                                line = line.strip()
                                if not line:
                                    continue

                                if line.startswith('data: '):
                                    data_str = line[6:]
                                    if data_str == '[DONE]':
                                        received_done = True
                                        # 发送 [DONE] 信号，统一在此处理
                                        yield "data: [DONE]\n\n"
                                        return

                                    # 只解析非空数据
                                    if not data_str:
                                        continue

                                    try:
                                        data = json.loads(data_str)
                                        if 'choices' in data and len(data['choices']) > 0:
                                            delta = data['choices'][0].get('delta', {})
                                            if 'content' in delta and delta['content'] is not None:
                                                content = delta['content']
                                                b64 = base64.b64encode(content.encode('utf-8')).decode('ascii')
                                                yield f"data: {b64}\n\n"
                                    except json.JSONDecodeError as json_err:
                                        # 记录 JSON 解析失败，便于调试
                                        # 注意：不完整的 JSON 是正常的，因为数据可能分块接收
                                        if len(data_str) > 50:
                                            # 超过50字符仍解析失败，可能是真正的错误
                                            logger.warning(f"JSON 解析失败 (长度={len(data_str)}): {data_str[:100]}...")
                                        else:
                                            logger.debug(f"JSON 解析失败 (可能不完整): {data_str}")

                        # 处理剩余的文本缓冲区（如果有完整的行）
                        if text_buffer.strip():
                            line = text_buffer.strip()
                            if line.startswith('data: '):
                                data_str = line[6:]
                                if data_str == '[DONE]':
                                    yield "data: [DONE]\n\n"
                                elif data_str:
                                    try:
                                        data = json.loads(data_str)
                                        if 'choices' in data and len(data['choices']) > 0:
                                            delta = data['choices'][0].get('delta', {})
                                            if 'content' in delta and delta['content'] is not None:
                                                content = delta['content']
                                                b64 = base64.b64encode(content.encode('utf-8')).decode('ascii')
                                                yield f"data: {b64}\n\n"
                                    except json.JSONDecodeError:
                                        logger.debug(f"最终缓冲区 JSON 解析失败: {data_str}")

                        # 如果循环正常结束但没收到 [DONE]，也发送一个
                        if not received_done:
                            yield "data: [DONE]\n\n"

                except aiohttp.client_exceptions.ClientConnectionError as conn_err:
                    logger.error(f"网络连接失败: {conn_err}")
                    yield f"data: error:网络连接失败\n\n"
                    return
                except aiohttp.client_exceptions.ServerDisconnectedError as disc_err:
                    logger.error(f"服务器连接断开: {disc_err}")
                    yield f"data: error:服务器连接已断开\n\n"
                    return
                except asyncio.TimeoutError:
                    logger.error("流式读取超时")
                    yield f"data: error:读取超时\n\n"
                    return
        except Exception as e:
            logger.error(f"流式聊天调用失败: {e}")
            yield f"data: error:流式调用出错: {str(e)}\n\n"

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

