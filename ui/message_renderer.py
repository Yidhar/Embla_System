# message_renderer.py # 独立的消息渲染器
import sys, os; sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))
from typing import List
from nagaagent_core.vendors.PyQt5.QtWidgets import QFrame, QVBoxLayout, QLabel, QWidget, QSizePolicy, QPushButton, QHBoxLayout  # 统一入口 #
from nagaagent_core.vendors.PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer  # 统一入口 #
from nagaagent_core.vendors.PyQt5.QtGui import QFont  # 统一入口 #
from system.config import config

# 使用统一配置系统
BG_ALPHA = config.ui.bg_alpha
ANIMATION_DURATION = config.ui.animation_duration

class MessageDialog(QFrame):
    """独立的对话对话框组件"""
    
    def __init__(self, name, content, parent=None):
        super().__init__(parent)
        self.name = name
        self.content = content
        self.setup_ui()
        
    def setup_ui(self):
        """设置UI布局"""
        # 设置对话框样式，与原始QTextEdit保持一致
        self.setStyleSheet(f"""
            MessageDialog {{
                background: rgba(17,17,17,{int(BG_ALPHA*255)});
                border-radius: 0px;
                border: 1px solid rgba(255, 255, 255, 50);
                padding: 10px;
                margin: 5px 0px;
            }}
        """)
        
        # 创建垂直布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)
        
        # 用户名标签
        self.name_label = QLabel(self.name)
        self.name_label.setStyleSheet("""
            QLabel {
                color: #fff;
                font-size: 12pt;
                font-family: 'Lucida Console';
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
        """)
        layout.addWidget(self.name_label)
        
        # 内容容器
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("""
            QWidget {
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
        """)
        
        content_layout = QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        
        # 内容文本
        self.content_label = QLabel(self.content)
        self.content_label.setWordWrap(True)  # 允许文本换行
        self.content_label.setTextFormat(Qt.RichText)  # 支持HTML格式
        self.content_label.setStyleSheet("""
            QLabel {
                color: #fff;
                font-size: 16pt;
                font-family: 'Lucida Console';
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
                line-height: 1.4;
            }
        """)
        content_layout.addWidget(self.content_label)
        
        layout.addWidget(self.content_widget)
        
        # 设置大小策略，允许垂直扩展
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        
    def update_content(self, new_content):
        """更新对话内容"""
        self.content = new_content
        self.content_label.setText(new_content)
        # 强制重新计算大小
        self.content_label.adjustSize()
        self.adjustSize()
        
    def get_preferred_height(self):
        """获取对话框的推荐高度"""
        # 计算文本高度
        font = QFont("Lucida Console", 16)
        metrics = self.content_label.fontMetrics()
        
        # 获取文本宽度和可用宽度
        text_width = metrics.horizontalAdvance(self.content)
        available_width = self.width() - 40  # 减去padding和margin
        
        if available_width <= 0:
            available_width = 400  # 默认宽度
            
        # 计算需要的行数
        lines = max(1, (text_width + available_width - 1) // available_width)
        
        # 计算用户名高度
        name_height = 20  # 用户名大约高度
        
        # 计算内容高度
        content_height = lines * metrics.lineSpacing()
        
        # 总高度 = padding + 用户名 + 间距 + 内容 + padding
        total_height = 20 + name_height + 5 + content_height + 20
        
        return max(80, total_height)  # 最小高度80px


class ToolCallDialog(QFrame):
    """工具调用检测提示对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        
    def setup_ui(self):
        """设置UI布局"""
        # 设置对话框样式，与其他对话框保持一致
        self.setStyleSheet(f"""
            ToolCallDialog {{
                background: rgba(17,17,17,{int(BG_ALPHA*255)});
                border-radius: 0px;
                border: 1px solid rgba(255, 255, 255, 50);
                padding: 10px;
                margin: 5px 0px;
            }}
        """)
        
        # 创建垂直布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)
        
        # 工具调用提示标签
        self.tool_call_label = QLabel("工具调用检测中...")
        self.tool_call_label.setStyleSheet("""
            QLabel {
                color: #888;
                font-size: 14pt;
                font-family: 'Lucida Console';
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
        """)
        layout.addWidget(self.tool_call_label)
        
        # 设置大小策略
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        
    def update_message(self, message):
        """更新工具调用消息"""
        self.tool_call_label.setText(message)
        self.adjustSize()


class ToolCallContentDialog(QFrame):
    """工具调用内容对话框 - 没有用户名，但保持相同UI风格，支持展开嵌套对话框"""
    
    def __init__(self, content, parent=None):
        super().__init__(parent)
        self.content = content
        self.is_expanded = False  # 展开状态标志
        self.nested_dialog = None  # 嵌套对话框
        self.setup_ui()
        
    def setup_ui(self):
        """设置UI布局"""
        # 设置对话框样式，与MessageDialog保持一致
        self.setStyleSheet(f"""
            ToolCallContentDialog {{
                background: rgba(17,17,17,{int(BG_ALPHA*255)});
                border-radius: 0px;
                border: 1px solid rgba(255, 255, 255, 50);
                padding: 10px;
                margin: 5px 0px;
            }}
        """)
        
        # 创建垂直布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)
        
        # 创建水平布局用于内容和展开按钮
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        
        # 内容容器 - 没有用户名标签
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("""
            QWidget {
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
        """)
        
        content_widget_layout = QVBoxLayout(self.content_widget)
        content_widget_layout.setContentsMargins(0, 0, 0, 0)
        content_widget_layout.setSpacing(0)
        
        # 内容文本 - 使用工具调用特有的颜色
        self.content_label = QLabel(self.content)
        self.content_label.setWordWrap(True)  # 允许文本换行
        self.content_label.setTextFormat(Qt.RichText)  # 支持HTML格式
        self.content_label.setStyleSheet("""
            QLabel {
                color: #888;
                font-size: 16pt;
                font-family: 'Lucida Console';
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
                line-height: 1.4;
            }
        """)
        content_widget_layout.addWidget(self.content_label)
        
        content_layout.addWidget(self.content_widget, 1)  # 内容占据大部分空间
        
        # 展开按钮
        self.expand_button = QPushButton("▶")
        self.expand_button.setFixedSize(24, 24)
        self.expand_button.setStyleSheet("""
            QPushButton {
                background: rgba(100, 100, 100, 100);
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 12px;
                color: #888;
                font-size: 10pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(120, 120, 120, 150);
                border: 1px solid rgba(255, 255, 255, 50);
            }
            QPushButton:pressed {
                background: rgba(80, 80, 80, 200);
            }
        """)
        self.expand_button.clicked.connect(self.toggle_expand)
        content_layout.addWidget(self.expand_button)
        
        layout.addLayout(content_layout)
        
        # 嵌套对话框容器（初始隐藏）
        self.nested_container = QWidget()
        self.nested_container.setStyleSheet("""
            QWidget {
                background: rgba(25, 25, 25, 150);
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 5px;
                margin-top: 5px;
            }
        """)
        self.nested_container.setMaximumHeight(0)  # 初始高度为0
        self.nested_container.hide()
        
        nested_layout = QVBoxLayout(self.nested_container)
        nested_layout.setContentsMargins(10, 10, 10, 10)
        nested_layout.setSpacing(5)
        
        # 嵌套对话框标题
        self.nested_title = QLabel("工具调用详情")
        self.nested_title.setStyleSheet("""
            QLabel {
                color: #aaa;
                font-size: 12pt;
                font-family: 'Lucida Console';
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
        """)
        nested_layout.addWidget(self.nested_title)
        
        # 嵌套对话框内容
        self.nested_content = QLabel("这里显示工具调用的详细信息...")
        self.nested_content.setWordWrap(True)
        self.nested_content.setStyleSheet("""
            QLabel {
                color: #888;
                font-size: 14pt;
                font-family: 'Lucida Console';
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
                line-height: 1.3;
            }
        """)
        nested_layout.addWidget(self.nested_content)
        
        layout.addWidget(self.nested_container)
        
        # 设置大小策略，允许垂直扩展
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        
    def toggle_expand(self):
        """切换展开/收缩状态"""
        if self.is_expanded:
            self.collapse_nested()
        else:
            self.expand_nested()
    
    def expand_nested(self):
        """展开嵌套对话框"""
        if self.is_expanded:
            return
            
        self.is_expanded = True
        self.expand_button.setText("▼")  # 改变按钮图标
        
        # 显示嵌套容器
        self.nested_container.show()
        
        # 创建高度动画
        self.height_animation = QPropertyAnimation(self.nested_container, b"maximumHeight")
        self.height_animation.setDuration(ANIMATION_DURATION)
        self.height_animation.setStartValue(0)
        self.height_animation.setEndValue(200)  # 展开后的高度
        self.height_animation.setEasingCurve(QEasingCurve.OutCubic)
        
        # 动画完成后调整主对话框高度
        self.height_animation.finished.connect(self.adjust_main_dialog_height)
        self.height_animation.start()
    
    def collapse_nested(self):
        """收缩嵌套对话框"""
        if not self.is_expanded:
            return
            
        self.is_expanded = False
        self.expand_button.setText("▶")  # 改变按钮图标
        
        # 创建高度动画
        self.height_animation = QPropertyAnimation(self.nested_container, b"maximumHeight")
        self.height_animation.setDuration(ANIMATION_DURATION)
        self.height_animation.setStartValue(200)
        self.height_animation.setEndValue(0)
        self.height_animation.setEasingCurve(QEasingCurve.OutCubic)
        
        # 动画完成后隐藏容器并调整主对话框高度
        self.height_animation.finished.connect(self.hide_nested_container)
        self.height_animation.start()
    
    def hide_nested_container(self):
        """隐藏嵌套容器"""
        self.nested_container.hide()
        self.adjust_main_dialog_height()
    
    def adjust_main_dialog_height(self):
        """调整主对话框高度"""
        # 强制重新计算大小
        self.adjustSize()
        # 通知父容器重新布局
        if self.parent():
            self.parent().updateGeometry()
    
    def set_nested_content(self, title, content):
        """设置嵌套对话框内容"""
        self.nested_title.setText(title)
        self.nested_content.setText(content)
    
    def update_content(self, new_content):
        """更新工具调用内容"""
        self.content = new_content
        self.content_label.setText(new_content)
        # 强制重新计算大小
        self.content_label.adjustSize()
        self.adjustSize()
        
    def get_preferred_height(self):
        """获取对话框的推荐高度"""
        # 计算文本高度
        font = QFont("Lucida Console", 16)
        metrics = self.content_label.fontMetrics()
        
        # 获取文本宽度和可用宽度
        text_width = metrics.horizontalAdvance(self.content)
        available_width = self.width() - 40  # 减去padding和margin
        
        if available_width <= 0:
            available_width = 400  # 默认宽度
            
        # 计算需要的行数
        lines = max(1, (text_width + available_width - 1) // available_width)
        
        # 计算内容高度 - 没有用户名，所以不需要name_height
        content_height = lines * metrics.lineSpacing()
        
        # 基础高度 = padding + 内容 + padding
        base_height = 20 + content_height + 20
        
        # 如果展开，加上嵌套对话框的高度
        if self.is_expanded:
            base_height += 220  # 嵌套对话框高度 + 间距
        
        return max(60, base_height)  # 最小高度60px（因为没有用户名）


class MessageRenderer:
    """消息渲染器管理器"""
    
    @staticmethod
    def create_user_message(name, content, parent):
        """创建用户消息对话框"""
        return MessageDialog(name, content, parent)
    
    @staticmethod
    def create_assistant_message(name, content, parent):
        """创建助手消息对话框"""
        return MessageDialog(name, content, parent)
    
    @staticmethod
    def create_tool_call_message(parent):
        """创建工具调用检测消息对话框"""
        return ToolCallDialog(parent)
    
    @staticmethod
    def create_tool_call_content_message(content, parent):
        """创建工具调用内容对话框 - 没有用户名"""
        return ToolCallContentDialog(content, parent)
    
    @staticmethod
    def create_system_message(name, content, parent):
        """创建系统消息对话框"""
        return MessageDialog(name, content, parent)
    
    @staticmethod
    def create_history_message(name, content, parent):
        """创建历史消息对话框 - 用于加载持久化上下文"""
        return MessageDialog(name, content, parent)
    
    @staticmethod
    def batch_create_history_messages(history_messages, parent_widget):
        """
        批量创建历史消息对话框
        
        Args:
            history_messages: 历史消息列表，格式为[{"role": "user/assistant", "content": "内容"}]
            parent_widget: 父级容器widget
            
        Returns:
            List: 创建的消息对话框列表
        """
        dialogs = []
        
        for msg in history_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "user":
                # 从配置获取用户名
                try:
                    from system.config import config
                    user_name = config.ui.user_name
                except ImportError:
                    user_name = "用户"
                dialog = MessageRenderer.create_user_message(user_name, content, parent_widget)
            elif role == "assistant":
                # 从配置获取AI名称
                try:
                    from system.config import config
                    ai_name = config.system.ai_name
                except ImportError:
                    ai_name = "娜迦"
                dialog = MessageRenderer.create_assistant_message(ai_name, content, parent_widget)
            else:
                # 其他角色使用系统消息样式
                dialog = MessageRenderer.create_system_message(role, content, parent_widget)
            
            dialogs.append(dialog)
        
        return dialogs
    
    @staticmethod
    def load_persistent_context_to_ui(parent_widget, max_messages: int = None) -> List[tuple]:
        """
        将持久化上下文加载到前端UI
        
        Args:
            parent_widget: 父级容器widget
            max_messages: 最大消息数量限制
            
        Returns:
            List[tuple]: 返回(消息ID, 消息信息, 对话框组件)的元组列表
        """
        try:
            # 导入消息管理器
            from apiserver.message_manager import message_manager
            
            # 计算最大消息数量
            if max_messages is None:
                try:
                    from system.config import config
                    max_messages = config.api.max_history_rounds * 2
                except ImportError:
                    max_messages = 20  # 默认值
            
            # 加载历史对话
            recent_messages = message_manager.load_recent_context(
                days=message_manager.context_load_days,
                max_messages=max_messages
            )
            
            if not recent_messages:
                print("📝 未找到历史对话记录，跳过前端UI加载")
                return []
            
            # 批量创建历史消息对话框
            history_dialogs = MessageRenderer.batch_create_history_messages(
                recent_messages, parent_widget
            )
            
            # 构建返回结果
            ui_messages = []
            for i, (msg, dialog) in enumerate(zip(recent_messages, history_dialogs)):
                message_id = f"history_{i}"
                message_info = {
                    'name': msg.get('role', 'user'),
                    'content': msg.get('content', ''),
                    'full_content': msg.get('content', ''),
                    'dialog_widget': dialog
                }
                ui_messages.append((message_id, message_info, dialog))
            
            print(f"✅ 前端UI已加载 {len(ui_messages)} 条历史对话")
            return ui_messages
            
        except Exception as e:
            print(f"❌ 前端加载持久化上下文失败: {e}")
            return []
    
    @staticmethod
    def update_message_content(dialog, new_content):
        """更新消息内容"""
        if hasattr(dialog, 'update_content'):
            dialog.update_content(new_content)
        elif hasattr(dialog, 'update_message'):
            dialog.update_message(new_content)
    
    @staticmethod
    def get_message_height(dialog):
        """获取消息对话框高度"""
        if hasattr(dialog, 'get_preferred_height'):
            return dialog.get_preferred_height()
        return dialog.sizeHint().height()
