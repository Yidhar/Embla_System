#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Live2D渲染器
负责Live2D模型的加载、渲染和基础操作
"""

import os
import time
from typing import Optional, Tuple

# 尝试导入Live2D相关模块
try:
    import live2d.v3 as live2d
    LIVE2D_AVAILABLE = True
except ImportError:
    LIVE2D_AVAILABLE = False
    print("⚠️ Live2D模块未安装，将使用图片模式")

class Live2DRenderer:
    """Live2D渲染器类"""
    
    def __init__(self):
        self.model = None
        self.is_initialized = False
        self.model_path = None
        self.width = 400
        self.height = 600
        
    def initialize(self) -> bool:
        """初始化Live2D渲染器"""
        if not LIVE2D_AVAILABLE:
            return False
            
        try:
            live2d.glInit()
            self.is_initialized = True
            print("✅ Live2D渲染器初始化成功")
            return True
        except Exception as e:
            print(f"❌ Live2D渲染器初始化失败: {e}")
            self.is_initialized = False
            return False
    
    def load_model(self, model_path: str) -> bool:
        """加载Live2D模型"""
        if not LIVE2D_AVAILABLE or not self.is_initialized:
            return False
            
        if not os.path.exists(model_path):
            print(f"❌ Live2D模型文件不存在: {model_path}")
            return False
            
        try:
            self.model = live2d.LAppModel()
            self.model.LoadModelJson(model_path)
            self.model.Resize(self.width, self.height)
            self.model.SetAutoBlinkEnable(False)  # 禁用自动眨眼
            self.model.SetAutoBreathEnable(True)  # 启用自动呼吸
            
            self.model_path = model_path
            print(f"✅ Live2D模型加载成功: {model_path}")
            return True
            
        except Exception as e:
            print(f"❌ Live2D模型加载失败: {e}")
            self.model = None
            return False
    
    def update(self):
        """更新模型状态"""
        if self.model:
            try:
                self.model.Update()
            except Exception as e:
                print(f"❌ Live2D模型更新失败: {e}")
    
    def draw(self):
        """绘制模型"""
        if self.model:
            try:
                live2d.clearBuffer()
                self.model.Draw()
            except Exception as e:
                print(f"❌ Live2D模型绘制失败: {e}")
    
    def resize(self, width: int, height: int):
        """调整模型大小"""
        self.width = width
        self.height = height
        if self.model:
            try:
                self.model.Resize(width, height)
            except Exception as e:
                print(f"❌ Live2D模型大小调整失败: {e}")
    
    def set_parameter(self, param_id: str, value: float):
        """设置模型参数"""
        if self.model:
            try:
                self.model.SetParameterValue(param_id, value)
            except Exception as e:
                print(f"❌ 设置Live2D参数失败: {e}")
    
    def get_parameter(self, param_id: str) -> float:
        """获取模型参数值"""
        if self.model:
            try:
                return self.model.GetParameterValue(param_id)
            except Exception as e:
                print(f"❌ 获取Live2D参数失败: {e}")
        return 0.0
    
    def trigger_motion(self, group: str, index: int = 0):
        """触发动作"""
        if self.model:
            try:
                self.model.StartMotion(group, index)
            except Exception as e:
                print(f"❌ 触发Live2D动作失败: {e}")
    
    def trigger_expression(self, expression_id: str):
        """触发表情"""
        if self.model:
            try:
                self.model.StartExpression(expression_id)
            except Exception as e:
                print(f"❌ 触发Live2D表情失败: {e}")
    
    def cleanup(self):
        """清理资源"""
        self.model = None
        self.is_initialized = False
        self.model_path = None
    
    def is_available(self) -> bool:
        """检查Live2D是否可用"""
        return LIVE2D_AVAILABLE and self.is_initialized
    
    def has_model(self) -> bool:
        """检查是否已加载模型"""
        return self.model is not None
