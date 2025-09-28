"""
进度显示组件
支持思考状态、加载动画和实时进度更新
"""

import os
from PyQt5.QtWidgets import QWidget, QLabel, QProgressBar, QVBoxLayout, QHBoxLayout  # 直接依赖 #
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal  # 直接依赖 #
from PyQt5.QtGui import QFont, QPixmap, QMovie  # 直接依赖 #

class ProgressWidget(QWidget):
    """进度显示组件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(80)
        self.setup_ui()
        self.setup_animations()
        
    def setup_ui(self):
        """初始化UI"""
        self.setStyleSheet("""
            QWidget {
                background: rgba(25, 25, 25, 200);
                border-radius: 15px;
                border: 1px solid rgba(100, 200, 255, 100);
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(8)
        
        # 状态标签和动画图标
        top_layout = QHBoxLayout()
        
        # 加载动画图标
        self.loading_label = QLabel()
        self.loading_label.setFixedSize(24, 24)
        self.loading_label.setAlignment(Qt.AlignCenter)
        
        # 检查是否有loading.gif
        gif_path = os.path.join(os.path.dirname(__file__), 'loading.gif')
        if os.path.exists(gif_path):
            self.movie = QMovie(gif_path)
            self.movie.setScaledSize(self.loading_label.size())
            self.loading_label.setMovie(self.movie)
        else:
            # 如果没有gif，显示文字动画
            self.loading_label.setText("●")
            self.loading_label.setStyleSheet("color: #64C8FF; font-size: 16pt;")
        
        top_layout.addWidget(self.loading_label)
        
        # 状态文本
        self.status_label = QLabel("正在思考...")
        self.status_label.setStyleSheet("""
            QLabel {
                color: #64C8FF;
                font: 14pt 'Lucida Console';
                background: transparent;
                border: none;
            }
        """)
        top_layout.addWidget(self.status_label)
        top_layout.addStretch()
        
        layout.addLayout(top_layout)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid rgba(100, 200, 255, 150);
                border-radius: 8px;
                background: rgba(50, 50, 50, 150);
                text-align: center;
                color: white;
                font: 10pt 'Lucida Console';
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #64C8FF, stop:1 #32A4FF);
                border-radius: 8px;
            }
        """)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        # 默认隐藏
        self.hide()
        
    def setup_animations(self):
        """设置动画效果"""
        # 淡入淡出动画
        self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_anim.setDuration(300)
        self.fade_anim.setEasingCurve(QEasingCurve.InOutQuad)
        
        # 脉冲动画定时器（用于无gif时的文字动画）
        self.pulse_timer = QTimer()
        self.pulse_timer.timeout.connect(self.pulse_loading_text)
        self.pulse_states = ["●", "●●", "●●●", "●●", "●"]
        self.pulse_index = 0
        
    def start_loading(self, status="正在思考..."):
        """开始加载动画"""
        self.status_label.setText(status)
        self.progress_bar.setValue(0)
        
        # 确保组件状态正确
        self.show()
        
        # 断开之前可能的连接
        try:
            self.fade_anim.finished.disconnect()
        except:
            pass
        
        # 设置淡入动画
        self.setWindowOpacity(0)
        self.fade_anim.setStartValue(0)
        self.fade_anim.setEndValue(1)
        self.fade_anim.start()
        
        # 启动动画
        if hasattr(self, 'movie'):
            self.movie.start()
        else:
            self.pulse_timer.start(500)  # 500ms间隔
            
    def update_progress(self, value, status=None):
        """更新进度"""
        # 确保组件可见
        if not self.isVisible():
            self.show()
            self.setWindowOpacity(1.0)
            
        self.progress_bar.setValue(min(100, max(0, value)))
        if status:
            self.status_label.setText(status)
            
    def stop_loading(self):
        """停止加载动画"""
        # 停止动画
        if hasattr(self, 'movie'):
            self.movie.stop()
        self.pulse_timer.stop()
        
        # 断开之前的连接，避免重复连接
        try:
            self.fade_anim.finished.disconnect()
        except:
            pass
        
        # 淡出隐藏
        self.fade_anim.setStartValue(1)
        self.fade_anim.setEndValue(0)
        self.fade_anim.finished.connect(self.hide)
        self.fade_anim.start()
        
    def pulse_loading_text(self):
        """脉冲文字动画（当没有gif时使用）"""
        if not hasattr(self, 'movie'):
            self.loading_label.setText(self.pulse_states[self.pulse_index])
            self.pulse_index = (self.pulse_index + 1) % len(self.pulse_states)


class EnhancedProgressWidget(ProgressWidget):
    """增强版进度组件，支持更多状态"""
    
    # 自定义信号
    cancel_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.add_cancel_button()
        
    def add_cancel_button(self):
        """添加取消按钮"""
        from PyQt5.QtWidgets import QPushButton  # 直接依赖 #
        
        # 在顶部布局添加取消按钮
        top_layout = self.layout().itemAt(0).layout()
        
        self.cancel_btn = QPushButton("✕")
        self.cancel_btn.setFixedSize(20, 20)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 100, 100, 150);
                border: none;
                border-radius: 10px;
                color: white;
                font: 12pt bold;
            }
            QPushButton:hover {
                background: rgba(255, 100, 100, 200);
            }
            QPushButton:pressed {
                background: rgba(255, 50, 50, 200);
            }
        """)
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)
        self.cancel_btn.hide()  # 默认隐藏
        
        top_layout.addWidget(self.cancel_btn)
        
    def set_thinking_mode(self):
        """设置思考模式"""
        self.start_loading("正在深度思考...", show_cancel=True)
        # 思考模式使用不确定进度条
        self.progress_bar.setRange(0, 0)
        # 确保显示状态
        self.show()
        self.setWindowOpacity(1.0)
        
    def set_generating_mode(self):
        """设置生成模式"""
        self.update_progress(0, "正在生成回复...")
        self.progress_bar.setRange(0, 100)
        
    def set_processing_mode(self, task_name="处理中"):
        """设置处理模式"""
        self.update_progress(0, f"{task_name}...")
        self.progress_bar.setRange(0, 100)
        
    def start_loading(self, status="正在思考...", show_cancel=False):
        """开始加载，可选择是否显示取消按钮"""
        super().start_loading(status)
        if show_cancel:
            self.cancel_btn.show()
        else:
            self.cancel_btn.hide() 