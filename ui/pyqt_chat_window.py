import sys, os; sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))
from .styles.button_factory import ButtonFactory
from nagaagent_core.vendors.PyQt5.QtWidgets import QApplication, QWidget, QTextEdit, QSizePolicy, QHBoxLayout, QLabel, QVBoxLayout, QStackedLayout, QPushButton, QStackedWidget, QDesktopWidget, QScrollArea, QSplitter, QFileDialog, QMessageBox, QFrame  # 统一入口 #
from nagaagent_core.vendors.PyQt5.QtCore import Qt, QRect, QParallelAnimationGroup, QPropertyAnimation, QEasingCurve, QTimer, QThread, pyqtSignal, QObject, QEvent  # 统一入口 #
from nagaagent_core.vendors.PyQt5.QtGui import QColor, QPainter, QBrush, QFont, QPen  # 统一入口 #
# conversation_core已删除，相关功能已迁移到apiserver
import os
from system.config import config, AI_NAME, Live2DConfig # 导入统一配置
from ui.response_utils import extract_message  # 新增：引入消息提取工具
from ui.styles.progress_widget import EnhancedProgressWidget  # 导入进度组件
from ui.enhanced_worker import StreamingWorker, BatchWorker  # 导入增强Worker
from ui.elegant_settings_widget import ElegantSettingsWidget
from ui.message_renderer import MessageRenderer  # 导入消息渲染器
from ui.live2d_side_widget import Live2DSideWidget  # 导入Live2D侧栏组件
from ui.document_tool import DocumentTool  # 导入Live2D侧栏组件
# 语音输入功能已迁移到统一语音管理器
import json
from nagaagent_core.core import requests
from pathlib import Path
import time
import logging
from .stream_manager import StreamingChatManager, _StreamHttpWorker, _NonStreamHttpWorker

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


class ChatWindow(QWidget):
    def __init__(self):
        super().__init__()
        
        # 获取屏幕大小并自适应
        desktop = QDesktopWidget()
        screen_rect = desktop.screenGeometry()
        # 设置为屏幕大小的80%
        window_width = int(screen_rect.width() * 0.8)
        window_height = int(screen_rect.height() * 0.8)
        self.resize(window_width, window_height)
        
        # 窗口居中显示
        x = (screen_rect.width() - window_width) // 2
        y = (screen_rect.height() - window_height) // 2
        self.move(x, y)
        
        # 移除置顶标志，保留无边框
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # 添加窗口背景和拖动支持
        self._offset = None
        self.setStyleSheet(f"""
            ChatWindow {{
                background: rgba(25, 25, 25, {WINDOW_BG_ALPHA});
                border-radius: 20px;
                border: 1px solid rgba(255, 255, 255, 30);
            }}
        """)
        
        # 初始化所有需要的self属性
        self.main_splitter = None
        self.chat_area = None
        self.chat_stack = None
        self.chat_page = None
        self.chat_scroll_area = None
        self.chat_content = None
        self.chat_layout = None
        self.settings_page = None
        self.progress_widget = None
        self.input_wrap = None
        self.prompt = None
        self.input = None
        self.hlay = None
        self.vlay = None
        
        # 初始化聊天UI组件（需要提前创建，供StreamingChatManager使用）
        self._init_chat_ui()
        
        # 初始化流式聊天管理器
        self.streaming_mode=False
        self.streaming_chat = StreamingChatManager(
            chat_layout=self.chat_layout,
            chat_scroll_area=self.chat_scroll_area,
            progress_widget=self.progress_widget,
            user_name=USER_NAME,
            ai_name=AI_NAME,
            streaming_mode=self.streaming_mode,
            logger=logger
        )
        
        
        from system.config import config
        # 加载历史记录（替换原_self_load_persistent_context_to_ui）
        self.streaming_chat.load_persistent_history(
            max_messages=config.api.max_history_rounds * 2
        )
        # 添加文档上传按钮
        self.upload_btn = ButtonFactory.create_action_button("upload", self.input_wrap)
        self.hlay.addWidget(self.upload_btn)
        
        # 添加心智云图按钮
        self.mind_map_btn = ButtonFactory.create_action_button("mind_map", self.input_wrap)
        self.hlay.addWidget(self.mind_map_btn)

        # 添加博弈论启动/关闭按钮
        self.self_game_enabled = False
        self.self_game_btn = ButtonFactory.create_action_button("self_game", self.input_wrap)
        self.self_game_btn.setToolTip("启动/关闭博弈论流程")
        self.hlay.addWidget(self.self_game_btn)
        
        # 添加实时语音按钮
        self.voice_realtime_btn = ButtonFactory.create_action_button("voice_realtime", self.input_wrap)
        self.voice_realtime_btn.setToolTip("启动/关闭实时语音对话")
        self.hlay.addWidget(self.voice_realtime_btn)

        self.vlay.addWidget(self.input_wrap,0)
        
        # 将聊天区域添加到分割器
        self.main_splitter.addWidget(self.chat_area)
        
        # 侧栏（Live2D/图片显示区域）- 使用Live2D侧栏Widget
        self.side = Live2DSideWidget()
        self.collapsed_width = 400  # 收缩状态宽度
        self.expanded_width = 800  # 展开状态宽度
        self.side.setMinimumWidth(self.collapsed_width)  # 设置最小宽度为收缩状态
        self.side.setMaximumWidth(self.collapsed_width)  # 初始状态为收缩
        
        def _enter(e):
            self.side.set_background_alpha(int(BG_ALPHA * 0.5 * 255))
            self.side.set_border_alpha(80)
        # 优化侧栏的悬停效果，使用QPainter绘制
        self.side.enterEvent = _enter
        
        def _leave(e):
            self.side.set_background_alpha(int(BG_ALPHA * 255))
            self.side.set_border_alpha(50)
        self.side.leaveEvent = _leave
        
        # 设置鼠标指针，提示可点击
        self.side.setCursor(Qt.PointingHandCursor)
        
        # 设置默认图片
        default_image = os.path.join(os.path.dirname(__file__), 'standby.png')
        if os.path.exists(default_image):
            self.side.set_fallback_image(default_image)
        
        # 连接Live2D侧栏的信号
        self.side.model_loaded.connect(self.on_live2d_model_loaded)
        self.side.error_occurred.connect(self.on_live2d_error)
        
        # 创建昵称标签（保持原有功能）
        nick=QLabel(f"● {AI_NAME}{config.system.version}",self.side)
        nick.setStyleSheet("""
            QLabel {
                color: #fff;
                font: 18pt 'Consolas';
                background: rgba(0,0,0,100);
                padding: 12px 0 12px 0;
                border-radius: 10px;
                border: none;
            }
        """)
        nick.setAlignment(Qt.AlignHCenter|Qt.AlignTop)
        nick.setAttribute(Qt.WA_TransparentForMouseEvents)
        nick.hide()  # 隐藏昵称
        
        # 将侧栏添加到分割器
        self.main_splitter.addWidget(self.side)
        
        # 设置分割器的初始比例 - 侧栏收缩状态
        self.main_splitter.setSizes([window_width - self.collapsed_width - 20, self.collapsed_width])  # 大部分给聊天区域
        
        # 创建包含分割器的主布局
        main=QVBoxLayout(self)
        main.setContentsMargins(10,110,10,10)
        main.addWidget(self.main_splitter)
        
        self.nick=nick
        self.naga=None  # conversation_core已删除，相关功能已迁移到apiserver
        self.worker=None
        self.full_img=0 # 立绘展开标志，0=收缩状态，1=展开状态
        self.streaming_mode = config.system.stream_mode  # 根据配置决定是否使用流式模式
        self.current_response = ""  # 当前响应缓冲
        self.animating = False  # 动画标志位，动画期间为True
        self._img_inited = False  # 标志变量，图片自适应只在初始化时触发一次

        # Live2D相关配置
        self.live2d_enabled = config.live2d.enabled  # 是否启用Live2D
        self.live2d_model_path = config.live2d.model_path  # Live2D模型路径
        
        # 实时语音相关
        self.voice_realtime_client = None  # 语音客户端（废弃，使用线程安全版本）
        self.voice_realtime_active = False  # 是否激活
        self.voice_realtime_state = "idle"  # idle/listening/recording/ai_speaking

        # 创建统一的语音管理器
        # 根据配置选择语音模式
        from system.config import config
        from voice.input.unified_voice_manager import UnifiedVoiceManager, VoiceMode

        self.voice_integration = UnifiedVoiceManager(self)

        # 根据配置确定默认模式
        if config.voice_realtime.voice_mode != "auto":
            # 使用指定的模式
            mode_map = {
                "local": VoiceMode.LOCAL,
                "end2end": VoiceMode.END_TO_END,
                "hybrid": VoiceMode.HYBRID
            }
            self.default_voice_mode = mode_map.get(config.voice_realtime.voice_mode, None)
        else:
            # 自动选择模式
            if config.voice_realtime.provider == "local":
                self.default_voice_mode = VoiceMode.LOCAL
            elif getattr(config.voice_realtime, 'use_api_server', False):
                self.default_voice_mode = VoiceMode.HYBRID
            else:
                self.default_voice_mode = VoiceMode.END_TO_END

        logger.info(f"[UI] 使用统一语音管理器，默认模式: {self.default_voice_mode.value if self.default_voice_mode else 'auto'}")

        # 初始化消息存储
        self._messages = {}
        self._message_counter = 0
        
        # 加载持久化历史对话到前端
        self._load_persistent_context_to_ui()
        
        # 连接进度组件信号
        self.progress_widget.cancel_requested.connect(self.cancel_current_task)
        
        self.input.textChanged.connect(self.adjust_input_height)
        self.input.installEventFilter(self)
        
        
        self.document_tool = DocumentTool(self)
        # 连接文档上传按钮
        self.upload_btn.clicked.connect(self.document_tool.upload_document)
        
        # 连接心智云图按钮
        self.mind_map_btn.clicked.connect(self.open_mind_map)
        # 连接博弈论按钮
        self.self_game_btn.clicked.connect(self.toggle_self_game)
        # 连接实时语音按钮
        self.voice_realtime_btn.clicked.connect(self.toggle_voice_realtime)
        
        self.setLayout(main)
        self.titlebar = TitleBar('NAGA AGENT', self)
        self.titlebar.setGeometry(0,0,self.width(),100)
        self.side.mousePressEvent=self.toggle_full_img # 侧栏点击切换聊天/设置
        self.resizeEvent(None)  # 强制自适应一次，修复图片初始尺寸
        
        # 初始化Live2D（如果启用）
        self.initialize_live2d()

    def _init_chat_ui(self):
        """初始化聊天相关UI组件"""
        
        fontfam,fontsize='Lucida Console',16
        
        # 创建主分割器，替换原来的HBoxLayout
        self.main_splitter = QSplitter(Qt.Horizontal, self)
        self.main_splitter.setStyleSheet("""
            QSplitter {
                background: transparent;
            }
            QSplitter::handle {
                background: rgba(255, 255, 255, 30);
                width: 2px;
                border-radius: 1px;
            }
            QSplitter::handle:hover {
                background: rgba(255, 255, 255, 60);
                width: 3px;
            }
        """)
        
        # 聊天区域容器
        self.chat_area=QWidget()
        self.chat_area.setMinimumWidth(400)  # 设置最小宽度
        self.vlay=QVBoxLayout(self.chat_area);
        self.vlay.setContentsMargins(0,0,0,0);
        self.vlay.setSpacing(10)
        
        # 用QStackedWidget管理聊天区和设置页
        self.chat_stack = QStackedWidget(self.chat_area)
        self.chat_stack.setStyleSheet("""
            QStackedWidget {
                background: transparent;
                border: none;
            }
        """) # 保证背景穿透
        # 创建聊天页面容器
        self.chat_page = QWidget()
        self.chat_page.setStyleSheet("""
            QWidget {
                background: transparent;
                border: none;
            }
        """)
        
        # 创建滚动区域来容纳消息对话框
        self.chat_scroll_area = QScrollArea(self.chat_page)
        self.chat_scroll_area.setWidgetResizable(True)
        self.chat_scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
                outline: none;
            }
            QScrollBar:vertical {
                background: rgba(255, 255, 255, 30);
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 80);
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 120);
            }
        """)
        
        # 创建滚动内容容器
        self.chat_content = QWidget()
        self.chat_content.setStyleSheet("""
            QWidget {
                background: transparent;
                border: none;
            }
        """)
        
        # 创建垂直布局来排列消息对话框
        self.chat_layout = QVBoxLayout(self.chat_content)
        self.chat_layout.setContentsMargins(10, 10, 10, 10)
        self.chat_layout.setSpacing(10)
        self.chat_layout.addStretch()  # 添加弹性空间，让消息从顶部开始
        
        self.chat_scroll_area.setWidget(self.chat_content)
        
        # 创建聊天页面布局
        chat_page_layout = QVBoxLayout(self.chat_page)
        chat_page_layout.setContentsMargins(0, 0, 0, 0)
        chat_page_layout.addWidget(self.chat_scroll_area)
        
        self.chat_stack.addWidget(self.chat_page) # index 0 聊天页
        self.settings_page = self.create_settings_page() # index 1 设置页
        self.chat_stack.addWidget(self.settings_page)
        self.vlay.addWidget(self.chat_stack, 1)
        
        # 添加进度显示组件
        self.progress_widget = EnhancedProgressWidget(self.chat_area)
        self.vlay.addWidget(self.progress_widget)
        
        self.input_wrap=QWidget(self.chat_area)
        self.input_wrap.setFixedHeight(60)  # 增加输入框包装器的高度，与字体大小匹配
        self.hlay=QHBoxLayout(self.input_wrap);self.hlay.setContentsMargins(0,0,0,0);self.hlay.setSpacing(8)
        self.prompt=QLabel('>',self.input_wrap)
        self.prompt.setStyleSheet(f"color:#fff;font:{fontsize}pt '{fontfam}';background:transparent;")
        self.hlay.addWidget(self.prompt)
        self.input = QTextEdit(self.input_wrap)
        self.input.setStyleSheet(f"""
            QTextEdit {{
                background: rgba(17,17,17,{int(BG_ALPHA*255)});
                color: #fff;
                border-radius: 15px;
                border: 1px solid rgba(255, 255, 255, 50);
                font: {fontsize}pt '{fontfam}';
                padding: 8px;
            }}
        """)
        self.input.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.hlay.addWidget(self.input)

    def create_settings_page(self):
        page = QWidget()
        page.setObjectName("SettingsPage")
        page.setStyleSheet("""
            #SettingsPage {
                background: transparent;
                border-radius: 24px;
                padding: 12px;
            }
        """)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollArea > QWidget > QWidget {
                background: transparent;
            }
            QScrollBar:vertical {
                background: rgba(255, 255, 255, 20);
                width: 6px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 60);
                border-radius: 3px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 80);
            }
        """)
        scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # 滚动内容
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        scroll_content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(12, 12, 12, 12)
        scroll_layout.setSpacing(20)
        # 只保留系统设置界面
        self.settings_widget = ElegantSettingsWidget(scroll_content)
        self.settings_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.settings_widget.settings_changed.connect(self.on_settings_changed)
        scroll_layout.addWidget(self.settings_widget, 1)
        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area, 1)
        return page

    def resizeEvent(self, e):
        if getattr(self, '_animating', False):  # 动画期间跳过所有重绘操作，避免卡顿
            return
        # 图片调整现在由Live2DSideWidget内部处理
        super().resizeEvent(e)
            

    def adjust_input_height(self):
        doc = self.input.document()
        h = int(doc.size().height())+10
        self.input.setFixedHeight(min(max(60, h), 150))  # 增加最小高度，与字体大小匹配
        self.input_wrap.setFixedHeight(self.input.height())

    def add_user_message(self, name, content, is_streaming=False):
        """添加用户消息"""
        from ui.response_utils import extract_message
        msg = extract_message(content)
        content_html = str(msg).replace('\\n', '\n').replace('\n', '<br>')

        # 生成消息ID
        if not hasattr(self, '_message_counter'):
            self._message_counter = 0
        self._message_counter += 1
        message_id = f"msg_{self._message_counter}"

        # 初始化消息存储
        if not hasattr(self, '_messages'):
            self._messages = {}

        # 存储消息信息
        self._messages[message_id] = {
            'name': name,
            'content': content_html,
            'full_content': content,
            'dialog_widget': None
        }

        # 使用消息渲染器创建对话框
        if name == "系统":
            message_dialog = MessageRenderer.create_system_message(name, content_html, self.chat_content)
        else:
            message_dialog = MessageRenderer.create_user_message(name, content_html, self.chat_content)

        # 存储对话框引用
        self._messages[message_id]['dialog_widget'] = message_dialog

        # 先移除stretch
        stretch_found = False
        stretch_index = -1
        for i in reversed(range(self.chat_layout.count())):
            item = self.chat_layout.itemAt(i)
            if item and not item.widget():  # 找到stretch
                self.chat_layout.removeItem(item)
                stretch_found = True
                stretch_index = i
                break

        # 添加消息
        self.chat_layout.addWidget(message_dialog)

        # 重新添加stretch到最后
        self.chat_layout.addStretch()

        # 滚动到底部
        self.scroll_to_bottom()

        return message_id
    
    
    def scroll_to_bottom(self):
        """滚动到聊天区域底部"""
        # 使用QTimer延迟滚动，确保布局完成
        QTimer.singleShot(10, lambda: self.chat_scroll_area.verticalScrollBar().setValue(
            self.chat_scroll_area.verticalScrollBar().maximum()
        ))

    def smart_scroll_to_bottom(self):
        """智能滚动到底部（如果用户正在查看历史消息，则不滚动）"""
        scrollbar = self.chat_scroll_area.verticalScrollBar()
        # 检查是否已经在底部附近（允许50像素的误差）
        is_at_bottom = scrollbar.value() >= scrollbar.maximum() - 50

        # 如果本来就在底部附近，则自动滚动到最新消息
        if is_at_bottom:
            self.scroll_to_bottom()
        
    def _load_persistent_context_to_ui(self):
        """从持久化上下文加载历史对话到前端UI"""
        try:
            # 检查是否启用持久化上下文
            if not config.api.persistent_context:
                logger.info("📝 持久化上下文功能已禁用，跳过历史记录加载")
                return

            # 使用消息渲染器加载历史对话到UI
            from ui.message_renderer import MessageRenderer

            ui_messages = MessageRenderer.load_persistent_context_to_ui(
                parent_widget=self.chat_content,
                max_messages=config.api.max_history_rounds * 2
            )

            if ui_messages:
                # 先移除stretch
                for i in reversed(range(self.chat_layout.count())):
                    item = self.chat_layout.itemAt(i)
                    if item and not item.widget():  # 找到stretch
                        self.chat_layout.removeItem(item)
                        break

                # 将历史消息添加到UI布局中
                for message_id, message_info, dialog in ui_messages:
                    self.chat_layout.addWidget(dialog)

                    # 存储到消息管理器中
                    self._messages[message_id] = message_info

                # 重新添加stretch到最后
                self.chat_layout.addStretch()

                # 更新消息计数器
                self._message_counter = len(ui_messages)

                # 滚动到底部显示最新消息
                self.scroll_to_bottom()

                logger.info(f"✅ 前端UI已加载 {len(ui_messages)} 条历史对话")
            else:
                logger.info("📝 前端UI未找到历史对话记录")

        except ImportError as e:
            logger.warning(f"⚠️ 日志解析器模块未找到，跳过前端历史记录加载: {e}")
        except Exception as e:
            logger.error(f"❌ 前端加载持久化上下文失败: {e}")
            # 失败时不影响正常使用，继续使用空上下文
            logger.info("💡 将继续使用空上下文，不影响正常对话功能")
    
    def on_send(self):
        u = self.input.toPlainText().strip()
        if u:
            # 停止任何正在进行的打字机效果
            if hasattr(self, '_non_stream_timer') and self._non_stream_timer and self._non_stream_timer.isActive():
                self._non_stream_timer.stop()
                self._non_stream_timer.deleteLater()
                self._non_stream_timer = None
                # 如果有未显示完的文本，立即显示完整内容
                if hasattr(self, '_non_stream_text') and hasattr(self, '_non_stream_message_id'):
                    self.update_last_message(self._non_stream_text)
                # 清理变量
                if hasattr(self, '_non_stream_text'):
                    delattr(self, '_non_stream_text')
                if hasattr(self, '_non_stream_index'):
                    delattr(self, '_non_stream_index')
                if hasattr(self, '_non_stream_message_id'):
                    delattr(self, '_non_stream_message_id')

            # 检查是否有流式打字机在运行
            if hasattr(self, '_stream_typewriter_timer') and self._stream_typewriter_timer and self._stream_typewriter_timer.isActive():
                self._stream_typewriter_timer.stop()
                self._stream_typewriter_timer.deleteLater()
                self._stream_typewriter_timer = None

            # 立即显示用户消息
            self.add_user_message(USER_NAME, u)
            self.input.clear()

            # 在发送新消息之前，确保清理所有可能存在的message_id
            # 包括文本和语音相关的ID，避免冲突
            if hasattr(self, '_current_message_id'):
                delattr(self, '_current_message_id')
            if hasattr(self, '_current_ai_voice_message_id'):
                delattr(self, '_current_ai_voice_message_id')

            # 如果已有任务在运行，先取消
            if self.worker and self.worker.isRunning():
                self.cancel_current_task()
                return

            # 清空当前响应缓冲
            self.current_response = ""

            # 确保worker被清理
            if self.worker:
                self.worker.deleteLater()
                self.worker = None

            # 架构设计：
            # 1. 博弈论模式：必须使用非流式（需要完整响应进行多轮思考）
            # 2. 普通模式：统一使用流式（更好的用户体验，统一的打字机效果）
            # 这样简化了代码，避免了重复的打字机效果实现

            # 博弈论模式必须使用非流式（需要完整响应进行多轮思考）
            if self.self_game_enabled:
                # 博弈论模式：使用非流式接口（放入后台线程）
                # 使用配置中的API服务器地址和端口
                api_url = f"http://{config.api_server.host}:{config.api_server.port}/chat"
                data = {"message": u, "stream": False, "use_self_game": True}

                from system.config import config as _cfg
                if _cfg.system.voice_enabled and _cfg.voice_realtime.voice_mode in ["hybrid", "end2end"]:
                    data["return_audio"] = True

                # 创建并启动非流式worker
                self.worker = ChatWindow._NonStreamHttpWorker(api_url, data)
                self.worker.status.connect(lambda st: self.progress_widget.status_label.setText(st))
                self.worker.error.connect(lambda err: (self.progress_widget.stop_loading(), self.add_user_message("系统", f"❌ 博弈论调用错误: {err}")))
                def _on_finish_text(text):
                    self.progress_widget.stop_loading()
                    self._start_non_stream_typewriter(text)
                self.worker.finished_text.connect(_on_finish_text)
                self.worker.start()
                return
            else:
                # 普通模式：根据配置决定使用流式还是非流式接口
                if self.streaming_mode:
                    # 流式模式
                    # 使用配置中的API服务器地址和端口
                    api_url = f"http://{config.api_server.host}:{config.api_server.port}/chat/stream"
                    data = {"message": u, "stream": True, "use_self_game": False}
                else:
                    # 非流式模式
                    # 使用配置中的API服务器地址和端口
                    api_url = f"http://{config.api_server.host}:{config.api_server.port}/chat"
                    data = {"message": u, "stream": False, "use_self_game": False}

                from system.config import config as _cfg
                if _cfg.system.voice_enabled and _cfg.voice_realtime.voice_mode in ["hybrid", "end2end"]:
                    data["return_audio"] = True

                if self.streaming_mode:
                    # 创建并启动流式worker
                    self.worker = _StreamHttpWorker(api_url, data)
                    # 复用现有的流式UI更新逻辑
                    self.worker.status.connect(lambda st: self.progress_widget.status_label.setText(st))
                    self.worker.error.connect(lambda err: (self.progress_widget.stop_loading(), self.add_user_message("系统", f"❌ 流式调用错误: {err}")))
                    # 将返回的data_str包裹成伪SSE处理路径，直接复用append_response_chunk节流更新
                    def _on_chunk(data_str):
                        # 过滤session_id与audio_url行，保持与handle_streaming_response一致
                        if data_str.startswith('session_id: '):
                            return
                        if data_str.startswith('audio_url: '):
                            return
                        self.append_response_chunk(data_str)
                    self.worker.chunk.connect(_on_chunk)
                    self.worker.done.connect(self.finalize_streaming_response)
                    self.worker.start()
                else:
                    # 创建并启动非流式worker
                    self.worker = _NonStreamHttpWorker(api_url, data)
                    self.worker.status.connect(lambda st: self.progress_widget.status_label.setText(st))
                    self.worker.error.connect(lambda err: (self.progress_widget.stop_loading(), self.add_user_message("系统", f"❌ 非流式调用错误: {err}")))
                    def _on_finish_text(text):
                        self.progress_widget.stop_loading()
                        self._start_non_stream_typewriter(text)
                    self.worker.finished_text.connect(_on_finish_text)
                    self.worker.start()
                return
    
# PyQt不再处理语音输出，由apiserver直接交给voice/output处理

    def update_last_message(self, new_text):
        """更新最后一条消息的内容"""
        # 处理消息格式化
        from ui.response_utils import extract_message
        msg = extract_message(new_text)
        content_html = str(msg).replace('\\n', '\n').replace('\n', '<br>')

        # 优先使用当前消息ID（流式更新时设置的）
        message_id = None
        message_source = ""
        if hasattr(self, '_current_message_id') and self._current_message_id:
            message_id = self._current_message_id
            message_source = "text"
        elif hasattr(self, '_current_ai_voice_message_id') and self._current_ai_voice_message_id:
            message_id = self._current_ai_voice_message_id
            message_source = "voice"
        elif self._messages:
            # 如果没有当前消息ID，查找最后一个消息
            message_id = max(self._messages.keys(), key=lambda x: int(x.split('_')[-1]) if '_' in x else 0)
            message_source = "last"

        # 更新消息内容
        if message_id and message_id in self._messages:
            message_info = self._messages[message_id]

            # 更新存储的消息信息
            message_info['content'] = content_html
            message_info['full_content'] = new_text

            # 尝试使用MessageRenderer更新（更可靠）
            if 'dialog_widget' in message_info and message_info['dialog_widget']:
                try:
                    from ui.message_renderer import MessageRenderer
                    MessageRenderer.update_message_content(message_info['dialog_widget'], content_html)
                except Exception as e:
                    # 如果MessageRenderer失败，使用备用方法
                    content_label = message_info['dialog_widget'].findChild(QLabel)
                    if content_label:
                        content_label.setText(content_html)
                        content_label.setTextFormat(1)  # Qt.RichText
                        content_label.setWordWrap(True)
            # 或者直接更新widget
            elif 'widget' in message_info:
                content_label = message_info['widget'].findChild(QLabel)
                if content_label:
                    # 使用HTML格式化的内容
                    content_label.setText(content_html)
                    # 确保标签可以正确显示HTML
                    content_label.setTextFormat(1)  # Qt.RichText
                    content_label.setWordWrap(True)

        # 自动滚动到底部，确保最新消息可见（使用智能滚动，不打扰正在查看历史的用户）
        self.smart_scroll_to_bottom()

    def _start_non_stream_typewriter(self, full_text):
        """为非流式响应启动打字机效果"""
        # 先清理可能存在的语音消息ID，避免冲突
        if hasattr(self, '_current_ai_voice_message_id'):
            delattr(self, '_current_ai_voice_message_id')

        # 创建空消息
        message_id = self.add_user_message(AI_NAME, "")
        # 同时设置两个message_id变量，确保update_last_message能找到正确的消息
        self._non_stream_message_id = message_id
        self._current_message_id = message_id  # 让update_last_message能正确找到这个消息

        # 初始化打字机变量
        self._non_stream_text = full_text
        self._non_stream_index = 0

        if not hasattr(self, '_non_stream_timer') or self._non_stream_timer is None:
            self._non_stream_timer = QTimer()
            self._non_stream_timer.timeout.connect(self._non_stream_typewriter_tick)

        # 启动定时器（速度可以稍快一些，因为已经有完整文本）
        self._non_stream_timer.start(100)  # 20ms一个字符

    def _non_stream_typewriter_tick(self):
        """非流式响应的打字机效果tick"""
        if not hasattr(self, '_non_stream_text') or not hasattr(self, '_non_stream_index'):
            if hasattr(self, '_non_stream_timer') and self._non_stream_timer:
                self._non_stream_timer.stop()
            return

        # 如果还有字符未显示
        if self._non_stream_index < len(self._non_stream_text):
            # 每次显示1-3个字符
            next_char = self._non_stream_text[self._non_stream_index] if self._non_stream_index < len(self._non_stream_text) else ''
            chars_to_add = 1

            # 如果是英文字符或空格，可以一次显示多个
            if next_char and ord(next_char) < 128:  # ASCII字符
                chars_to_add = min(3, len(self._non_stream_text) - self._non_stream_index)

            self._non_stream_index += chars_to_add
            displayed_text = self._non_stream_text[:self._non_stream_index]

            # 更新消息显示
            self.update_last_message(displayed_text)
        else:
            # 所有字符都显示完了，停止定时器并清理
            self._non_stream_timer.stop()
            self._non_stream_timer.deleteLater()
            self._non_stream_timer = None
            # 清理临时变量
            if hasattr(self, '_non_stream_text'):
                delattr(self, '_non_stream_text')
            if hasattr(self, '_non_stream_index'):
                delattr(self, '_non_stream_index')
            if hasattr(self, '_non_stream_message_id'):
                delattr(self, '_non_stream_message_id')
            # 清理_current_message_id，避免影响后续消息
            if hasattr(self, '_current_message_id'):
                delattr(self, '_current_message_id')

    def append_response_chunk(self, chunk):
        """追加响应片段（流式模式）- 实时显示到普通消息框"""
        # 检查是否为工具调用相关标记
        if any(marker in chunk for marker in ["[TOOL_CALL]", "[TOOL_START]", "[TOOL_RESULT]", "[TOOL_ERROR]"]):
            # 这是工具调用相关标记，不累积到普通消息中
            return

        # 检查是否在工具调用过程中，如果是则创建新的消息框
        if hasattr(self, '_in_tool_call_mode') and self._in_tool_call_mode:
            # 工具调用模式结束，创建新的消息框
            self._in_tool_call_mode = False
            self._current_message_id = None

        # 实时更新显示 - 立即显示到UI
        if not hasattr(self, '_current_message_id') or self._current_message_id is None:
            # 第一次收到chunk时，创建新消息
            self._current_message_id = self.add_user_message(AI_NAME, chunk)
            self.current_response = chunk
        else:
            # 后续chunk，追加到当前消息
            self.current_response += chunk
            # 限制更新频率（节流）
            if not hasattr(self, '_last_update_time'):
                self._last_update_time = 0

            import time
            current_time = time.time()
            # 每50毫秒更新一次UI，减少闪动
            if current_time - self._last_update_time >= 0.05:
                self.update_last_message(self.current_response)
                self._last_update_time = current_time
    
    def finalize_streaming_response(self):
        """完成流式响应 - 立即处理"""
        if self.current_response:
            # 对累积的完整响应进行消息提取（多步自动\n分隔）
            from ui.response_utils import extract_message
            final_message = extract_message(self.current_response)
            
            # 更新最终消息（确保最后的内容完整显示）
            if hasattr(self, '_current_message_id') and self._current_message_id:
                self.update_last_message(final_message)
                # 不要在这里删除_current_message_id，让on_response_finished处理
                # delattr(self, '_current_message_id')
            else:
                self.add_user_message(AI_NAME, final_message)
        
        # 重置current_response和更新时间
        self.current_response = ""
        if hasattr(self, '_last_update_time'):
            delattr(self, '_last_update_time')

        # 立即停止加载状态
        self.progress_widget.stop_loading()
    def toggle_self_game(self):
        """切换博弈论流程开关"""
        self.self_game_enabled = not self.self_game_enabled
        status = '启用' if self.self_game_enabled else '禁用'
        self.add_user_message("系统", f"● 博弈论流程已{status}")
    
    def cancel_current_task(self):
        """取消当前任务 - 优化版本，减少卡顿"""
        # 停止所有打字机效果
        if hasattr(self, '_non_stream_timer') and self._non_stream_timer and self._non_stream_timer.isActive():
            self._non_stream_timer.stop()
            self._non_stream_timer.deleteLater()
            self._non_stream_timer = None
            # 清理非流式打字机变量
            if hasattr(self, '_non_stream_text'):
                delattr(self, '_non_stream_text')
            if hasattr(self, '_non_stream_index'):
                delattr(self, '_non_stream_index')
            if hasattr(self, '_non_stream_message_id'):
                delattr(self, '_non_stream_message_id')
            # 清理当前消息ID
            if hasattr(self, '_current_message_id'):
                delattr(self, '_current_message_id')

        if hasattr(self, '_stream_typewriter_timer') and self._stream_typewriter_timer and self._stream_typewriter_timer.isActive():
            self._stream_typewriter_timer.stop()
            self._stream_typewriter_timer.deleteLater()
            self._stream_typewriter_timer = None

        if hasattr(self, '_typewriter_timer') and self._typewriter_timer and self._typewriter_timer.isActive():
            self._typewriter_timer.stop()
            self._typewriter_timer.deleteLater()
            self._typewriter_timer = None

        # 处理worker
        if self.worker and self.worker.isRunning():
            # 立即设置取消标志
            self.worker.cancel()
            
            # 非阻塞方式处理线程清理
            self.progress_widget.stop_loading()
            self.add_user_message("系统", "🚫 操作已取消")
            
            # 清空当前响应缓冲，避免部分响应显示
            self.current_response = ""
            
            # 使用QTimer延迟处理线程清理，避免UI卡顿
            def cleanup_worker():
                if self.worker:
                    self.worker.quit()
                    if not self.worker.wait(500):  # 只等待500ms
                        self.worker.terminate()
                        self.worker.wait(200)  # 再等待200ms
                    self.worker.deleteLater()
                    self.worker = None
            
            # 50ms后异步清理，避免阻塞UI
            QTimer.singleShot(50, cleanup_worker)
        else:
            self.progress_widget.stop_loading()

    def toggle_full_img(self,e):
        if getattr(self, '_animating', False):  # 动画期间禁止重复点击
            return
        self._animating = True  # 设置动画标志位
        self.full_img^=1  # 立绘展开标志切换
        target_width = self.expanded_width if self.full_img else self.collapsed_width  # 目标宽度：展开或收缩
        
        # --- 立即切换界面状态 ---
        if self.full_img:  # 展开状态 - 进入设置页面
            self.input_wrap.hide()  # 隐藏输入框
            self.chat_stack.setCurrentIndex(1)  # 切换到设置页
            self.side.setCursor(Qt.PointingHandCursor)  # 保持点击指针，可点击收缩
            self.titlebar.text = "SETTING PAGE"
            self.titlebar.update()
            self.side.setStyleSheet(f"""
                QWidget {{
                    background: rgba(17,17,17,{int(BG_ALPHA*255*0.9)});
                    border-radius: 15px;
                    border: 1px solid rgba(255, 255, 255, 80);
                }}
            """)
        else:  # 收缩状态 - 主界面聊天模式
            self.input_wrap.show()  # 显示输入框
            self.chat_stack.setCurrentIndex(0)  # 切换到聊天页
            self.input.setFocus()  # 恢复输入焦点
            self.side.setCursor(Qt.PointingHandCursor)  # 保持点击指针
            self.titlebar.text = "NAGA AGENT"
            self.titlebar.update()
            self.side.setStyleSheet(f"""
                QWidget {{
                    background: rgba(17,17,17,{int(BG_ALPHA*255*0.7)});
                    border-radius: 15px;
                    border: 1px solid rgba(255, 255, 255, 40);
                }}
            """)
        # --- 立即切换界面状态 END ---
        
        # 创建优化后的动画组
        group = QParallelAnimationGroup(self)
        
        # 侧栏宽度动画 - 合并为单个动画
        side_anim = QPropertyAnimation(self.side, b"minimumWidth", self)
        side_anim.setDuration(ANIMATION_DURATION)
        side_anim.setStartValue(self.side.width())
        side_anim.setEndValue(target_width)
        side_anim.setEasingCurve(QEasingCurve.OutCubic)  # 使用更流畅的缓动
        group.addAnimation(side_anim)
        
        side_anim2 = QPropertyAnimation(self.side, b"maximumWidth", self)
        side_anim2.setDuration(ANIMATION_DURATION)
        side_anim2.setStartValue(self.side.width())
        side_anim2.setEndValue(target_width)
        side_anim2.setEasingCurve(QEasingCurve.OutCubic)
        group.addAnimation(side_anim2)
        
        # 输入框动画 - 进入设置时隐藏，退出时显示
        if self.full_img:
            input_hide_anim = QPropertyAnimation(self.input_wrap, b"maximumHeight", self)
            input_hide_anim.setDuration(ANIMATION_DURATION // 2)
            input_hide_anim.setStartValue(self.input_wrap.height())
            input_hide_anim.setEndValue(0)
            input_hide_anim.setEasingCurve(QEasingCurve.OutQuad)
            group.addAnimation(input_hide_anim)
        else:
            input_show_anim = QPropertyAnimation(self.input_wrap, b"maximumHeight", self)
            input_show_anim.setDuration(ANIMATION_DURATION // 2)
            input_show_anim.setStartValue(0)
            input_show_anim.setEndValue(60)
            input_show_anim.setEasingCurve(QEasingCurve.OutQuad)
            group.addAnimation(input_show_anim)
        
        def on_side_width_changed():
            """侧栏宽度变化时实时更新"""
            # Live2D侧栏会自动处理大小调整
            pass
        
        def on_animation_finished():
            self._animating = False  # 动画结束标志
            # Live2D侧栏会自动处理最终调整
            pass
        
        # 连接信号
        side_anim.valueChanged.connect(on_side_width_changed)
        group.finished.connect(on_animation_finished)
        group.start()
        
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
                    self.on_send()
                    return True  # 返回True表示事件已处理，不传递给输入框
                else:
                    # Shift+回车：放行事件，让输入框正常换行
                    return False  # 返回False表示事件继续传递

        # 其他事件（如普通输入）：正常放行
        return super().eventFilter(obj, event)
#====================

    def on_settings_changed(self, setting_key, value):
        """处理设置变化"""
        logger.debug(f"设置变化: {setting_key} = {value}")
        
        # 透明度设置将在保存时统一应用，避免动画卡顿
        if setting_key in ("all", "ui.bg_alpha", "ui.window_bg_alpha"):  # UI透明度变化 #
            # 保存时应用透明度设置
            self.apply_opacity_from_config()
            return
        if setting_key in ("system.stream_mode", "STREAM_MODE"):
            self.streaming_mode = value if setting_key == "system.stream_mode" else value  # 兼容新旧键名 #
            self.add_user_message("系统", f"● 流式模式已{'启用' if self.streaming_mode else '禁用'}")
        elif setting_key in ("system.debug", "DEBUG"):
            self.add_user_message("系统", f"● 调试模式已{'启用' if value else '禁用'}")
        
        # 发送设置变化信号给其他组件
        # 这里可以根据需要添加更多处理逻辑

    def apply_opacity_from_config(self):
        """从配置中应用UI透明度(聊天区/输入框/侧栏/窗口)"""
        # 更新全局变量，保持其它逻辑一致 #
        global BG_ALPHA, WINDOW_BG_ALPHA
        # 直接读取配置值，避免函数调用开销
        BG_ALPHA = config.ui.bg_alpha
        WINDOW_BG_ALPHA = config.ui.window_bg_alpha

        # 计算alpha #
        alpha_px = int(BG_ALPHA * 255)

        # 更新聊天区域背景 - 现在使用透明背景，对话框有自己的背景
        self.chat_content.setStyleSheet(f"""
            QWidget {{
                background: transparent;
                border: none;
            }}
        """)

        # 更新输入框背景 #
        fontfam, fontsize = 'Lucida Console', 16
        self.input.setStyleSheet(f"""
            QTextEdit {{
                background: rgba(17,17,17,{alpha_px});
                color: #fff;
                border-radius: 15px;
                border: 1px solid rgba(255, 255, 255, 50);
                font: {fontsize}pt '{fontfam}';
                padding: 8px;
            }}
        """)

        # 更新侧栏背景 #
        if hasattr(self, 'side') and isinstance(self.side, QWidget):
            try:
                self.side.set_background_alpha(alpha_px)
            except Exception:
                pass

        # 更新主窗口背景 #
        self.set_window_background_alpha(WINDOW_BG_ALPHA)


    def set_window_background_alpha(self, alpha):
        """设置整个窗口的背景透明度
        Args:
            alpha: 透明度值，可以是:
                   - 0-255的整数 (PyQt原生格式)
                   - 0.0-1.0的浮点数 (百分比格式)
        """
        global WINDOW_BG_ALPHA
        
        # 处理不同格式的输入
        if isinstance(alpha, float) and 0.0 <= alpha <= 1.0:
            # 浮点数格式：0.0-1.0 转换为 0-255
            WINDOW_BG_ALPHA = int(alpha * 255)
        elif isinstance(alpha, int) and 0 <= alpha <= 255:
            # 整数格式：0-255
            WINDOW_BG_ALPHA = alpha
        else:
            logger.warning(f"警告：无效的透明度值 {alpha}，应为0-255的整数或0.0-1.0的浮点数")
            return
        
        # 更新CSS样式表
        self.setStyleSheet(f"""
            ChatWindow {{
                background: rgba(25, 25, 25, {WINDOW_BG_ALPHA});
                border-radius: 20px;
                border: 1px solid rgba(255, 255, 255, 30);
            }}
        """)
    
        # 触发重绘
        self.update()

        logger.info(f"✅ 窗口背景透明度已设置为: {WINDOW_BG_ALPHA}/255 ({WINDOW_BG_ALPHA/255*100:.1f}%不透明度)")

    def open_mind_map(self):
        """打开心智云图"""
        try:
            # 检查是否存在知识图谱文件
            graph_file = "logs/knowledge_graph/graph.html"
            quintuples_file = "logs/knowledge_graph/quintuples.json"
            
            # 如果quintuples.json存在，删除现有的graph.html并重新生成
            if os.path.exists(quintuples_file):
                # 如果graph.html存在，先删除它
                if os.path.exists(graph_file):
                    try:
                        os.remove(graph_file)
                        logger.debug(f"已删除旧的graph.html文件")
                    except Exception as e:
                        logger.error(f"删除graph.html文件失败: {e}")
                
                # 生成新的HTML
                self.add_user_message("系统", "🔄 正在生成心智云图...")
                try:
                    from summer_memory.quintuple_visualize_v2 import visualize_quintuples
                    visualize_quintuples()
                    if os.path.exists(graph_file):
                        import webbrowser
                        # 获取正确的绝对路径
                        if os.path.isabs(graph_file):
                            abs_graph_path = graph_file
                        else:
                            # 如果是相对路径，基于项目根目录构建绝对路径
                            current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                            abs_graph_path = os.path.join(current_dir, graph_file)
                        
                        webbrowser.open("file:///" + abs_graph_path)
                        self.add_user_message("系统", "🧠 心智云图已生成并打开")
                    else:
                        self.add_user_message("系统", "❌ 心智云图生成失败")
                except Exception as e:
                    self.add_user_message("系统", f"❌ 生成心智云图失败: {str(e)}")
            else:
                # 没有五元组数据，提示用户
                self.add_user_message("系统", "❌ 未找到五元组数据，请先进行对话以生成知识图谱")
        except Exception as e:
            self.add_user_message("系统", f"❌ 打开心智云图失败: {str(e)}")
    
    def initialize_live2d(self):
        """初始化Live2D"""
        if self.live2d_enabled and self.live2d_model_path:
            if os.path.exists(self.live2d_model_path):
                self.side.set_live2d_model(self.live2d_model_path) # 调用已有输出逻辑
            else:
                logger.warning(f"⚠️ Live2D模型文件不存在: {self.live2d_model_path}")
        else:
            logger.info("📝 Live2D功能未启用或未配置模型路径")
    
    def on_live2d_model_loaded(self, success):
        """Live2D模型加载状态回调"""
        if success:
            logger.info("✅ Live2D模型已成功加载")
        else:
            logger.info("🔄 已回退到图片模式")
    
    def on_live2d_error(self, error_msg):
        """Live2D错误回调"""
        self.add_user_message("系统", f"❌ Live2D错误: {error_msg}")
    
    def set_live2d_model(self, model_path):
        """设置Live2D模型"""
        if not os.path.exists(model_path):
            self.add_user_message("系统", f"❌ Live2D模型文件不存在: {model_path}")
            return False
        
        self.live2d_model_path = model_path
        self.live2d_enabled = True
        
        self.add_user_message("系统", "🔄 正在切换Live2D模型...")
        success = self.side.set_live2d_model(model_path)
        
        if success:
            self.add_user_message("系统", "✅ Live2D模型切换成功")
        else:
            self.add_user_message("系统", "⚠️ Live2D模型切换失败，已回退到图片模式")
        
        return success
    
    def set_fallback_image(self, image_path):
        """设置回退图片"""
        if not os.path.exists(image_path):
            self.add_user_message("系统", f"❌ 图片文件不存在: {image_path}")
            return False
        
        self.side.set_fallback_image(image_path)
        self.add_user_message("系统", f"✅ 回退图片已设置: {os.path.basename(image_path)}")
        return True
    
    def get_display_mode(self):
        """获取当前显示模式"""
        return self.side.get_display_mode()
    
    def is_live2d_available(self):
        """检查Live2D是否可用"""
        return self.side.is_live2d_available()

    def toggle_voice_realtime(self):
        """切换实时语音对话状态"""
        # 添加防抖动机制
        import time
        current_time = time.time()
        if hasattr(self, '_last_voice_toggle_time'):
            if current_time - self._last_voice_toggle_time < 1.0:  # 1秒内防止重复点击
                return
        self._last_voice_toggle_time = current_time

        # 如果是超时断开状态，视为未激活
        if getattr(self, '_is_timeout_disconnect', False):
            self.voice_realtime_active = False

        if not self.voice_realtime_active:
            # 启动语音服务
            self.start_voice_realtime()
        else:
            # 语音输入功能由统一语音管理器处理
            from system.config import config
            if config.voice_realtime.provider == "local" and hasattr(self.voice_integration, 'voice_integration'):
                # 本地模式：切换录音
                if hasattr(self.voice_integration.voice_integration, 'toggle_recording'):
                    self.voice_integration.voice_integration.toggle_recording()
                    return

            # 其他模式：停止服务
            self.stop_voice_realtime()

    def start_voice_realtime(self):
        """启动实时语音对话"""
        try:
            # 注意：不要在这里清理超时标记，让 stop_voice 使用它来判断是否显示停止消息

            # 检查配置
            from system.config import config

            # 如果使用本地模式，不需要API密钥
            if config.voice_realtime.provider == "local":
                # 本地模式只需要ASR服务运行
                pass
            elif not config.voice_realtime.api_key:
                self.add_user_message("系统", "❌ 请先在设置中配置语音服务API密钥")
                return

            # 使用统一语音管理器启动
            from voice.input.unified_voice_manager import VoiceMode

            # 确定要使用的模式
            mode = getattr(self, 'default_voice_mode', None)

            success = self.voice_integration.start_voice(mode=mode)

            if not success:
                self.add_user_message("系统", "❌ 语音服务启动失败，请检查配置和服务状态")
            else:
                # 设置激活标志
                self.voice_realtime_active = True

        except Exception as e:
            self.add_user_message("系统", f"❌ 启动语音服务失败: {str(e)}")

    def stop_voice_realtime(self):
        """停止实时语音对话"""
        try:
            # 检查是否因为超时断开而自动调用的停止
            if getattr(self, '_is_timeout_disconnect', False):
                # 超时断开的情况下，清理标记后直接返回
                # 因为状态已经在on_voice_status中处理过了
                self._is_timeout_disconnect = False
                return True

            # 使用线程安全的语音集成管理器停止语音
            success = self.voice_integration.stop_voice()

            # 无论成功与否，都设置标志为False
            self.voice_realtime_active = False

            if not success:
                self.add_user_message("系统", "⚠️ 语音服务未在运行")

        except Exception as e:
            self.voice_realtime_active = False  # 确保异常时也设置为False
            self.add_user_message("系统", f"❌ 停止语音服务失败: {str(e)}")


if __name__=="__main__":
    app = QApplication(sys.argv)
    win = ChatWindow()
    win.show()
    sys.exit(app.exec_())
