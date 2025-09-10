import os
import sys
import json
import time
import threading
from pathlib import Path
from PyQt5.QtWidgets import QWidget, QStackedLayout, QLabel, QSizePolicy
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap, QPainter, QColor, QBrush, QPen

# 导入独立的Live2D模块
try:
    from .live2d import Live2DWidget
    LIVE2D_AVAILABLE = True
except ImportError as e:
    LIVE2D_AVAILABLE = False
    print(f"⚠️ Live2D模块未找到，将使用图片模式: {e}")


class Live2DSideWidget(QWidget):
    """支持Live2D和图片的侧栏Widget"""
    
    # 信号定义
    model_loaded = pyqtSignal(bool)  # 模型加载状态信号
    error_occurred = pyqtSignal(str)  # 错误信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        # 从配置中读取透明度设置，避免硬编码
        try:
            import sys, os
            sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))
            from system.config import config
            # 使用配置中的透明度，转换为0-255范围
            self.bg_alpha = int(config.ui.bg_alpha * 255)  # 背景透明度
            self.border_alpha = 50  # 边框透明度（保持固定值）
        except Exception:
            # 如果配置加载失败，使用默认值
            self.bg_alpha = 200  # 背景透明度
            self.border_alpha = 50  # 边框透明度
        self.glow_intensity = 0  # 发光强度
        self.is_glowing = False
        
        # 显示模式：'live2d' 或 'image'
        self.display_mode = 'image'
        self.live2d_model_path = None
        self.fallback_image_path = None
        
        # 创建堆叠布局
        self.stack_layout = QStackedLayout(self)
        self.stack_layout.setContentsMargins(5, 5, 5, 5)
        
        # 创建Live2D Widget
        if LIVE2D_AVAILABLE:
            self.live2d_widget = Live2DWidget(self)
            self.live2d_widget.setStyleSheet('background: transparent; border: none;')
        else:
            self.live2d_widget = None
        
        # 创建图片显示Widget
        self.image_widget = QLabel(self)
        self.image_widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.image_widget.setAlignment(Qt.AlignCenter)
        self.image_widget.setMinimumSize(1, 1)
        self.image_widget.setMaximumSize(16777215, 16777215)
        self.image_widget.setStyleSheet('background: transparent; border: none;')
        
        # 添加到堆叠布局
        self.stack_layout.addWidget(self.image_widget)  # index 0: 图片模式
        if self.live2d_widget:
            self.stack_layout.addWidget(self.live2d_widget)  # index 1: Live2D模式
        
        # 默认显示图片模式
        self.stack_layout.setCurrentIndex(0)
        
        # 设置鼠标指针
        self.setCursor(Qt.PointingHandCursor)
    
    def set_background_alpha(self, alpha):
        """设置背景透明度"""
        self.bg_alpha = alpha
        self.update()
    
    def set_border_alpha(self, alpha):
        """设置边框透明度"""
        self.border_alpha = alpha
        self.update()
    
    def set_glow_intensity(self, intensity):
        """设置发光强度 0-20"""
        self.glow_intensity = max(0, min(20, intensity))
        self.update()
    
    def start_glow_animation(self):
        """开始发光动画"""
        self.is_glowing = True
        self.update()
    
    def stop_glow_animation(self):
        """停止发光动画"""
        self.is_glowing = False
        self.glow_intensity = 0
        self.update()
    
    def set_live2d_model(self, model_path):
        """设置Live2D模型路径"""
        self.live2d_model_path = model_path
        
        # 检查文件是否存在
        if not os.path.exists(model_path):
            self.error_occurred.emit(f"Live2D模型文件不存在: {model_path}")
            return False
        
        # 尝试加载Live2D模型
        if LIVE2D_AVAILABLE and self.live2d_widget:
            success = self.live2d_widget.load_model(model_path)
            if success:
                self.display_mode = 'live2d'
                self.stack_layout.setCurrentIndex(1)  # 切换到Live2D模式
                self.model_loaded.emit(True)
                print(f"✅ 切换到Live2D模式: {model_path}")
                return True
            else:
                self.error_occurred.emit(f"Live2D模型加载失败: {model_path}")
        else:
            self.error_occurred.emit("Live2D功能不可用")
        
        # Live2D加载失败，回退到图片模式
        self.fallback_to_image_mode()
        return False
    
    def set_fallback_image(self, image_path):
        """设置回退图片路径"""
        self.fallback_image_path = image_path
        self.load_image(image_path)
    
    def fallback_to_image_mode(self):
        """回退到图片模式"""
        self.display_mode = 'image'
        self.stack_layout.setCurrentIndex(0)  # 切换到图片模式
        
        # 如果有回退图片，加载它
        if self.fallback_image_path and os.path.exists(self.fallback_image_path):
            self.load_image(self.fallback_image_path)
        else:
            # 使用默认图片
            default_image = os.path.join(os.path.dirname(__file__), 'standby.png')
            if os.path.exists(default_image):
                self.load_image(default_image)
        
        self.model_loaded.emit(False)
        print("🔄 已回退到图片模式")
    
    def load_image(self, image_path):
        """加载图片"""
        if not os.path.exists(image_path):
            print(f"⚠️ 图片文件不存在: {image_path}")
            return False
        
        try:
            pixmap = QPixmap(image_path)
            if pixmap.isNull():
                print(f"❌ 无法加载图片: {image_path}")
                return False
            
            # 自适应缩放图片
            self.resize_image(pixmap)
            return True
            
        except Exception as e:
            print(f"❌ 图片加载失败: {e}")
            return False
    
    def resize_image(self, pixmap=None):
        """调整图片大小"""
        if not pixmap:
            if hasattr(self.image_widget, 'pixmap'):
                pixmap = self.image_widget.pixmap()
            else:
                return
        
        if pixmap.isNull():
            return
        
        # 获取可用空间（减去边距）
        available_width = self.width() - 10
        available_height = self.height() - 10
        
        if available_width > 50 and available_height > 50:
            # 缩放图片以填满空间
            scaled_pixmap = pixmap.scaled(
                available_width, available_height,
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation
            )
            self.image_widget.setPixmap(scaled_pixmap)
            self.image_widget.resize(available_width, available_height)
    
    def resizeEvent(self, event):
        """调整大小事件"""
        super().resizeEvent(event)
        
        # 延迟调整图片大小，避免频繁重绘
        if not hasattr(self, '_resize_timer'):
            self._resize_timer = QTimer()
            self._resize_timer.setSingleShot(True)
            self._resize_timer.timeout.connect(self._delayed_resize)
        
        self._resize_timer.start(50)  # 50ms后执行调整
    
    def _delayed_resize(self):
        """延迟执行的大小调整"""
        if self.display_mode == 'image':
            self.resize_image()
        elif self.display_mode == 'live2d' and self.live2d_widget and self.live2d_widget.is_model_loaded():
            # Live2D Widget会自动处理大小调整
            pass
    
    def paintEvent(self, event):
        """自定义绘制方法"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = self.rect()
        
        # 绘制发光效果（如果有）
        if self.glow_intensity > 0:
            glow_rect = rect.adjusted(-2, -2, 2, 2)
            glow_color = QColor(100, 200, 255, self.glow_intensity)
            painter.setPen(QPen(glow_color, 2))
            painter.setBrush(QBrush(Qt.NoBrush))
            painter.drawRoundedRect(glow_rect, 17, 17)
        
        # 绘制主要背景
        bg_color = QColor(17, 17, 17, self.bg_alpha)
        painter.setBrush(QBrush(bg_color))
        
        # 绘制边框
        border_color = QColor(255, 255, 255, self.border_alpha)
        painter.setPen(QPen(border_color, 1))
        
        # 绘制圆角矩形
        painter.drawRoundedRect(rect, 15, 15)
        
        super().paintEvent(event)
    
    def get_display_mode(self):
        """获取当前显示模式"""
        return self.display_mode
    
    def is_live2d_available(self):
        """检查Live2D是否可用"""
        return LIVE2D_AVAILABLE
    
    def cleanup(self):
        """清理资源"""
        if self.live2d_widget:
            self.live2d_widget.cleanup()
    
    def mousePressEvent(self, event):
        """鼠标点击事件 - 传递给父组件处理"""
        super().mousePressEvent(event)
        # 这里可以添加Live2D特定的交互逻辑
        if self.display_mode == 'live2d' and self.live2d_widget and self.live2d_widget.is_model_loaded():
            # Live2D Widget会自动处理点击交互
            pass
