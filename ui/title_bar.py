import sys, os; sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))
from nagaagent_core.vendors.PyQt5.QtWidgets import QWidget, QPushButton
from nagaagent_core.vendors.PyQt5.QtCore import Qt, QRect
from nagaagent_core.vendors.PyQt5.QtGui import QColor, QPainter, QFont
import os
from system.config import config
import logging

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

class TitleBar(QWidget):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.text = text
        self.setFixedHeight(100)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._offset = None
        # mac风格按钮
        for i,(txt,color,hover,cb) in enumerate([
            ('-','#FFBD2E','#ffe084',lambda:self.parent().showMinimized()),
            ('×','#FF5F57','#ff8783',lambda:self.parent().close())]):
            btn=QPushButton(txt,self)
            btn.setGeometry(self.width()-MAC_BTN_MARGIN-MAC_BTN_SIZE*(2-i)-MAC_BTN_GAP*(1-i),36,MAC_BTN_SIZE,MAC_BTN_SIZE)
            btn.setStyleSheet(f"QPushButton{{background:{color};border:none;border-radius:{MAC_BTN_SIZE//2}px;color:#fff;font:18pt;}}QPushButton:hover{{background:{hover};}}")
            btn.clicked.connect(cb)
            setattr(self,f'btn_{"min close".split()[i]}',btn)
    def mousePressEvent(self, e):
        if e.button()==Qt.LeftButton: self._offset = e.globalPos()-self.parent().frameGeometry().topLeft()
    def mouseMoveEvent(self, e):
        if self._offset and e.buttons()&Qt.LeftButton:
            self.parent().move(e.globalPos()-self._offset)
    def mouseReleaseEvent(self,e):self._offset=None
    def paintEvent(self, e):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        qp.setPen(QColor(255,255,255,180))
        qp.drawLine(0, 2, w, 2)
        qp.drawLine(0, h-3, w, h-3)
        font = QFont("Consolas", max(10, (h-40)//2), QFont.Bold)
        qp.setFont(font)
        rect = QRect(0, 20, w, h-40)
        for dx,dy in [(-1,0),(1,0),(0,-1),(0,1)]:
            qp.setPen(QColor(0,0,0))
            qp.drawText(rect.translated(dx,dy), Qt.AlignCenter, self.text)
        qp.setPen(QColor(255,255,255))
        qp.drawText(rect, Qt.AlignCenter, self.text)
    def resizeEvent(self,e):
        x=self.width()-MAC_BTN_MARGIN
        for i,btn in enumerate([self.btn_min,self.btn_close]):btn.move(x-MAC_BTN_SIZE*(2-i)-MAC_BTN_GAP*(1-i),36)
