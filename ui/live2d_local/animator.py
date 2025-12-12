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


class LipSyncAnimator:
    """嘴部同步动画器 - 基于音频音量驱动，支持音素识别和情感表情"""
    
    def __init__(self):
        """初始化嘴部同步"""
        self.current_volume = 0.0  # 当前音量 (0.0-1.0)
        self.target_mouth_open = 0.0  # 目标嘴部张开度
        self.current_mouth_open = 0.0  # 当前嘴部张开度
        self.target_mouth_form = 0.0  # 目标嘴部形状 (-1.0 到 1.0)
        self.current_mouth_form = 0.0  # 当前嘴部形状
        self.target_mouth_smile = 0.0  # 目标嘴部微笑度
        self.current_mouth_smile = 0.0  # 当前嘴部微笑度
        self.target_eye_brow = 0.0  # 目标眉毛位置
        self.current_eye_brow = 0.0  # 当前眉毛位置
        self.target_eye_wide = 0.0  # 目标眼睛睁大度
        self.current_eye_wide = 0.0  # 当前眼睛睁大度
        self.smooth_factor = 0.3  # 平滑系数
        self.form_smooth_factor = 0.25  # 嘴形平滑系数（稍慢以避免抖动）
        self.volume_threshold = 0.01  # 音量阈值（低于此值视为静音）
        self.volume_scale = 1.5  # 音量放大系数
        self.is_speaking = False  # 是否正在说话
        
    def set_audio_volume(self, volume: float):
        """设置当前音频音量
        
        Args:
            volume: 音量值 (0.0-1.0)
        """
        self.current_volume = max(0.0, min(1.0, volume))
        self.is_speaking = self.current_volume > self.volume_threshold
        
        # 计算目标嘴部张开度（非线性映射，让动画更自然）
        if self.is_speaking:
            # 使用平方根函数让小音量也有明显的嘴部动作
            normalized_volume = min(1.0, self.current_volume * self.volume_scale)
            self.target_mouth_open = math.sqrt(normalized_volume)
        else:
            self.target_mouth_open = 0.0
    
    def set_mouth_form(self, form: float):
        """设置嘴部形状参数（用于音素识别）
        
        Args:
            form: 嘴形参数 (-1.0 到 1.0)
                 -1.0 = 'i' 音（嘴角拉宽）
                  0.0 = 'e' 音（中性）
                  1.0 = 'u' 音（嘴唇撮起）
        """
        self.target_mouth_form = max(-1.0, min(1.0, form))
    
    def start_speaking(self):
        """开始说话（手动触发）"""
        self.is_speaking = True
        logger.debug("嘴部同步：开始说话")
        
    def stop_speaking(self):
        """停止说话（手动触发）"""
        self.is_speaking = False
        self.target_mouth_open = 0.0
        logger.debug("嘴部同步：停止说话")
    
    def update(self) -> Dict[str, float]:
        """更新嘴部和表情动画"""
        # 平滑过渡到目标值（张开度）
        self.current_mouth_open += (
            (self.target_mouth_open - self.current_mouth_open) * self.smooth_factor
        )
        
        # 平滑过渡到目标值（嘴形）
        self.current_mouth_form += (
            (self.target_mouth_form - self.current_mouth_form) * self.form_smooth_factor
        )
        
        # 平滑过渡到目标值（微笑）
        self.current_mouth_smile += (
            (self.target_mouth_smile - self.current_mouth_smile) * self.form_smooth_factor
        )
        
        # 平滑过渡到目标值（眉毛）
        self.current_eye_brow += (
            (self.target_eye_brow - self.current_eye_brow) * 0.2
        )
        
        # 平滑过渡到目标值（眼睛）
        self.current_eye_wide += (
            (self.target_eye_wide - self.current_eye_wide) * 0.25
        )
        
        # 返回Live2D参数
        params = {
            "ParamMouthOpenY": self.current_mouth_open,  # 嘴部张开（Y轴，垂直）
            "ParamMouthForm": self.current_mouth_form,  # 嘴型变化（横向）
        }
        
        # 添加扩展参数（如果有值）
        if abs(self.current_mouth_smile) > 0.01:
            params["ParamMouthSmile"] = self.current_mouth_smile
        
        if abs(self.current_eye_brow) > 0.01:
            params["ParamBrowLY"] = self.current_eye_brow
            params["ParamBrowRY"] = self.current_eye_brow
        
        if abs(self.current_eye_wide) > 0.01:
            # 眼睛睁大时，需要增加眼睛开度
            params["ParamEyeLOpen"] = min(1.0, 1.0 + self.current_eye_wide)
            params["ParamEyeROpen"] = min(1.0, 1.0 + self.current_eye_wide)
        
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
        self.lip_sync = LipSyncAnimator()  # 新增嘴部同步动画器

        # 参数缓存 - 用于差异化更新
        self._previous_params = {}
        self._param_threshold = 0.001  # 参数变化阈值

        logger.debug("Live2D动画管理器初始化完成（包含嘴部同步）")

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
            all_params.update(self.lip_sync.update())  # 新增嘴部同步更新

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
    
    def set_audio_volume(self, volume: float):
        """设置音频音量（供外部调用，用于驱动嘴部动画）
        
        Args:
            volume: 音量值 (0.0-1.0)
        """
        if self.lip_sync:
            self.lip_sync.set_audio_volume(volume)
    
    def set_mouth_form(self, form: float):
        """设置嘴部形状参数（供外部调用，用于音素识别）
        
        Args:
            form: 嘴形参数 (-1.0 到 1.0)
        """
        if self.lip_sync:
            self.lip_sync.set_mouth_form(form)
    
    def set_mouth_smile(self, smile: float):
        """设置嘴部微笑度（供外部调用，用于情感表情）
        
        Args:
            smile: 微笑度 (-1.0 到 1.0)
        """
        if self.lip_sync:
            self.lip_sync.target_mouth_smile = max(-1.0, min(1.0, smile))
    
    def set_eye_brow(self, position: float):
        """设置眉毛位置（供外部调用，用于情感表情）
        
        Args:
            position: 眉毛位置 (-1.0 到 1.0)，正值向上
        """
        if self.lip_sync:
            self.lip_sync.target_eye_brow = max(-1.0, min(1.0, position))
    
    def set_eye_wide(self, wide: float):
        """设置眼睛睁大度（供外部调用，用于情感表情）
        
        Args:
            wide: 睁大度 (0.0 到 1.0)
        """
        if self.lip_sync:
            self.lip_sync.target_eye_wide = max(0.0, min(1.0, wide))
    
    def start_speaking(self):
        """开始说话（手动触发嘴部动画）"""
        if self.lip_sync:
            self.lip_sync.start_speaking()
    
    def stop_speaking(self):
        """停止说话（关闭嘴部动画）"""
        if self.lip_sync:
            self.lip_sync.stop_speaking()

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