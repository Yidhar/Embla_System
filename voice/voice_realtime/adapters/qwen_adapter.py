#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
通义千问实时语音适配器
支持阿里巴巴通义千问的实时语音交互
"""

import logging
from typing import Optional

from ..core.base_client import BaseVoiceClient
from .qwen.client import QwenVoiceClientRefactored

logger = logging.getLogger(__name__)


class QwenVoiceClientAdapter(BaseVoiceClient):
    """
    通义千问语音客户端适配器
    桥接通义千问的实时语音服务到统一接口
    """

    # 默认配置
    DEFAULT_MODEL = 'qwen3-omni-flash-realtime'
    DEFAULT_VOICE = 'Cherry'

    def __init__(
        self,
        api_key: str,
        model: Optional[str] = None,
        voice: Optional[str] = None,
        use_voice_prompt: bool = True,  # 添加语音提示词参数
        **kwargs
    ):
        """
        初始化通义千问适配器

        参数:
            api_key: DashScope API密钥
            model: 模型名称（默认: qwen3-omni-flash-realtime）
            voice: 语音角色（默认: Cherry）
                可选: Cherry, Dingding, Maimai, Shasha, Tongtong, Qingqing
            **kwargs: 其他参数
        """
        super().__init__(api_key, **kwargs)

        self.model = model or self.DEFAULT_MODEL
        self.voice = voice or self.DEFAULT_VOICE
        self.use_voice_prompt = use_voice_prompt  # 保存语音提示词设置

        # 创建底层客户端
        self._client = QwenVoiceClientRefactored(
            api_key=api_key,
            model=self.model,
            voice=self.voice,
            debug=self.debug,
            use_voice_prompt=self.use_voice_prompt  # 传递语音提示词设置
        )

        # 桥接回调
        self._setup_callbacks()

        logger.info(f"QwenVoiceClientAdapter initialized: model={self.model}, voice={self.voice}")

    def _setup_callbacks(self):
        """设置回调桥接"""
        # 将基类的回调桥接到底层客户端
        def user_text_bridge(text):
            if self.on_user_text_callback:
                self.on_user_text_callback(text)

        def ai_text_bridge(text):
            if self.on_text_callback:
                self.on_text_callback(text)

        def response_complete_bridge():
            if self.on_response_complete_callback:
                self.on_response_complete_callback()

        def status_bridge(status):
            if self.on_status_callback:
                self.on_status_callback(status)

        self._client.on_user_text_callback = user_text_bridge
        self._client.on_text_callback = ai_text_bridge
        self._client.on_response_complete_callback = response_complete_bridge
        self._client.on_status_callback = status_bridge

        logger.debug("Callbacks bridged successfully")

    def connect(self) -> bool:
        """
        建立连接

        返回:
            bool: 连接是否成功
        """
        try:
            # 确认配置
            if hasattr(self._client, 'config'):
                # 从系统配置读取auto_reconnect设置
                self._client.config['auto_reconnect'] = False  # 默认禁用自动重连

                logger.info(f"Connecting with config: auto_reconnect={self._client.config.get('auto_reconnect')}")

            self._client.connect()
            self._trigger_status('connected')
            return True
        except Exception as e:
            self._trigger_error(e)
            return False

    def disconnect(self):
        """断开连接"""
        try:
            # 确保禁用自动重连
            if hasattr(self._client, 'config'):
                self._client.config['auto_reconnect'] = False

            self._client.disconnect()
            self._trigger_status('disconnected')
            logger.info("QwenVoiceClientAdapter disconnected")
        except Exception as e:
            self._trigger_error(e)

    def is_active(self) -> bool:
        """检查客户端是否活跃"""
        return self._client.is_active() if hasattr(self._client, 'is_active') else False

    def manual_interrupt(self) -> bool:
        """手动打断AI说话"""
        try:
            if hasattr(self._client, 'manual_interrupt'):
                return self._client.manual_interrupt()
            return False
        except Exception as e:
            self._trigger_error(e)
            return False

    def get_status(self) -> dict:
        """获取客户端状态"""
        try:
            if hasattr(self._client, 'get_status'):
                return self._client.get_status()
            return {'active': False}
        except Exception as e:
            self._trigger_error(e)
            return {'active': False, 'error': str(e)}

    def set_callbacks(self, **kwargs):
        """重载设置回调函数"""
        super().set_callbacks(**kwargs)
        # 重新桥接回调
        self._setup_callbacks()

    @property
    def audio_manager(self):
        """暴露底层客户端的音频管理器（如果有）"""
        return self._client.audio_manager if hasattr(self._client, 'audio_manager') else None

    @property
    def state_manager(self):
        """暴露底层客户端的状态管理器（如果有）"""
        return self._client.state_manager if hasattr(self._client, 'state_manager') else None