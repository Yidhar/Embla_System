# message_renderer.py # 独立的消息渲染器
import sys, os; sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))
from PyQt5.QtWidgets import QFrame, QVBoxLayout, QLabel, QWidget, QSizePolicy, QPushButton, QHBoxLayout, QTextEdit
from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer
from PyQt5.QtGui import QFont, QTextDocument, QTextCursor, QTextCharFormat, QColor, QTextBlockFormat
from system.config import config
from ui.styles.message_styles import MessageStyles, MarkdownStyles, LayoutConfig
import markdown
from markdown.extensions import codehilite, fenced_code, tables, nl2br
from pygments import highlight
from pygments.lexers import get_lexer_by_name, TextLexer
from pygments.formatters import HtmlFormatter
from pygments.util import ClassNotFound
import re

# 使用统一配置系统
ANIMATION_DURATION = config.ui.animation_duration

class MarkdownRenderer:
    """Markdown渲染器，将Markdown内容转换为富文本格式"""
    
    def __init__(self):
        # 配置代码高亮
        self.codehilite_config = {
            'use_pygments': True,
            'css_class': 'highlight',
            'guess_lang': True,
            'noclasses': False,
            'pygments_style': 'monokai'  # 使用monokai主题
        }
        
        self.md = markdown.Markdown(extensions=[
            'codehilite',
            'fenced_code',  # 支持 ```python 格式
            'tables',       # 支持表格
            'nl2br'         # 换行转换
        ], extension_configs={
            'codehilite': self.codehilite_config
        })
        
        # 创建HTML格式化器
        self.html_formatter = HtmlFormatter(
            style='monokai',
            cssclass='highlight',
            noclasses=False,
            linenos=False,
            wrapcode=True
        )
    
    def render_to_html(self, content):
        """将Markdown内容渲染为HTML"""
        try:
            # 先进行基础Markdown渲染
            html = self.md.convert(content)
            
            # 后处理：增强代码块高亮
            html = self.enhance_code_highlighting(html)
            
            return html
        except Exception as e:
            print(f"Markdown渲染错误: {e}")
            return content  # 失败时返回原内容
    
    def enhance_code_highlighting(self, html):
        """增强代码块的高亮显示"""
        # 查找所有代码块 - 支持多种格式
        code_block_patterns = [
            r'<pre><code class="language-(\w+)">(.*?)</code></pre>',  # 标准格式
            r'<pre><code class="(\w+)">(.*?)</code></pre>',          # 简化格式
            r'<pre><code class="highlight highlight-(\w+)">(.*?)</code></pre>'  # codehilite格式
        ]
        
        def replace_code_block(match):
            language = match.group(1)
            code_content = match.group(2)
            
            # 清理代码内容
            code_content = code_content.strip()
            
            try:
                # 获取对应的词法分析器
                if language.lower() in ['text', 'plain', 'txt']:
                    lexer = TextLexer()
                else:
                    lexer = get_lexer_by_name(language, stripall=True)
                
                # 使用pygments进行高亮
                highlighted = highlight(code_content, lexer, self.html_formatter)
                
                # 提取高亮后的HTML内容
                highlighted_html = re.search(r'<div class="highlight"><pre>(.*?)</pre></div>', 
                                           highlighted, re.DOTALL)
                if highlighted_html:
                    return f'<div class="highlight"><pre><code class="language-{language}">{highlighted_html.group(1)}</code></pre></div>'
                else:
                    # 如果提取失败，直接使用高亮后的HTML
                    return highlighted
                    
            except ClassNotFound:
                # 如果找不到对应的词法分析器，使用文本词法分析器
                try:
                    lexer = TextLexer()
                    highlighted = highlight(code_content, lexer, self.html_formatter)
                    highlighted_html = re.search(r'<div class="highlight"><pre>(.*?)</pre></div>', 
                                               highlighted, re.DOTALL)
                    if highlighted_html:
                        return f'<div class="highlight"><pre><code class="language-{language}">{highlighted_html.group(1)}</code></pre></div>'
                except:
                    pass
                return match.group(0)
            except Exception as e:
                print(f"代码高亮错误 ({language}): {e}")
                return match.group(0)
        
        # 使用所有模式进行替换
        enhanced_html = html
        for pattern in code_block_patterns:
            enhanced_html = re.sub(pattern, replace_code_block, enhanced_html, flags=re.DOTALL)
        
        return enhanced_html
    
    def preprocess_content(self, content):
        """预处理内容，确保代码块格式正确"""
        if not isinstance(content, str):
            return str(content)
        
        # 确保代码块前后有换行
        content = re.sub(r'^(\s*```)(?![\r\n])', r'\1\n', content, flags=re.MULTILINE)
        content = re.sub(r'([^\n])(```)', r'\1\n\2', content)
        
        return content

class MessageDialog(QFrame):
    """独立的对话对话框组件 - 支持Markdown渲染"""
    
    def __init__(self, name, content, parent=None):
        super().__init__(parent)
        self.name = name
        self.content = content
        self.markdown_renderer = MarkdownRenderer()  # 初始化Markdown渲染器
        self.setup_ui()
        
    def setup_ui(self):
        """设置UI布局"""
        # 设置对话框样式
        self.setStyleSheet(MessageStyles.get_dialog_style())
        
        # 创建垂直布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*LayoutConfig.MAIN_LAYOUT_MARGINS)
        layout.setSpacing(LayoutConfig.MAIN_LAYOUT_SPACING)
        
        # 用户名标签
        self.name_label = QLabel(self.name)
        self.name_label.setStyleSheet(MessageStyles.get_name_label_style())
        layout.addWidget(self.name_label)
        
        # 内容容器
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet(MessageStyles.get_content_widget_style())
        
        content_layout = QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(*LayoutConfig.CONTENT_LAYOUT_MARGINS)
        content_layout.setSpacing(LayoutConfig.CONTENT_LAYOUT_SPACING)
        
        # 内容文本 - 使用QTextEdit支持富文本和Markdown
        self.content_text = QTextEdit()
        self.content_text.setReadOnly(True)  # 只读模式
        self.content_text.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # 禁用垂直滚动条
        self.content_text.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # 保留水平滚动条
        self.content_text.setStyleSheet(MessageStyles.get_content_text_style())
        
        # 设置文档大小调整策略，让高度自动适应内容
        self.content_text.document().contentsChanged.connect(self.adjust_text_height)
        
        # 渲染Markdown内容
        self.render_markdown_content()
        content_layout.addWidget(self.content_text)
        
        layout.addWidget(self.content_widget)
        
        # 设置大小策略，允许垂直扩展
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        
    def update_content(self, new_content):
        """更新对话内容"""
        self.content = new_content
        self.render_markdown_content()  # 重新渲染Markdown内容（会自动调整高度）
        
    def get_preferred_height(self):
        """获取对话框的推荐高度"""
        # 使用QTextEdit的文档高度
        doc_height = self.content_text.document().size().height()
        
        # 计算用户名高度
        name_height = 20  # 用户名大约高度
        
        # 总高度 = padding + 用户名 + 间距 + 内容 + padding
        total_height = 20 + name_height + 5 + int(doc_height) + 20
        
        return max(80, total_height)  # 最小高度80px
    
    def render_markdown_content(self):
        """渲染Markdown内容到QTextEdit"""
        try:
            # 预处理内容
            processed_content = self.markdown_renderer.preprocess_content(self.content)
            
            # 渲染为HTML
            html_content = self.markdown_renderer.render_to_html(processed_content)
            
            # 添加自定义样式
            styled_html = self.add_custom_styles(html_content)
            
            # 设置到QTextEdit
            self.content_text.setHtml(styled_html)
            
            # 渲染完成后调整高度
            QTimer.singleShot(0, self.adjust_text_height)
            
        except Exception as e:
            print(f"Markdown渲染失败: {e}")
            # 失败时显示原始内容
            self.content_text.setPlainText(self.content)
            QTimer.singleShot(0, self.adjust_text_height)
    
    def add_custom_styles(self, html_content):
        """为HTML内容添加自定义样式"""
        styled_html = f"""
        <html>
        <head>
            <style>
                {MarkdownStyles.get_markdown_styles()}
            </style>
        </head>
        <body>{html_content}</body>
        </html>
        """
        return styled_html
    
    def adjust_text_height(self):
        """动态调整文本高度以适应内容"""
        # 获取文档的理想高度
        doc_height = self.content_text.document().size().height()
        
        # 设置QTextEdit的高度为文档高度
        self.content_text.setFixedHeight(int(doc_height))
        
        # 调整整个对话框的高度
        self.adjustSize()


class ToolCallDialog(QFrame):
    """工具调用检测提示对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        
    def setup_ui(self):
        """设置UI布局"""
        # 设置对话框样式
        self.setStyleSheet(MessageStyles.get_dialog_style())
        
        # 创建垂直布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*LayoutConfig.MAIN_LAYOUT_MARGINS)
        layout.setSpacing(LayoutConfig.MAIN_LAYOUT_SPACING)
        
        # 工具调用提示标签
        self.tool_call_label = QLabel("工具调用检测中...")
        self.tool_call_label.setStyleSheet(MessageStyles.get_tool_call_label_style())
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
        # 设置对话框样式
        self.setStyleSheet(MessageStyles.get_dialog_style())
        
        # 创建垂直布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*LayoutConfig.MAIN_LAYOUT_MARGINS)
        layout.setSpacing(LayoutConfig.MAIN_LAYOUT_SPACING)
        
        # 创建水平布局用于内容和展开按钮
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(*LayoutConfig.HORIZONTAL_LAYOUT_MARGINS)
        content_layout.setSpacing(LayoutConfig.HORIZONTAL_LAYOUT_SPACING)
        
        # 内容容器 - 没有用户名标签
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet(MessageStyles.get_content_widget_style())
        
        content_widget_layout = QVBoxLayout(self.content_widget)
        content_widget_layout.setContentsMargins(0, 0, 0, 0)
        content_widget_layout.setSpacing(0)
        
        # 内容文本 - 使用工具调用特有的颜色
        self.content_label = QLabel(self.content)
        self.content_label.setWordWrap(True)  # 允许文本换行
        self.content_label.setTextFormat(Qt.RichText)  # 支持HTML格式
        self.content_label.setStyleSheet(MessageStyles.get_tool_call_content_style())
        content_widget_layout.addWidget(self.content_label)
        
        content_layout.addWidget(self.content_widget, 1)  # 内容占据大部分空间
        
        # 展开按钮
        self.expand_button = QPushButton("▶")
        self.expand_button.setFixedSize(*LayoutConfig.EXPAND_BUTTON_SIZE)
        self.expand_button.setStyleSheet(MessageStyles.get_expand_button_style())
        self.expand_button.clicked.connect(self.toggle_expand)
        content_layout.addWidget(self.expand_button)
        
        layout.addLayout(content_layout)
        
        # 嵌套对话框容器（初始隐藏）
        self.nested_container = QWidget()
        self.nested_container.setStyleSheet(MessageStyles.get_nested_container_style())
        self.nested_container.setMaximumHeight(LayoutConfig.NESTED_CONTAINER_INITIAL_HEIGHT)
        self.nested_container.hide()
        
        nested_layout = QVBoxLayout(self.nested_container)
        nested_layout.setContentsMargins(*LayoutConfig.NESTED_LAYOUT_MARGINS)
        nested_layout.setSpacing(LayoutConfig.NESTED_LAYOUT_SPACING)
        
        # 嵌套对话框标题
        self.nested_title = QLabel("工具调用详情")
        self.nested_title.setStyleSheet(MessageStyles.get_nested_title_style())
        nested_layout.addWidget(self.nested_title)
        
        # 嵌套对话框内容
        self.nested_content = QLabel("这里显示工具调用的详细信息...")
        self.nested_content.setWordWrap(True)
        self.nested_content.setStyleSheet(MessageStyles.get_nested_content_style())
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
        self.height_animation.setEndValue(LayoutConfig.NESTED_CONTAINER_EXPANDED_HEIGHT)
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
        self.height_animation.setStartValue(LayoutConfig.NESTED_CONTAINER_EXPANDED_HEIGHT)
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
