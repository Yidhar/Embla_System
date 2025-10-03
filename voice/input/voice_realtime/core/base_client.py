#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
语音客户端基类
定义所有语音客户端的通用接口
"""

from abc import ABC, abstractmethod
from typing import Optional, Callable, Dict, Any
import logging

logger = logging.getLogger(__name__)


class BaseVoiceClient(ABC):
    """
    语音客户端基类
    所有提供商的语音客户端都必须继承此类
    """

    def __init__(self, api_key: str, **kwargs):
        """
        初始化客户端

        参数:
            api_key: API密钥
            **kwargs: 其他提供商特定的参数
        """
        self.api_key = api_key
        self.debug = kwargs.get('debug', False)

        # 回调函数
        self.on_user_text_callback: Optional[Callable[[str], None]] = None
        self.on_text_callback: Optional[Callable[[str], None]] = None
        self.on_response_complete_callback: Optional[Callable[[], None]] = None
        self.on_status_callback: Optional[Callable[[str], None]] = None
        self.on_error_callback: Optional[Callable[[Exception], None]] = None

        # 设置日志级别
        if self.debug:
            logging.basicConfig(level=logging.DEBUG)
            logger.setLevel(logging.DEBUG)

    def set_callbacks(
        self,
        on_user_text: Optional[Callable[[str], None]] = None,
        on_text: Optional[Callable[[str], None]] = None,
        on_response_complete: Optional[Callable[[], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None
    ):
        """
        设置回调函数

        参数:
            on_user_text: 用户语音识别文本回调 (text: str) -> None
            on_text: AI文本响应回调 (text: str) -> None
            on_response_complete: 响应完成回调 () -> None
            on_status: 状态变化回调 (status: str) -> None
                可能的状态: 'connected', 'disconnected', 'listening',
                          'processing', 'ai_speaking', 'cooldown', 'error'
            on_error: 错误回调 (error: Exception) -> None
        """
        if on_user_text:
            self.on_user_text_callback = on_user_text
        if on_text:
            self.on_text_callback = on_text
        if on_response_complete:
            self.on_response_complete_callback = on_response_complete
        if on_status:
            self.on_status_callback = on_status
        if on_error:
            self.on_error_callback = on_error

        logger.debug(f"Callbacks set: user_text={bool(on_user_text)}, "
                    f"text={bool(on_text)}, complete={bool(on_response_complete)}, "
                    f"status={bool(on_status)}, error={bool(on_error)}")

    @abstractmethod
    def connect(self) -> bool:
        """
        建立连接

        返回:
            bool: 连接是否成功
        """
        pass

    @abstractmethod
    def disconnect(self):
        """
        断开连接
        """
        pass

    @abstractmethod
    def is_active(self) -> bool:
        """
        检查客户端是否活跃

        返回:
            bool: 是否活跃
        """
        pass

    @abstractmethod
    def manual_interrupt(self) -> bool:
        """
        手动打断AI说话

        返回:
            bool: 是否成功打断
        """
        pass

    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        """
        获取客户端状态

        返回:
            Dict: 状态信息字典
        """
        pass

    def update_config(self, config: Dict[str, Any]):
        """
        更新配置（可选实现）

        参数:
            config: 配置字典
        """
        for key, value in config.items():
            if hasattr(self, key):
                setattr(self, key, value)
                logger.debug(f"Updated config: {key}={value}")

    def _trigger_error(self, error: Exception):
        """
        触发错误回调的辅助方法

        参数:
            error: 异常对象
        """
        logger.error(f"Error occurred: {error}")
        if self.on_error_callback:
            try:
                self.on_error_callback(error)
            except Exception as e:
                logger.error(f"Error in error callback: {e}")

    def _trigger_status(self, status: str):
        """
        触发状态回调的辅助方法

        参数:
            status: 状态字符串
        """
        logger.debug(f"Status changed: {status}")
        if self.on_status_callback:
            try:
                self.on_status_callback(status)
            except Exception as e:
                logger.error(f"Error in status callback: {e}")