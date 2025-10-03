# -*- coding: utf-8 -*-
"""
语音输入模块
包含本地语音集成、统一语音管理器等核心功能
"""

from .unified_voice_manager import UnifiedVoiceManager, VoiceMode
from .voice_thread_safe_simple import ThreadSafeVoiceIntegration

__all__ = [
    'UnifiedVoiceManager', 
    'VoiceMode',
    'ThreadSafeVoiceIntegration'
]
