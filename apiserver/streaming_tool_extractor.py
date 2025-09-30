#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流式文本切割器
负责将LLM流式输出按句切割并发送给语音集成（TTS）。不再检测或处理工具调用。
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

# 工具调用解析/执行已不再需要

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
    """流式文本切割器（仅TTS）"""
    
    def __init__(self, mcp_manager=None):
        self.mcp_manager = mcp_manager
        self.text_buffer = ""  # 普通文本缓冲区
        self.sentence_endings = r"[。？！；\.\?\!\;]"  # 断句标点
        
        # 使用回调管理器
        self.callback_manager = CallbackManager()
        
        # 语音集成（可选）
        self.voice_integration = None
        
        # 工具调用相关已移除
        self.tool_calls_queue = None
        
    def set_callbacks(self, 
                     on_text_chunk: Optional[Callable] = None,
                     voice_integration=None):
        """设置回调函数"""
        # 注册回调函数（仅文本块）
        self.callback_manager.register_callback("text_chunk", on_text_chunk)
        self.voice_integration = voice_integration
    
    async def process_text_chunk(self, text_chunk: str):
        """处理文本块，仅进行文本积累与按句切割并发送给语音集成"""
        if not text_chunk:
            return None
            
        # 仅按句切割并发送到TTS，不再向前端返回分句事件
        for char in text_chunk:
            self.text_buffer += char
            if re.search(self.sentence_endings, char):
                sentences = re.split(self.sentence_endings, self.text_buffer)
                if len(sentences) > 1:
                    complete_sentence = sentences[0] + char
                    if complete_sentence.strip():
                        await self._send_to_voice_integration(complete_sentence)
                    remaining_sentences = [s for s in sentences[1:] if s.strip()]
                    self.text_buffer = "".join(remaining_sentences)
        return None
    
    async def _flush_text_buffer(self):
        """刷新文本缓冲区"""
        if self.text_buffer:
            # 发送到语音集成（普通文本，非工具调用）
            await self._send_to_voice_integration(self.text_buffer)
            
            self.text_buffer = ""
            return None
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
    
    # 工具调用相关方法已移除
    
    async def finish_processing(self):
        """完成处理，清理剩余内容"""
        results = []
        
        # 处理剩余的文本
        if self.text_buffer:
            result = await self._flush_text_buffer()
            if result:
                results.append(result)
        
        return results if results else None
    
    def reset(self):
        """重置提取器状态"""
        self.text_buffer = ""

