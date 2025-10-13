#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Live2D动画系统
负责Live2D模型的动画控制，包括眨眼、眼球跟踪、身体摆动等
"""

import time
import math
import random
from typing import Dict, List, Optional

# 尝试导入噪声生成模块
try:
    import opensimplex as noise
    NOISE_AVAILABLE = True
except Exception:
    NOISE_AVAILABLE = False
    print("⚠️ opensimplex不可用(可能是 numba/llvmlite 初始化失败)，动画将使用简化模式")

class BaseAnimator:
    """基础动画器类"""
    
    def __init__(self, weight: float = 1.0):
        self.weight = weight
        self.start_time = time.time()
        self.enabled = True
    
    def update(self, renderer) -> Dict[str, float]:
        """更新动画参数"""
        if not self.enabled:
            return {}
        return self._calculate_parameters(renderer)
    
    def _calculate_parameters(self, renderer) -> Dict[str, float]:
        """计算动画参数 - 子类需要实现"""
        return {}
    
    def enable(self):
        """启用动画"""
        self.enabled = True
    
    def disable(self):
        """禁用动画"""
        self.enabled = False

class BlinkAnimator(BaseAnimator):
    """眨眼动画器"""
    
    def __init__(self, weight: float = 1.0):
        super().__init__(weight)
        self.blink_interval = random.uniform(2.0, 4.0)  # 眨眼间隔
        self.last_blink_time = time.time()
        self.blink_duration = 0.1  # 眨眼持续时间
    
    def _calculate_parameters(self, renderer) -> Dict[str, float]:
        current_time = time.time()
        
        # 检查是否需要眨眼
        if current_time - self.last_blink_time >= self.blink_interval:
            self.last_blink_time = current_time
            self.blink_interval = random.uniform(2.0, 4.0)  # 随机下次眨眼时间
        
        # 计算眨眼状态
        time_since_blink = current_time - self.last_blink_time
        if time_since_blink < self.blink_duration:
            # 眨眼过程中
            blink_progress = time_since_blink / self.blink_duration
            eye_close = math.sin(blink_progress * math.pi) * self.weight
            return {"ParamEyeLOpen": 1.0 - eye_close, "ParamEyeROpen": 1.0 - eye_close}
        
        return {"ParamEyeLOpen": 1.0, "ParamEyeROpen": 1.0}

class EyeBallAnimator(BaseAnimator):
    """眼球跟踪动画器"""
    
    def __init__(self, weight: float = 0.5):
        super().__init__(weight)
        self.target_x = 0.0
        self.target_y = 0.0
        self.current_x = 0.0
        self.current_y = 0.0
        self.smooth_factor = 0.1  # 平滑因子
    
    def set_target(self, x: float, y: float):
        """设置眼球跟踪目标"""
        self.target_x = max(-1.0, min(1.0, x))
        self.target_y = max(-1.0, min(1.0, y))
    
    def _calculate_parameters(self, renderer) -> Dict[str, float]:
        # 平滑移动到目标位置
        self.current_x += (self.target_x - self.current_x) * self.smooth_factor
        self.current_y += (self.target_y - self.current_y) * self.smooth_factor
        
        return {
            "ParamEyeBallX": self.current_x * self.weight,
            "ParamEyeBallY": self.current_y * self.weight
        }

class BodyAngleAnimator(BaseAnimator):
    """身体角度动画器"""
    
    def __init__(self, weight: float = 0.3):
        super().__init__(weight)
        self.base_angle = 0.0
        self.angle_range = 0.1  # 角度变化范围
    
    def _calculate_parameters(self, renderer) -> Dict[str, float]:
        if not NOISE_AVAILABLE:
            # 简化模式：使用正弦波
            current_time = time.time()
            angle = math.sin(current_time * 0.5) * self.angle_range * self.weight
        else:
            # 使用噪声生成更自然的摆动
            current_time = time.time()
            angle = noise.noise2(current_time * 0.3, 0) * self.angle_range * self.weight
        
        return {"ParamAngleX": self.base_angle + angle}

class BreathAnimator(BaseAnimator):
    """呼吸动画器"""
    
    def __init__(self, weight: float = 0.5):
        super().__init__(weight)
        self.breath_speed = 1.0  # 呼吸速度
    
    def _calculate_parameters(self, renderer) -> Dict[str, float]:
        current_time = time.time()
        breath = math.sin(current_time * self.breath_speed) * self.weight
        
        return {
            "ParamBreath": breath,
            "ParamBodyAngleX": breath * 0.1
        }

class EmotionAnimator(BaseAnimator):
    """情绪动画器"""
    
    def __init__(self, weight: float = 1.0):
        super().__init__(weight)
        self.current_emotion = "neutral"
        self.emotion_intensity = 0.0
        self.emotion_transition_time = 0.0
    
    def set_emotion(self, emotion: str, intensity: float = 1.0):
        """设置情绪"""
        self.current_emotion = emotion
        self.emotion_intensity = max(0.0, min(1.0, intensity))
        self.emotion_transition_time = time.time()
    
    def _calculate_parameters(self, renderer) -> Dict[str, float]:
        if self.current_emotion == "neutral":
            return {}
        
        # 根据情绪类型返回不同的参数
        emotion_params = {
            "happy": {"ParamMouthOpenY": 0.3, "ParamEyeLOpen": 0.8, "ParamEyeROpen": 0.8},
            "sad": {"ParamMouthOpenY": -0.2, "ParamEyeLOpen": 0.6, "ParamEyeROpen": 0.6},
            "angry": {"ParamMouthOpenY": -0.1, "ParamEyeLOpen": 1.2, "ParamEyeROpen": 1.2},
            "surprised": {"ParamMouthOpenY": 0.5, "ParamEyeLOpen": 1.5, "ParamEyeROpen": 1.5}
        }
        
        if self.current_emotion in emotion_params:
            params = emotion_params[self.current_emotion].copy()
            # 应用强度
            for key in params:
                params[key] *= self.emotion_intensity * self.weight
            return params
        
        return {}

class Live2DAnimator:
    """Live2D动画管理器"""
    
    def __init__(self, renderer):
        self.renderer = renderer
        self.animators: List[BaseAnimator] = []
        self.last_update_time = time.time()
        
        # 初始化默认动画器
        self._initialize_default_animators()
    
    def _initialize_default_animators(self):
        """初始化默认动画器"""
        # 添加眨眼动画器
        blink_animator = BlinkAnimator(weight=1.0)
        self.add_animator(blink_animator)
        
        # 添加眼球跟踪动画器
        eyeball_animator = EyeBallAnimator(weight=0.3)
        self.add_animator(eyeball_animator)
        
        # 添加身体角度动画器
        body_animator = BodyAngleAnimator(weight=0.2)
        self.add_animator(body_animator)
        
        # 添加呼吸动画器
        breath_animator = BreathAnimator(weight=0.4)
        self.add_animator(breath_animator)
        
        # 添加情绪动画器
        emotion_animator = EmotionAnimator(weight=1.0)
        self.add_animator(emotion_animator)
    
    def add_animator(self, animator: BaseAnimator):
        """添加动画器"""
        self.animators.append(animator)
    
    def remove_animator(self, animator: BaseAnimator):
        """移除动画器"""
        if animator in self.animators:
            self.animators.remove(animator)
    
    def update(self):
        """更新所有动画器"""
        if not self.renderer or not self.renderer.has_model():
            return
        
        current_time = time.time()
        delta_time = current_time - self.last_update_time
        self.last_update_time = current_time
        
        # 更新所有动画器并应用参数
        for animator in self.animators:
            if animator.enabled:
                params = animator.update(self.renderer)
                for param_id, value in params.items():
                    self.renderer.set_parameter(param_id, value)
    
    def set_emotion(self, emotion: str, intensity: float = 1.0):
        """设置情绪"""
        for animator in self.animators:
            if isinstance(animator, EmotionAnimator):
                animator.set_emotion(emotion, intensity)
                break
    
    def set_eye_target(self, x: float, y: float):
        """设置眼球跟踪目标"""
        for animator in self.animators:
            if isinstance(animator, EyeBallAnimator):
                animator.set_target(x, y)
                break
    
    def enable_animator(self, animator_type: type):
        """启用指定类型的动画器"""
        for animator in self.animators:
            if isinstance(animator, animator_type):
                animator.enable()
    
    def disable_animator(self, animator_type: type):
        """禁用指定类型的动画器"""
        for animator in self.animators:
            if isinstance(animator, animator_type):
                animator.disable()
    
    def cleanup(self):
        """清理动画器"""
        self.animators.clear()
        self.renderer = None
