#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流式工具调用提取器
实时检测和提取AI输出中的工具调用，支持中英文括号
"""

import re
import json
import logging
import asyncio
import sys
import os
from typing import Callable, Optional, Dict, Any, Union

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from system.config import config, AI_NAME  # 导入配置系统
except ImportError:
    # 如果直接导入失败，尝试从父目录导入
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from system.config import config, AI_NAME

from .tool_call_utils import parse_tool_calls, execute_tool_calls

logger = logging.getLogger("StreamingToolCallExtractor")

class CallbackManager:
    """回调函数管理器 - 统一处理同步/异步回调"""
    
    def __init__(self):
        self.callbacks = {}
        self.callback_types = {}  # 缓存回调函数类型
    
    def register_callback(self, name: str, callback: Optional[Callable]):
        """注册回调函数"""
        self.callbacks[name] = callback
        if callback:
            # 缓存函数类型，避免重复检查
            self.callback_types[name] = asyncio.iscoroutinefunction(callback)
        else:
            self.callback_types[name] = False
    
    async def call_callback(self, name: str, *args, **kwargs):
        """统一调用回调函数"""
        callback = self.callbacks.get(name)
        if not callback:
            return None
            
        try:
            if self.callback_types.get(name, False):
                # 异步回调
                return await callback(*args, **kwargs)
            else:
                # 同步回调
                return callback(*args, **kwargs)
        except Exception as e:
            logger.error(f"回调函数 {name} 执行错误: {e}")
            return None

class StreamingToolCallExtractor:
    """流式工具调用提取器"""
    
    def __init__(self, mcp_manager=None):
        self.tool_call_buffer = ""  # 工具调用缓冲区
        self.is_in_tool_call = False  # 是否在工具调用中
        self.brace_count = 0  # 括号计数
        self.mcp_manager = mcp_manager
        self.text_buffer = ""  # 普通文本缓冲区
        self.sentence_endings = r"[。？！；\.\?\!\;]"  # 断句标点
        
        # 使用回调管理器
        self.callback_manager = CallbackManager()
        
        # 语音集成（可选）
        self.voice_integration = None
        
        # 工具调用队列（用于与工具调用循环通信）
        self.tool_calls_queue = None
        
    def set_callbacks(self, 
                     on_text_chunk: Optional[Callable] = None,
                     on_sentence: Optional[Callable] = None,
                     on_tool_result: Optional[Callable] = None,
                     voice_integration=None,
                     tool_calls_queue=None,
                     tool_call_detected_signal=None):
        """设置回调函数"""
        # 注册回调函数
        self.callback_manager.register_callback("text_chunk", on_text_chunk)
        self.callback_manager.register_callback("sentence", on_sentence)
        self.callback_manager.register_callback("tool_result", on_tool_result)
        
        self.voice_integration = voice_integration
        self.tool_calls_queue = tool_calls_queue
        self.tool_call_detected_signal = tool_call_detected_signal
    
    async def process_text_chunk(self, text_chunk: str):
        """处理文本块，分离普通文本和工具调用"""
        if not text_chunk:
            return None
            
        results = []
        
        for char in text_chunk:
            if char in '{｛':  # 检测到开始括号
                if not self.is_in_tool_call:
                    # 开始工具调用，先处理累积的普通文本
                    if self.text_buffer:
                        result = await self._flush_text_buffer()
                        if result:
                            results.append(result)
                    
                    self.is_in_tool_call = True
                    self.tool_call_buffer = char
                    self.brace_count = 1
                else:
                    # 嵌套括号
                    self.tool_call_buffer += char
                    self.brace_count += 1
                    
            elif char in '}｝':  # 检测到结束括号
                if self.is_in_tool_call:
                    self.tool_call_buffer += char
                    self.brace_count -= 1
                    
                    if self.brace_count == 0:  # 工具调用结束
                        # 提取完整的工具调用
                        tool_call = self.tool_call_buffer
                        self.tool_call_buffer = ""
                        self.is_in_tool_call = False
                        
                        # 处理工具调用 - 只提取，不执行
                        await self._extract_tool_call(tool_call)
                        
            else:  # 普通字符
                if self.is_in_tool_call:
                    self.tool_call_buffer += char
                else:
                    # 普通文本，累积到缓冲区
                    self.text_buffer += char
                    
                    # 检查是否形成完整句子
                    if re.search(self.sentence_endings, char):
                        # 提取完整句子
                        sentences = re.split(self.sentence_endings, self.text_buffer)
                        if len(sentences) > 1:
                            complete_sentence = sentences[0] + char  # 包含标点
                            if complete_sentence.strip():
                                # 发送文本块回调（用于前端显示）
                                result = await self.callback_manager.call_callback(
                                    "text_chunk", complete_sentence, "chunk"
                                )
                                if result:
                                    results.append(result)
                                
                                # 发送句子回调（用于其他处理）
                                await self.callback_manager.call_callback(
                                    "sentence", complete_sentence, "sentence"
                                )
                                
                                # 发送到语音集成（普通文本，非工具调用）
                                await self._send_to_voice_integration(complete_sentence)
                            
                            # 更新缓冲区，过滤空字符串
                            remaining_sentences = [s for s in sentences[1:] if s.strip()]
                            self.text_buffer = "".join(remaining_sentences)
        
        # 返回所有结果
        return results
    
    async def _flush_text_buffer(self):
        """刷新文本缓冲区"""
        if self.text_buffer:
            # 发送文本块
            result = await self.callback_manager.call_callback(
                "text_chunk", self.text_buffer, "chunk"
            )
            
            # 发送到语音集成（普通文本，非工具调用）
            await self._send_to_voice_integration(self.text_buffer)
            
            self.text_buffer = ""
            return result
        return None
    
    async def _send_to_voice_integration(self, text: str):
        """发送文本到语音集成"""
        if self.voice_integration:
            try:
                import threading
                threading.Thread(
                    target=self.voice_integration.receive_text_chunk,
                    args=(text,),
                    daemon=True
                ).start()
            except Exception as e:
                logger.error(f"语音集成错误: {e}")
    
    async def _extract_tool_call(self, tool_call_text: str):
        """提取工具调用 - 流式执行并反馈结果"""
        try:
            logger.info(f"检测到工具调用: {tool_call_text[:100]}...")
            
            # 发送工具调用开始信号
            await self.callback_manager.call_callback("tool_call", tool_call_text, "tool_call")
            
            # 解析JSON
            tool_calls = parse_tool_calls(tool_call_text)
            
            if tool_calls:
                logger.info(f"解析到 {len(tool_calls)} 个工具调用")
                
                # 流式执行工具调用
                for i, tool_call in enumerate(tool_calls):
                    try:
                        # 发送工具调用执行开始信号
                        await self.callback_manager.call_callback(
                            "tool_result", f"正在执行工具: {tool_call['name']}", "tool_start"
                        )
                        
                        # 执行工具调用
                        result = await self._execute_single_tool_call(tool_call)
                        
                        # 发送工具调用结果
                        await self.callback_manager.call_callback(
                            "tool_result", result, "tool_result"
                        )
                        
                    except Exception as e:
                        error_msg = f"工具 {tool_call['name']} 执行失败: {str(e)}"
                        logger.error(error_msg)
                        await self.callback_manager.call_callback(
                            "tool_result", error_msg, "tool_error"
                        )
                
            else:
                logger.warning("工具调用解析失败")
                await self.callback_manager.call_callback(
                    "tool_result", "工具调用解析失败", "tool_error"
                )
                
        except Exception as e:
            error_msg = f"工具调用提取失败: {str(e)}"
            logger.error(error_msg)
            await self.callback_manager.call_callback(
                "tool_result", error_msg, "tool_error"
            )
    
    async def _execute_single_tool_call(self, tool_call: dict) -> str:
        """执行单个工具调用 - 使用统一的工具调用执行函数"""
        from .tool_call_utils import execute_single_tool_call
        return await execute_single_tool_call(tool_call, self.mcp_manager)
    
    async def finish_processing(self):
        """完成处理，清理剩余内容"""
        results = []
        
        # 处理剩余的文本
        if self.text_buffer:
            result = await self._flush_text_buffer()
            if result:
                results.append(result)
        
        # 处理未完成的工具调用
        if self.is_in_tool_call and self.tool_call_buffer:
            logger.warning(f"检测到未完成的工具调用: {self.tool_call_buffer}")
            # 尝试解析未完成的工具调用
            try:
                await self._extract_tool_call(self.tool_call_buffer)
            except Exception as e:
                logger.error(f"处理未完成工具调用失败: {e}")
        
        return results if results else None
    
    def reset(self):
        """重置提取器状态"""
        self.tool_call_buffer = ""
        self.is_in_tool_call = False
        self.brace_count = 0
        self.text_buffer = ""

