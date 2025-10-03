#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
适配器模块
包含各种语音服务提供商的适配器
"""

from .qwen_adapter import QwenVoiceClientAdapter
from .openai_adapter import OpenAIVoiceClientAdapter

__all__ = [
    'QwenVoiceClientAdapter',
    'OpenAIVoiceClientAdapter',
]