#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Live2D Widget
基于QGLWidget的Live2D显示组件
"""

from nagaagent_core.vendors.PyQt5.QtWidgets import QWidget  # 统一入口 #
from nagaagent_core.vendors.PyQt5.QtCore import Qt, QTimer  # 统一入口 #
from nagaagent_core.vendors.PyQt5.QtOpenGL import QGLWidget  # 统一入口 #

from .renderer import Live2DRenderer
from .animator import Live2DAnimator

class Live2DWidget(QGLWidget):
    """Live2D显示Widget"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 初始化渲染器和动画器
        self.renderer = Live2DRenderer()
        self.animator = None
        self.timer = None
        self.fps = 60  # 帧率
        
        # 设置Widget属性
        self.setMinimumSize(200, 300)
        self.setStyleSheet('background: transparent; border: none;')
        
    def initializeGL(self):
        """初始化OpenGL"""
        try:
            success = self.renderer.initialize()
            if success:
                # 初始化动画器
                self.animator = Live2DAnimator(self.renderer)
                print("✅ Live2D Widget初始化成功")
            else:
                print("❌ Live2D Widget初始化失败")
        except Exception as e:
            print(f"❌ Live2D Widget初始化异常: {e}")
    
    def load_model(self, model_path: str) -> bool:
        """加载Live2D模型"""
        if not self.renderer.is_available():
            print("❌ Live2D渲染器不可用")
            return False
        
        success = self.renderer.load_model(model_path)
        if success:
            # 启动渲染定时器
            self._start_render_timer()
            print(f"✅ Live2D模型加载成功: {model_path}")
        else:
            print(f"❌ Live2D模型加载失败: {model_path}")
        
        return success
    
    def _start_render_timer(self):
        """启动渲染定时器"""
        if not self.timer:
            self.timer = QTimer()
            self.timer.timeout.connect(self._update_frame)
            self.timer.start(int(1000 / self.fps))  # 根据fps设置间隔
    
    def _stop_render_timer(self):
        """停止渲染定时器"""
        if self.timer:
            self.timer.stop()
            self.timer = None
    
    def _update_frame(self):
        """更新帧"""
        if self.animator:
            self.animator.update()
        self.update()  # 触发重绘
    
    def paintGL(self):
        """绘制Live2D模型"""
        if self.renderer and self.renderer.has_model():
            self.renderer.update()
            self.renderer.draw()
    
    def resizeGL(self, width: int, height: int):
        """调整大小"""
        if self.renderer:
            self.renderer.resize(width, height)
    
    def set_emotion(self, emotion: str, intensity: float = 1.0):
        """设置情绪"""
        if self.animator:
            self.animator.set_emotion(emotion, intensity)
    
    def set_eye_target(self, x: float, y: float):
        """设置眼球跟踪目标"""
        if self.animator:
            self.animator.set_eye_target(x, y)
    
    def trigger_motion(self, group: str, index: int = 0):
        """触发动作"""
        if self.renderer:
            self.renderer.trigger_motion(group, index)
    
    def trigger_expression(self, expression_id: str):
        """触发表情"""
        if self.renderer:
            self.renderer.trigger_expression(expression_id)
    
    def set_fps(self, fps: int):
        """设置帧率"""
        self.fps = max(1, min(120, fps))  # 限制在1-120fps之间
        if self.timer:
            self.timer.setInterval(int(1000 / self.fps))
    
    def is_model_loaded(self) -> bool:
        """检查是否已加载模型"""
        return self.renderer and self.renderer.has_model()
    
    def cleanup(self):
        """清理资源"""
        self._stop_render_timer()
        if self.animator:
            self.animator.cleanup()
        if self.renderer:
            self.renderer.cleanup()
    
    def mousePressEvent(self, event):
        """鼠标点击事件"""
        if event.button() == Qt.LeftButton and self.renderer and self.renderer.has_model():
            # 可以在这里添加点击交互逻辑
            # 例如：触发随机动作或表情
            import random
            actions = ["tap", "touch", "click"]
            action = random.choice(actions)
            self.trigger_motion(action, 0)
        
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """鼠标移动事件"""
        if self.renderer and self.renderer.has_model():
            # 眼球跟踪
            x = (event.x() / self.width()) * 2.0 - 1.0  # 转换为-1到1的范围
            y = -((event.y() / self.height()) * 2.0 - 1.0)  # 转换为-1到1的范围，Y轴翻转
            self.set_eye_target(x, y)
        
        super().mouseMoveEvent(event)
