import sys, os; sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))
from .styles.button_factory import ButtonFactory
from nagaagent_core.vendors.PyQt5.QtWidgets import QApplication, QWidget, QTextEdit, QSizePolicy, QHBoxLayout, QLabel, QVBoxLayout, QStackedLayout, QPushButton, QStackedWidget, QDesktopWidget, QScrollArea, QSplitter, QFileDialog, QMessageBox, QFrame  # 统一入口 #
from nagaagent_core.vendors.PyQt5.QtCore import Qt, QRect, QParallelAnimationGroup, QPropertyAnimation, QEasingCurve, QTimer, QThread, pyqtSignal, QObject, QEvent  # 统一入口 #
from nagaagent_core.vendors.PyQt5.QtGui import QColor, QPainter, QBrush, QFont, QPen  # 统一入口 #
# conversation_core已删除，相关功能已迁移到apiserver
import os
from system.config import config, AI_NAME, Live2DConfig # 导入统一配置
from ui.message_renderer import MessageRenderer  # 导入消息渲染器
# 语音输入功能已迁移到统一语音管理器
import json
from nagaagent_core.core import requests
from pathlib import Path
import time
import logging

from .title_bar import TitleBar
from .utils.response_util import extract_message
from .tools import chat, document, live2d, mindmap, side, stream, voice

# 设置日志
logger = logging.getLogger(__name__)

# 使用统一配置系统
def get_ui_config():
    """获取UI配置，确保使用最新的配置值"""
    return {
        'BG_ALPHA': config.ui.bg_alpha,
        'WINDOW_BG_ALPHA': config.ui.window_bg_alpha,
        'USER_NAME': config.ui.user_name,
        'MAC_BTN_SIZE': config.ui.mac_btn_size,
        'MAC_BTN_MARGIN': config.ui.mac_btn_margin,
        'MAC_BTN_GAP': config.ui.mac_btn_gap,
        'ANIMATION_DURATION': config.ui.animation_duration
    }

# 初始化全局变量
ui_config = get_ui_config()
BG_ALPHA = ui_config['BG_ALPHA']
WINDOW_BG_ALPHA = ui_config['WINDOW_BG_ALPHA']
USER_NAME = ui_config['USER_NAME']
MAC_BTN_SIZE = ui_config['MAC_BTN_SIZE']
MAC_BTN_MARGIN = ui_config['MAC_BTN_MARGIN']
MAC_BTN_GAP = ui_config['MAC_BTN_GAP']
ANIMATION_DURATION = ui_config['ANIMATION_DURATION']

class ChatWindow(QWidget):
    def __init__(self):
        super().__init__()
        
        self._init_windows()
        
        config.window=self
        
        
        self.resizeEvent(None)  # 强制自适应一次，修复图片初始尺寸
        # 加载历史记录（替换原_self_load_persistent_context_to_ui） 
        chat.load_persistent_history(
            max_messages=config.api.max_history_rounds * 2
        )
        
        
    def _init_windows(self):
        # 设置为屏幕大小的80%
        desktop = QDesktopWidget()
        self.screen_rect = desktop.screenGeometry()
        self.window_width = int(self.screen_rect.width() * 0.8)
        self.window_height = int(self.screen_rect.height() * 0.8)
        self._offset = None
        # 获取屏幕大小并自适应
        self.resize(self.window_width, self.window_height)
        
        # 窗口居中显示
        x = (self.screen_rect.width() - self.window_width) // 2
        y = (self.screen_rect.height() - self.window_height) // 2
        self.move(x, y)
        
        # 移除置顶标志，保留无边框
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # 添加窗口背景和拖动支持
        self.setStyleSheet(f"""
            ChatWindow {{
                background: rgba(25, 25, 25, {WINDOW_BG_ALPHA});
                border-radius: 20px;
                border: 1px solid rgba(255, 255, 255, 30);
            }}
        """)
        self.setLayout(self.chat_tool.main)
        self.titlebar = TitleBar('NAGA AGENT', self)
        self.titlebar.setGeometry(0,0,self.width(),100)
    
# PyQt不再处理语音输出，由apiserver直接交给voice/output处理

    def toggle_self_game(self):
        """切换博弈论流程开关"""
        self.self_game_enabled = not self.self_game_enabled
        status = '启用' if self.self_game_enabled else '禁用'
        self.chat_tool.add_user_message("系统", f"● 博弈论流程已{status}")

#==========MouseEvents==========
    # 添加整个窗口的拖动支持
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._offset = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._offset and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._offset = None
        event.accept()

    def paintEvent(self, event):
        """绘制窗口背景"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 绘制主窗口背景 - 使用可调节的透明度
        painter.setBrush(QBrush(QColor(25, 25, 25, WINDOW_BG_ALPHA)))
        painter.setPen(QColor(255, 255, 255, 30))
        painter.drawRoundedRect(self.rect(), 20, 20)
        
    def showEvent(self, event):
        """窗口显示事件"""
        super().showEvent(event)
        
        # 其他初始化代码...
        self.setFocus()
        self.input.setFocus()
        # 图片初始化现在由Live2DSideWidget处理
        self._img_inited = True
        
    def resizeEvent(self, e):
        if getattr(self, '_animating', False):  # 动画期间跳过所有重绘操作，避免卡顿
            return
        # 图片调整现在由Live2DSideWidget内部处理
        super().resizeEvent(e)
    
    def eventFilter(self, obj, event):
        """事件过滤器：处理输入框的键盘事件，实现回车发送、Shift+回车换行"""
        # 仅处理输入框（self.input）的事件
        if obj != self.input:
            return super().eventFilter(obj, event)

        # 仅处理「键盘按下」事件
        if event.type() == QEvent.KeyPress:
            # 捕获两种回车按键：主键盘回车（Key_Return）、小键盘回车（Key_Enter）
            is_enter_key = event.key() in (Qt.Key_Return, Qt.Key_Enter)
            # 判断是否按住了Shift键
            is_shift_pressed = event.modifiers() & Qt.ShiftModifier

            if is_enter_key:
                if not is_shift_pressed:
                    # 纯回车：发送消息，阻止默认换行
                    self.chat_tool.on_send()
                    return True  # 返回True表示事件已处理，不传递给输入框
                else:
                    # Shift+回车：放行事件，让输入框正常换行
                    return False  # 返回False表示事件继续传递

        # 其他事件（如普通输入）：正常放行
        return super().eventFilter(obj, event)
    
    
#====================
