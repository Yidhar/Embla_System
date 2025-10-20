#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Live2D动画系统（精简版）
负责Live2D模型的动画控制
"""

import time
import math
import random
import logging
from typing import Optional, Dict

logger = logging.getLogger("live2d.animator")


class BlinkAnimator:
    """眨眼动画器"""

    def __init__(self, min_interval: float = 2.0, max_interval: float = 4.0):
        """初始化眨眼动画器"""
        self.min_interval = min_interval
        self.max_interval = max_interval
        self.last_blink_time = time.time()
        self.next_blink_interval = random.uniform(min_interval, max_interval)

    def update(self) -> Dict[str, float]:
        """更新眨眼状态"""
        current_time = time.time()

        # 检查是否该眨眼了
        if current_time - self.last_blink_time >= self.next_blink_interval:
            self.last_blink_time = current_time
            self.next_blink_interval = random.uniform(self.min_interval, self.max_interval)

        # 计算眨眼动画
        time_since_blink = current_time - self.last_blink_time
        if time_since_blink < 0.1:  # 眨眼持续0.1秒
            blink_progress = time_since_blink / 0.1
            eye_close = math.sin(blink_progress * math.pi)
            return {
                "ParamEyeLOpen": 1.0 - eye_close,
                "ParamEyeROpen": 1.0 - eye_close
            }

        return {"ParamEyeLOpen": 1.0, "ParamEyeROpen": 1.0}


class EyeTrackingAnimator:
    """眼球追踪动画器"""

    def __init__(self):
        """初始化眼球追踪"""
        self.target_x = 0.0
        self.target_y = 0.0
        self.current_x = 0.0
        self.current_y = 0.0

    def set_target(self, x: float, y: float):
        """设置追踪目标"""
        self.target_x = max(-1.0, min(1.0, x))
        self.target_y = max(-1.0, min(1.0, y))

    def update(self) -> Dict[str, float]:
        """更新眼球位置（简单平滑）"""
        # 简单的线性插值平滑
        smooth_factor = 0.1
        self.current_x += (self.target_x - self.current_x) * smooth_factor
        self.current_y += (self.target_y - self.current_y) * smooth_factor

        return {
            "ParamEyeBallX": self.current_x * 0.5,  # 限制移动范围
            "ParamEyeBallY": self.current_y * 0.5
        }


class BreathAnimator:
    """呼吸动画器"""

    def __init__(self):
        """初始化呼吸动画"""
        self.start_time = time.time()

    def update(self) -> Dict[str, float]:
        """更新呼吸动画"""
        current_time = time.time()
        breath = math.sin((current_time - self.start_time) * 1.0) * 0.5

        return {
            "ParamBreath": breath,
            "ParamBodyAngleX": breath * 0.05  # 轻微的身体摆动
        }


class EmotionAnimator:
    """情绪动画器"""

    def __init__(self):
        """初始化情绪动画"""
        self.current_emotion = "neutral"
        self.emotion_intensity = 0.0

        # 预定义表情参数
        self.emotions = {
            "neutral": {},
            "happy": {"ParamMouthForm": 1.0},
            "sad": {"ParamMouthForm": -1.0},
            "angry": {"ParamMouthForm": -0.5},
            "surprised": {"ParamMouthOpenY": 0.8}
        }

    def set_emotion(self, emotion: str, intensity: float = 1.0):
        """设置情绪"""
        if emotion in self.emotions:
            self.current_emotion = emotion
            self.emotion_intensity = max(0.0, min(1.0, intensity))

    def update(self) -> Dict[str, float]:
        """更新情绪参数"""
        if self.current_emotion == "neutral":
            return {}

        params = self.emotions.get(self.current_emotion, {}).copy()

        # 应用强度
        for key in params:
            params[key] *= self.emotion_intensity

        return params


class Live2DAnimator:
    """Live2D动画管理器（精简版）"""

    def __init__(self, renderer):
        """初始化动画管理器"""
        self.renderer = renderer

        # 创建动画器
        self.blink = BlinkAnimator()
        self.eye_tracking = EyeTrackingAnimator()
        self.breath = BreathAnimator()
        self.emotion = EmotionAnimator()

        # 参数缓存 - 用于差异化更新
        self._previous_params = {}
        self._param_threshold = 0.001  # 参数变化阈值

        logger.info("Live2D动画管理器初始化完成")

    def update(self):
        """更新所有动画 - 优化版，只更新变化的参数"""
        if not self.renderer or not self.renderer.has_model():
            return

        try:
            # 收集所有参数
            all_params = {}

            # 更新各个动画器
            all_params.update(self.blink.update())
            all_params.update(self.eye_tracking.update())
            all_params.update(self.breath.update())
            all_params.update(self.emotion.update())

            # 差异化更新 - 只应用变化的参数
            params_to_update = {}
            for param_id, value in all_params.items():
                # 检查参数是否有显著变化
                if param_id not in self._previous_params:
                    # 新参数，需要更新
                    params_to_update[param_id] = value
                    self._previous_params[param_id] = value
                elif abs(self._previous_params[param_id] - value) > self._param_threshold:
                    # 参数有显著变化，需要更新
                    params_to_update[param_id] = value
                    self._previous_params[param_id] = value

            # 只更新变化的参数
            if params_to_update:
                for param_id, value in params_to_update.items():
                    self.renderer.set_parameter(param_id, value)

        except Exception as e:
            logger.error(f"动画更新失败: {e}")

    def set_emotion(self, emotion: str, intensity: float = 1.0):
        """设置情绪"""
        self.emotion.set_emotion(emotion, intensity)
        # 清除相关参数缓存，确保情绪变化立即生效
        emotion_params = self.emotion.emotions.get(emotion, {})
        for param_id in emotion_params:
            if param_id in self._previous_params:
                del self._previous_params[param_id]

    def set_eye_target(self, x: float, y: float):
        """设置眼球追踪目标"""
        self.eye_tracking.set_target(x, y)

    def reset_cache(self):
        """重置参数缓存"""
        self._previous_params.clear()

    def cleanup(self):
        """清理资源"""
        self._previous_params.clear()
        self.renderer = None
        logger.info("动画管理器已清理")


def create_animator_from_config(renderer, config_manager=None):
    """从配置创建动画管理器（简化版）"""
    # 直接创建默认动画管理器
    return Live2DAnimator(renderer)