import sys, os; sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))
from .styles.button_factory import ButtonFactory
from nagaagent_core.vendors.PyQt5.QtWidgets import QApplication, QWidget, QTextEdit, QSizePolicy, QHBoxLayout, QLabel, QVBoxLayout, QStackedLayout, QPushButton, QStackedWidget, QDesktopWidget, QScrollArea, QSplitter, QFileDialog, QMessageBox, QFrame  # 统一入口 #
from nagaagent_core.vendors.PyQt5.QtCore import Qt, QRect, QParallelAnimationGroup, QPropertyAnimation, QEasingCurve, QTimer, QThread, pyqtSignal, QObject  # 统一入口 #
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
# 语音输入功能已迁移到统一语音管理器
import json
from nagaagent_core.core import requests
from pathlib import Path
import time
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
    def __init__(s, text, parent=None):
        super().__init__(parent)
        s.text = text
        s.setFixedHeight(100)
        s.setAttribute(Qt.WA_TranslucentBackground)
        s._offset = None
        # mac风格按钮
        for i,(txt,color,hover,cb) in enumerate([
            ('-','#FFBD2E','#ffe084',lambda:s.parent().showMinimized()),
            ('×','#FF5F57','#ff8783',lambda:s.parent().close())]):
            btn=QPushButton(txt,s)
            btn.setGeometry(s.width()-MAC_BTN_MARGIN-MAC_BTN_SIZE*(2-i)-MAC_BTN_GAP*(1-i),36,MAC_BTN_SIZE,MAC_BTN_SIZE)
            btn.setStyleSheet(f"QPushButton{{background:{color};border:none;border-radius:{MAC_BTN_SIZE//2}px;color:#fff;font:18pt;}}QPushButton:hover{{background:{hover};}}")
            btn.clicked.connect(cb)
            setattr(s,f'btn_{"min close".split()[i]}',btn)
    def mousePressEvent(s, e):
        if e.button()==Qt.LeftButton: s._offset = e.globalPos()-s.parent().frameGeometry().topLeft()
    def mouseMoveEvent(s, e):
        if s._offset and e.buttons()&Qt.LeftButton:
            s.parent().move(e.globalPos()-s._offset)
    def mouseReleaseEvent(s,e):s._offset=None
    def paintEvent(s, e):
        qp = QPainter(s)
        qp.setRenderHint(QPainter.Antialiasing)
        w, h = s.width(), s.height()
        qp.setPen(QColor(255,255,255,180))
        qp.drawLine(0, 2, w, 2)
        qp.drawLine(0, h-3, w, h-3)
        font = QFont("Consolas", max(10, (h-40)//2), QFont.Bold)
        qp.setFont(font)
        rect = QRect(0, 20, w, h-40)
        for dx,dy in [(-1,0),(1,0),(0,-1),(0,1)]:
            qp.setPen(QColor(0,0,0))
            qp.drawText(rect.translated(dx,dy), Qt.AlignCenter, s.text)
        qp.setPen(QColor(255,255,255))
        qp.drawText(rect, Qt.AlignCenter, s.text)
    def resizeEvent(s,e):
        x=s.width()-MAC_BTN_MARGIN
        for i,btn in enumerate([s.btn_min,s.btn_close]):btn.move(x-MAC_BTN_SIZE*(2-i)-MAC_BTN_GAP*(1-i),36)


class ChatWindow(QWidget):
    def __init__(s):
        super().__init__()
        
        # 获取屏幕大小并自适应
        desktop = QDesktopWidget()
        screen_rect = desktop.screenGeometry()
        # 设置为屏幕大小的80%
        window_width = int(screen_rect.width() * 0.8)
        window_height = int(screen_rect.height() * 0.8)
        s.resize(window_width, window_height)
        
        # 窗口居中显示
        x = (screen_rect.width() - window_width) // 2
        y = (screen_rect.height() - window_height) // 2
        s.move(x, y)
        
        # 移除置顶标志，保留无边框
        s.setWindowFlags(Qt.FramelessWindowHint)
        s.setAttribute(Qt.WA_TranslucentBackground)
        
        # 添加窗口背景和拖动支持
        s._offset = None
        s.setStyleSheet(f"""
            ChatWindow {{
                background: rgba(25, 25, 25, {WINDOW_BG_ALPHA});
                border-radius: 20px;
                border: 1px solid rgba(255, 255, 255, 30);
            }}
        """)
        
        fontfam,fontsize='Lucida Console',16
        
        # 创建主分割器，替换原来的HBoxLayout
        s.main_splitter = QSplitter(Qt.Horizontal, s)
        s.main_splitter.setStyleSheet("""
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
        chat_area=QWidget()
        chat_area.setMinimumWidth(400)  # 设置最小宽度
        vlay=QVBoxLayout(chat_area);vlay.setContentsMargins(0,0,0,0);vlay.setSpacing(10)
        
        # 用QStackedWidget管理聊天区和设置页
        s.chat_stack = QStackedWidget(chat_area)
        s.chat_stack.setStyleSheet("""
            QStackedWidget {
                background: transparent;
                border: none;
            }
        """) # 保证背景穿透
        
        # 创建聊天页面容器
        s.chat_page = QWidget()
        s.chat_page.setStyleSheet("""
            QWidget {
                background: transparent;
                border: none;
            }
        """)
        
        # 创建滚动区域来容纳消息对话框
        s.chat_scroll_area = QScrollArea(s.chat_page)
        s.chat_scroll_area.setWidgetResizable(True)
        s.chat_scroll_area.setStyleSheet("""
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
        s.chat_content = QWidget()
        s.chat_content.setStyleSheet("""
            QWidget {
                background: transparent;
                border: none;
            }
        """)
        
        # 创建垂直布局来排列消息对话框
        s.chat_layout = QVBoxLayout(s.chat_content)
        s.chat_layout.setContentsMargins(10, 10, 10, 10)
        s.chat_layout.setSpacing(10)
        s.chat_layout.addStretch()  # 添加弹性空间，让消息从顶部开始
        
        s.chat_scroll_area.setWidget(s.chat_content)
        
        # 创建聊天页面布局
        chat_page_layout = QVBoxLayout(s.chat_page)
        chat_page_layout.setContentsMargins(0, 0, 0, 0)
        chat_page_layout.addWidget(s.chat_scroll_area)
        
        s.chat_stack.addWidget(s.chat_page) # index 0 聊天页
        s.settings_page = s.create_settings_page() # index 1 设置页
        s.chat_stack.addWidget(s.settings_page)
        vlay.addWidget(s.chat_stack, 1)
        
        # 添加进度显示组件
        s.progress_widget = EnhancedProgressWidget(chat_area)
        vlay.addWidget(s.progress_widget)
        
        s.input_wrap=QWidget(chat_area)
        s.input_wrap.setFixedHeight(60)  # 增加输入框包装器的高度，与字体大小匹配
        hlay=QHBoxLayout(s.input_wrap);hlay.setContentsMargins(0,0,0,0);hlay.setSpacing(8)
        s.prompt=QLabel('>',s.input_wrap)
        s.prompt.setStyleSheet(f"color:#fff;font:{fontsize}pt '{fontfam}';background:transparent;")
        hlay.addWidget(s.prompt)
        s.input = QTextEdit(s.input_wrap)
        s.input.setStyleSheet(f"""
            QTextEdit {{
                background: rgba(17,17,17,{int(BG_ALPHA*255)});
                color: #fff;
                border-radius: 15px;
                border: 1px solid rgba(255, 255, 255, 50);
                font: {fontsize}pt '{fontfam}';
                padding: 8px;
            }}
        """)
        s.input.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        s.input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        hlay.addWidget(s.input)
        
        # 添加文档上传按钮
        s.upload_btn = ButtonFactory.create_action_button("upload", s.input_wrap)
        hlay.addWidget(s.upload_btn)
        
        # 添加心智云图按钮
        s.mind_map_btn = ButtonFactory.create_action_button("mind_map", s.input_wrap)
        hlay.addWidget(s.mind_map_btn)

        # 添加博弈论启动/关闭按钮
        s.self_game_enabled = False
        s.self_game_btn = ButtonFactory.create_action_button("self_game", s.input_wrap)
        s.self_game_btn.setToolTip("启动/关闭博弈论流程")
        hlay.addWidget(s.self_game_btn)
        
        # 添加实时语音按钮
        s.voice_realtime_btn = ButtonFactory.create_action_button("voice_realtime", s.input_wrap)
        s.voice_realtime_btn.setToolTip("启动/关闭实时语音对话")
        hlay.addWidget(s.voice_realtime_btn)

        vlay.addWidget(s.input_wrap,0)
        
        # 将聊天区域添加到分割器
        s.main_splitter.addWidget(chat_area)
        
        # 侧栏（Live2D/图片显示区域）- 使用Live2D侧栏Widget
        s.side = Live2DSideWidget()
        s.collapsed_width = 400  # 收缩状态宽度
        s.expanded_width = 800  # 展开状态宽度
        s.side.setMinimumWidth(s.collapsed_width)  # 设置最小宽度为收缩状态
        s.side.setMaximumWidth(s.collapsed_width)  # 初始状态为收缩
        
        # 优化侧栏的悬停效果，使用QPainter绘制
        def setup_side_hover_effects():
            def original_enter(e):
                s.side.set_background_alpha(int(BG_ALPHA * 0.5 * 255))
                s.side.set_border_alpha(80)
            def original_leave(e):
                s.side.set_background_alpha(int(BG_ALPHA * 255))
                s.side.set_border_alpha(50)
            return original_enter, original_leave
        
        s.side_hover_enter, s.side_hover_leave = setup_side_hover_effects()
        s.side.enterEvent = s.side_hover_enter
        s.side.leaveEvent = s.side_hover_leave
        
        # 设置鼠标指针，提示可点击
        s.side.setCursor(Qt.PointingHandCursor)
        
        # 设置默认图片
        default_image = os.path.join(os.path.dirname(__file__), 'standby.png')
        if os.path.exists(default_image):
            s.side.set_fallback_image(default_image)
        
        # 连接Live2D侧栏的信号
        s.side.model_loaded.connect(s.on_live2d_model_loaded)
        s.side.error_occurred.connect(s.on_live2d_error)
        
        # 创建昵称标签（保持原有功能）
        from system.config import config as sys_config  # 导入配置
        nick=QLabel(f"● {AI_NAME}{sys_config.system.version}",s.side)
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
        s.main_splitter.addWidget(s.side)
        
        # 设置分割器的初始比例 - 侧栏收缩状态
        s.main_splitter.setSizes([window_width - s.collapsed_width - 20, s.collapsed_width])  # 大部分给聊天区域
        
        # 创建包含分割器的主布局
        main=QVBoxLayout(s)
        main.setContentsMargins(10,110,10,10)
        main.addWidget(s.main_splitter)
        
        s.nick=nick
        s.naga=None  # conversation_core已删除，相关功能已迁移到apiserver
        s.worker=None
        s.full_img=0 # 立绘展开标志，0=收缩状态，1=展开状态
        s.streaming_mode = sys_config.system.stream_mode  # 根据配置决定是否使用流式模式
        s.current_response = ""  # 当前响应缓冲
        s.animating = False  # 动画标志位，动画期间为True
        s._img_inited = False  # 标志变量，图片自适应只在初始化时触发一次

        # Live2D相关配置
        s.live2d_enabled = sys_config.live2d.enabled  # 是否启用Live2D
        s.live2d_model_path = sys_config.live2d.model_path  # Live2D模型路径
        
        # 实时语音相关
        s.voice_realtime_client = None  # 语音客户端（废弃，使用线程安全版本）
        s.voice_realtime_active = False  # 是否激活
        s.voice_realtime_state = "idle"  # idle/listening/recording/ai_speaking

        # 创建统一的语音管理器
        # 根据配置选择语音模式
        from system.config import config
        from voice.input.unified_voice_manager import UnifiedVoiceManager, VoiceMode

        s.voice_integration = UnifiedVoiceManager(s)

        # 根据配置确定默认模式
        if config.voice_realtime.voice_mode != "auto":
            # 使用指定的模式
            mode_map = {
                "local": VoiceMode.LOCAL,
                "end2end": VoiceMode.END_TO_END,
                "hybrid": VoiceMode.HYBRID
            }
            s.default_voice_mode = mode_map.get(config.voice_realtime.voice_mode, None)
        else:
            # 自动选择模式
            if config.voice_realtime.provider == "local":
                s.default_voice_mode = VoiceMode.LOCAL
            elif getattr(config.voice_realtime, 'use_api_server', False):
                s.default_voice_mode = VoiceMode.HYBRID
            else:
                s.default_voice_mode = VoiceMode.END_TO_END

        logger.info(f"[UI] 使用统一语音管理器，默认模式: {s.default_voice_mode.value if s.default_voice_mode else 'auto'}")

        # 初始化消息存储
        s._messages = {}
        s._message_counter = 0
        
        # 加载持久化历史对话到前端
        s._load_persistent_context_to_ui()
        
        # 连接进度组件信号
        s.progress_widget.cancel_requested.connect(s.cancel_current_task)
        
        s.input.textChanged.connect(s.adjust_input_height)
        s.input.installEventFilter(s)
        
        # 连接文档上传按钮
        s.upload_btn.clicked.connect(s.upload_document)
        
        # 连接心智云图按钮
        s.mind_map_btn.clicked.connect(s.open_mind_map)
        # 连接博弈论按钮
        s.self_game_btn.clicked.connect(s.toggle_self_game)
        # 连接实时语音按钮
        s.voice_realtime_btn.clicked.connect(s.toggle_voice_realtime)
        
        s.setLayout(main)
        s.titlebar = TitleBar('NAGA AGENT', s)
        s.titlebar.setGeometry(0,0,s.width(),100)
        s.side.mousePressEvent=s.toggle_full_img # 侧栏点击切换聊天/设置
        s.resizeEvent(None)  # 强制自适应一次，修复图片初始尺寸
        
        # 初始化Live2D（如果启用）
        s.initialize_live2d()

    # --- 后台HTTP请求Worker（避免主线程阻塞） ---
    class _StreamHttpWorker(QThread):
        chunk = pyqtSignal(str)
        done = pyqtSignal()
        error = pyqtSignal(str)
        status = pyqtSignal(str)

        def __init__(self, url, payload):
            super().__init__()
            self.url = url
            self.payload = payload
            self._cancelled = False

        def cancel(self):
            self._cancelled = True

        def run(self):
            try:
                import requests
                self.status.emit("连接到AI...")
                resp = requests.post(self.url, json=self.payload, timeout=120, stream=True)
                if resp.status_code != 200:
                    self.error.emit(f"流式调用失败: {resp.text}")
                    return
                self.status.emit("正在生成回复...")
                for line in resp.iter_lines():
                    if self._cancelled:
                        return
                    if line:
                        line_str = line.decode('utf-8')
                        if line_str.startswith('data: '):
                            data_str = line_str[6:]
                            if data_str == '[DONE]':
                                break
                            # 直接把内容行交回主线程，由现有逻辑处理
                            self.chunk.emit(data_str)
                self.done.emit()
            except Exception as e:
                self.error.emit(str(e))

    class _NonStreamHttpWorker(QThread):
        finished_text = pyqtSignal(str)
        error = pyqtSignal(str)
        status = pyqtSignal(str)

        def __init__(self, url, payload):
            super().__init__()
            self.url = url
            self.payload = payload
            self._cancelled = False

        def cancel(self):
            self._cancelled = True

        def run(self):
            try:
                import requests
                self.status.emit("正在思考...")
                resp = requests.post(self.url, json=self.payload, timeout=120)
                if self._cancelled:
                    return
                if resp.status_code != 200:
                    self.error.emit(f"非流式调用失败: {resp.text}")
                    return
                try:
                    result = resp.json()
                    from ui.response_utils import extract_message
                    final_message = extract_message(result.get("response", ""))
                except Exception:
                    final_message = resp.text
                self.finished_text.emit(str(final_message))
            except Exception as e:
                self.error.emit(str(e))

    def create_settings_page(s):
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
        s.settings_widget = ElegantSettingsWidget(scroll_content)
        s.settings_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        s.settings_widget.settings_changed.connect(s.on_settings_changed)
        scroll_layout.addWidget(s.settings_widget, 1)
        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area, 1)
        return page

    def resizeEvent(s, e):
        if getattr(s, '_animating', False):  # 动画期间跳过所有重绘操作，避免卡顿
            return
        # 图片调整现在由Live2DSideWidget内部处理
        super().resizeEvent(e)
            

    def adjust_input_height(s):
        doc = s.input.document()
        h = int(doc.size().height())+10
        s.input.setFixedHeight(min(max(60, h), 150))  # 增加最小高度，与字体大小匹配
        s.input_wrap.setFixedHeight(s.input.height())
        
    def eventFilter(s, obj, event):
        if obj is s.input and event.type()==6:
            if event.key()==Qt.Key_Return and not (event.modifiers()&Qt.ShiftModifier):
                s.on_send();return True
        return False
    def _ensure_stretch_at_end(s):
        """确保弹性空间在布局的最后"""
        # 移除所有现有的stretch
        for i in reversed(range(s.chat_layout.count())):
            item = s.chat_layout.itemAt(i)
            if item and not item.widget():  # 这是一个spacer/stretch
                s.chat_layout.removeItem(item)

        # 在最后添加一个新的stretch
        s.chat_layout.addStretch()

    def add_user_message(s, name, content, is_streaming=False):
        """添加用户消息"""
        from ui.response_utils import extract_message
        msg = extract_message(content)
        content_html = str(msg).replace('\\n', '\n').replace('\n', '<br>')

        # 生成消息ID
        if not hasattr(s, '_message_counter'):
            s._message_counter = 0
        s._message_counter += 1
        message_id = f"msg_{s._message_counter}"

        # 初始化消息存储
        if not hasattr(s, '_messages'):
            s._messages = {}

        # 存储消息信息
        s._messages[message_id] = {
            'name': name,
            'content': content_html,
            'full_content': content,
            'dialog_widget': None
        }

        # 使用消息渲染器创建对话框
        if name == "系统":
            message_dialog = MessageRenderer.create_system_message(name, content_html, s.chat_content)
        else:
            message_dialog = MessageRenderer.create_user_message(name, content_html, s.chat_content)

        # 存储对话框引用
        s._messages[message_id]['dialog_widget'] = message_dialog

        # 先移除stretch
        stretch_found = False
        stretch_index = -1
        for i in reversed(range(s.chat_layout.count())):
            item = s.chat_layout.itemAt(i)
            if item and not item.widget():  # 找到stretch
                s.chat_layout.removeItem(item)
                stretch_found = True
                stretch_index = i
                break

        # 添加消息
        s.chat_layout.addWidget(message_dialog)

        # 重新添加stretch到最后
        s.chat_layout.addStretch()

        # 滚动到底部
        s.scroll_to_bottom()

        return message_id
    
    
    def scroll_to_bottom(s):
        """滚动到聊天区域底部"""
        # 使用QTimer延迟滚动，确保布局完成
        QTimer.singleShot(10, lambda: s.chat_scroll_area.verticalScrollBar().setValue(
            s.chat_scroll_area.verticalScrollBar().maximum()
        ))

    def smart_scroll_to_bottom(s):
        """智能滚动到底部（如果用户正在查看历史消息，则不滚动）"""
        scrollbar = s.chat_scroll_area.verticalScrollBar()
        # 检查是否已经在底部附近（允许50像素的误差）
        is_at_bottom = scrollbar.value() >= scrollbar.maximum() - 50

        # 如果本来就在底部附近，则自动滚动到最新消息
        if is_at_bottom:
            s.scroll_to_bottom()
        
    def _load_persistent_context_to_ui(s):
        """从持久化上下文加载历史对话到前端UI"""
        try:
            # 检查是否启用持久化上下文
            if not config.api.persistent_context:
                logger.info("📝 持久化上下文功能已禁用，跳过历史记录加载")
                return

            # 使用消息渲染器加载历史对话到UI
            from ui.message_renderer import MessageRenderer

            ui_messages = MessageRenderer.load_persistent_context_to_ui(
                parent_widget=s.chat_content,
                max_messages=config.api.max_history_rounds * 2
            )

            if ui_messages:
                # 先移除stretch
                for i in reversed(range(s.chat_layout.count())):
                    item = s.chat_layout.itemAt(i)
                    if item and not item.widget():  # 找到stretch
                        s.chat_layout.removeItem(item)
                        break

                # 将历史消息添加到UI布局中
                for message_id, message_info, dialog in ui_messages:
                    s.chat_layout.addWidget(dialog)

                    # 存储到消息管理器中
                    s._messages[message_id] = message_info

                # 重新添加stretch到最后
                s.chat_layout.addStretch()

                # 更新消息计数器
                s._message_counter = len(ui_messages)

                # 滚动到底部显示最新消息
                s.scroll_to_bottom()

                logger.info(f"✅ 前端UI已加载 {len(ui_messages)} 条历史对话")
            else:
                logger.info("📝 前端UI未找到历史对话记录")

        except ImportError as e:
            logger.warning(f"⚠️ 日志解析器模块未找到，跳过前端历史记录加载: {e}")
        except Exception as e:
            logger.error(f"❌ 前端加载持久化上下文失败: {e}")
            # 失败时不影响正常使用，继续使用空上下文
            logger.info("💡 将继续使用空上下文，不影响正常对话功能")
    
    def clear_chat_history(s):
        """清除聊天历史记录"""
        # 清除所有消息对话框
        if hasattr(s, '_messages'):
            for message_id, message_info in s._messages.items():
                dialog_widget = message_info.get('dialog_widget')
                if dialog_widget:
                    dialog_widget.deleteLater()
            s._messages.clear()

        # 清除布局中的所有widget
        while s.chat_layout.count() > 0:
            item = s.chat_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        # 重新添加stretch到最后
        s.chat_layout.addStretch()
    def on_send(s):
        u = s.input.toPlainText().strip()
        if u:
            # 停止任何正在进行的打字机效果
            if hasattr(s, '_non_stream_timer') and s._non_stream_timer and s._non_stream_timer.isActive():
                s._non_stream_timer.stop()
                s._non_stream_timer.deleteLater()
                s._non_stream_timer = None
                # 如果有未显示完的文本，立即显示完整内容
                if hasattr(s, '_non_stream_text') and hasattr(s, '_non_stream_message_id'):
                    s.update_last_message(s._non_stream_text)
                # 清理变量
                if hasattr(s, '_non_stream_text'):
                    delattr(s, '_non_stream_text')
                if hasattr(s, '_non_stream_index'):
                    delattr(s, '_non_stream_index')
                if hasattr(s, '_non_stream_message_id'):
                    delattr(s, '_non_stream_message_id')

            # 检查是否有流式打字机在运行
            if hasattr(s, '_stream_typewriter_timer') and s._stream_typewriter_timer and s._stream_typewriter_timer.isActive():
                s._stream_typewriter_timer.stop()
                s._stream_typewriter_timer.deleteLater()
                s._stream_typewriter_timer = None

            # 立即显示用户消息
            s.add_user_message(USER_NAME, u)
            s.input.clear()

            # 在发送新消息之前，确保清理所有可能存在的message_id
            # 包括文本和语音相关的ID，避免冲突
            if hasattr(s, '_current_message_id'):
                delattr(s, '_current_message_id')
            if hasattr(s, '_current_ai_voice_message_id'):
                delattr(s, '_current_ai_voice_message_id')

            # 如果已有任务在运行，先取消
            if s.worker and s.worker.isRunning():
                s.cancel_current_task()
                return

            # 清空当前响应缓冲
            s.current_response = ""

            # 确保worker被清理
            if s.worker:
                s.worker.deleteLater()
                s.worker = None

            # 架构设计：
            # 1. 博弈论模式：必须使用非流式（需要完整响应进行多轮思考）
            # 2. 普通模式：统一使用流式（更好的用户体验，统一的打字机效果）
            # 这样简化了代码，避免了重复的打字机效果实现

            # 博弈论模式必须使用非流式（需要完整响应进行多轮思考）
            if s.self_game_enabled:
                # 博弈论模式：使用非流式接口（放入后台线程）
                api_url = "http://localhost:8000/chat"
                data = {"message": u, "stream": False, "use_self_game": True}

                from system.config import config as _cfg
                if _cfg.system.voice_enabled and _cfg.voice_realtime.voice_mode in ["hybrid", "end2end"]:
                    data["return_audio"] = True

                # 创建并启动非流式worker
                s.worker = ChatWindow._NonStreamHttpWorker(api_url, data)
                s.worker.status.connect(lambda st: s.progress_widget.status_label.setText(st))
                s.worker.error.connect(lambda err: (s.progress_widget.stop_loading(), s.add_user_message("系统", f"❌ 博弈论调用错误: {err}")))
                def _on_finish_text(text):
                    s.progress_widget.stop_loading()
                    s._start_non_stream_typewriter(text)
                s.worker.finished_text.connect(_on_finish_text)
                s.worker.start()
                return
            else:
                # 普通模式：统一使用流式接口（放入后台线程）
                api_url = "http://localhost:8000/chat/stream"
                data = {"message": u, "stream": True, "use_self_game": False}

                from system.config import config as _cfg
                if _cfg.system.voice_enabled and _cfg.voice_realtime.voice_mode in ["hybrid", "end2end"]:
                    data["return_audio"] = True

                # 创建并启动流式worker
                s.worker = ChatWindow._StreamHttpWorker(api_url, data)
                # 复用现有的流式UI更新逻辑
                s.worker.status.connect(lambda st: s.progress_widget.status_label.setText(st))
                s.worker.error.connect(lambda err: (s.progress_widget.stop_loading(), s.add_user_message("系统", f"❌ 流式调用错误: {err}")))
                # 将返回的data_str包裹成伪SSE处理路径，直接复用append_response_chunk节流更新
                def _on_chunk(data_str):
                    # 过滤session_id与audio_url行，保持与handle_streaming_response一致
                    if data_str.startswith('session_id: '):
                        return
                    if data_str.startswith('audio_url: '):
                        return
                    s.append_response_chunk(data_str)
                s.worker.chunk.connect(_on_chunk)
                s.worker.done.connect(s.finalize_streaming_response)
                s.worker.start()
                return
    
# PyQt不再处理语音输出，由apiserver直接交给voice/output处理

    def handle_streaming_response(s, resp):
        """处理流式响应"""
        try:
            # 启动进度显示
            s.progress_widget.set_thinking_mode()

            # 累积响应内容
            response_content = ""
            message_started = False

            # 打字机效果相关
            s._stream_typewriter_buffer = ""
            s._stream_typewriter_index = 0
            s._stream_typewriter_timer = None

            # 处理流式数据
            for line in resp.iter_lines():
                if line:
                    line_str = line.decode('utf-8')
                    if line_str.startswith('data: '):
                        data_str = line_str[6:]
                        if data_str == '[DONE]':
                            break
                        elif data_str.startswith('session_id: '):
                            # 处理会话ID
                            session_id = data_str[12:]
                            logger.debug(f"会话ID: {session_id}")
                        elif data_str.startswith('audio_url: '):
                            # 音频URL由apiserver直接处理，PyQt不再处理
                            pass
                        else:
                            # 处理内容数据
                            response_content += data_str
                            s._stream_typewriter_buffer += data_str

                            # 如果是第一条消息，创建新消息并设置当前消息ID
                            if not message_started:
                                # 先清理可能存在的语音消息ID，避免冲突
                                if hasattr(s, '_current_ai_voice_message_id'):
                                    delattr(s, '_current_ai_voice_message_id')

                                message_id = s.add_user_message(AI_NAME, "")
                                s._current_message_id = message_id  # 设置当前消息ID
                                message_started = True
                                # 启动流式打字机效果
                                s._start_stream_typewriter(response_content)
                            else:
                                # 继续打字机效果（如果需要重新启动）
                                if s._stream_typewriter_timer and not s._stream_typewriter_timer.isActive():
                                    s._start_stream_typewriter(response_content)

            # 完成处理 - 停止打字机，显示完整内容
            if hasattr(s, '_stream_typewriter_timer') and s._stream_typewriter_timer:
                s._stream_typewriter_timer.stop()
                s._stream_typewriter_timer.deleteLater()
                # 确保显示完整内容
                s.update_last_message(response_content)

            # 清理临时变量
            if hasattr(s, '_stream_typewriter_buffer'):
                delattr(s, '_stream_typewriter_buffer')
            if hasattr(s, '_stream_typewriter_index'):
                delattr(s, '_stream_typewriter_index')
            if hasattr(s, '_stream_typewriter_timer'):
                s._stream_typewriter_timer = None

            s.progress_widget.stop_loading()

            # 语音输出由apiserver直接处理，PyQt不再处理

        except Exception as e:
            s.add_user_message("系统", f"❌ 流式处理错误: {str(e)}")
            s.progress_widget.stop_loading()

    def _start_stream_typewriter(s, full_text):
        """启动流式聊天的打字机效果"""
        # 确保索引从当前已显示的位置开始
        if not hasattr(s, '_stream_typewriter_index'):
            s._stream_typewriter_index = 0

        if not hasattr(s, '_stream_typewriter_timer') or s._stream_typewriter_timer is None:
            s._stream_typewriter_timer = QTimer()
            s._stream_typewriter_timer.timeout.connect(lambda: s._stream_typewriter_tick(full_text))

        # 设置打字速度（可以比语音的稍快一点）
        if not s._stream_typewriter_timer.isActive():
            s._stream_typewriter_timer.start(100)  # 25ms一个字符，流畅的打字机效果

    def _stream_typewriter_tick(s, full_text):
        """流式聊天的打字机效果tick"""
        if not hasattr(s, '_stream_typewriter_index'):
            s._stream_typewriter_timer.stop()
            return

        # 如果还有字符未显示
        if s._stream_typewriter_index < len(full_text):
            # 每次显示1-3个字符
            next_char = full_text[s._stream_typewriter_index] if s._stream_typewriter_index < len(full_text) else ''
            chars_to_add = 1

            # 如果是英文字符或空格，可以一次显示多个
            if next_char and ord(next_char) < 128:  # ASCII字符
                chars_to_add = min(3, len(full_text) - s._stream_typewriter_index)

            s._stream_typewriter_index += chars_to_add
            displayed_text = full_text[:s._stream_typewriter_index]

            # 更新消息显示
            s.update_last_message(displayed_text)
        else:
            # 所有字符都显示完了，停止定时器
            s._stream_typewriter_timer.stop()

    def _start_non_stream_typewriter(s, full_text):
        """为非流式响应启动打字机效果"""
        # 先清理可能存在的语音消息ID，避免冲突
        if hasattr(s, '_current_ai_voice_message_id'):
            delattr(s, '_current_ai_voice_message_id')

        # 创建空消息
        message_id = s.add_user_message(AI_NAME, "")
        # 同时设置两个message_id变量，确保update_last_message能找到正确的消息
        s._non_stream_message_id = message_id
        s._current_message_id = message_id  # 让update_last_message能正确找到这个消息

        # 初始化打字机变量
        s._non_stream_text = full_text
        s._non_stream_index = 0

        if not hasattr(s, '_non_stream_timer') or s._non_stream_timer is None:
            s._non_stream_timer = QTimer()
            s._non_stream_timer.timeout.connect(s._non_stream_typewriter_tick)

        # 启动定时器（速度可以稍快一些，因为已经有完整文本）
        s._non_stream_timer.start(100)  # 20ms一个字符

    def _non_stream_typewriter_tick(s):
        """非流式响应的打字机效果tick"""
        if not hasattr(s, '_non_stream_text') or not hasattr(s, '_non_stream_index'):
            if hasattr(s, '_non_stream_timer') and s._non_stream_timer:
                s._non_stream_timer.stop()
            return

        # 如果还有字符未显示
        if s._non_stream_index < len(s._non_stream_text):
            # 每次显示1-3个字符
            next_char = s._non_stream_text[s._non_stream_index] if s._non_stream_index < len(s._non_stream_text) else ''
            chars_to_add = 1

            # 如果是英文字符或空格，可以一次显示多个
            if next_char and ord(next_char) < 128:  # ASCII字符
                chars_to_add = min(3, len(s._non_stream_text) - s._non_stream_index)

            s._non_stream_index += chars_to_add
            displayed_text = s._non_stream_text[:s._non_stream_index]

            # 更新消息显示
            s.update_last_message(displayed_text)
        else:
            # 所有字符都显示完了，停止定时器并清理
            s._non_stream_timer.stop()
            s._non_stream_timer.deleteLater()
            s._non_stream_timer = None
            # 清理临时变量
            if hasattr(s, '_non_stream_text'):
                delattr(s, '_non_stream_text')
            if hasattr(s, '_non_stream_index'):
                delattr(s, '_non_stream_index')
            if hasattr(s, '_non_stream_message_id'):
                delattr(s, '_non_stream_message_id')
            # 清理_current_message_id，避免影响后续消息
            if hasattr(s, '_current_message_id'):
                delattr(s, '_current_message_id')

    def setup_streaming_worker(s):
        """配置流式Worker的信号连接"""
        s.worker.progress_updated.connect(s.progress_widget.update_progress)
        s.worker.status_changed.connect(lambda status: s.progress_widget.status_label.setText(status))
        s.worker.error_occurred.connect(s.handle_error)
        
        # 流式专用信号
        s.worker.stream_chunk.connect(s.append_response_chunk)
        s.worker.stream_complete.connect(s.finalize_streaming_response)
        s.worker.finished.connect(s.on_response_finished)
        
        # 注意：工具调用现在通过API通讯处理，不再使用UI信号
        # 工具调用流程：UI -> API Server -> MCP Server -> 工具执行 -> 回调
    
    def setup_batch_worker(s):
        """配置批量Worker的信号连接"""
        s.worker.progress_updated.connect(s.progress_widget.update_progress)
        s.worker.status_changed.connect(lambda status: s.progress_widget.status_label.setText(status))
        s.worker.error_occurred.connect(s.handle_error)
        s.worker.finished.connect(s.on_batch_response_finished)
    
    def append_response_chunk(s, chunk):
        """追加响应片段（流式模式）- 实时显示到普通消息框"""
        # 检查是否为工具调用相关标记
        if any(marker in chunk for marker in ["[TOOL_CALL]", "[TOOL_START]", "[TOOL_RESULT]", "[TOOL_ERROR]"]):
            # 这是工具调用相关标记，不累积到普通消息中
            return

        # 检查是否在工具调用过程中，如果是则创建新的消息框
        if hasattr(s, '_in_tool_call_mode') and s._in_tool_call_mode:
            # 工具调用模式结束，创建新的消息框
            s._in_tool_call_mode = False
            s._current_message_id = None

        # 实时更新显示 - 立即显示到UI
        if not hasattr(s, '_current_message_id') or s._current_message_id is None:
            # 第一次收到chunk时，创建新消息
            s._current_message_id = s.add_user_message(AI_NAME, chunk)
            s.current_response = chunk
        else:
            # 后续chunk，追加到当前消息
            s.current_response += chunk
            # 限制更新频率（节流）
            if not hasattr(s, '_last_update_time'):
                s._last_update_time = 0

            import time
            current_time = time.time()
            # 每50毫秒更新一次UI，减少闪动
            if current_time - s._last_update_time >= 0.05:
                s.update_last_message(s.current_response)
                s._last_update_time = current_time
    
    def finalize_streaming_response(s):
        """完成流式响应 - 立即处理"""
        if s.current_response:
            # 对累积的完整响应进行消息提取（多步自动\n分隔）
            from ui.response_utils import extract_message
            final_message = extract_message(s.current_response)
            
            # 更新最终消息（确保最后的内容完整显示）
            if hasattr(s, '_current_message_id') and s._current_message_id:
                s.update_last_message(final_message)
                # 不要在这里删除_current_message_id，让on_response_finished处理
                # delattr(s, '_current_message_id')
            else:
                s.add_user_message(AI_NAME, final_message)
        
        # 重置current_response和更新时间
        s.current_response = ""
        if hasattr(s, '_last_update_time'):
            delattr(s, '_last_update_time')

        # 立即停止加载状态
        s.progress_widget.stop_loading()
    
    def on_response_finished(s, response):
        """处理完成的响应（流式模式后备）"""
        # 检查是否是取消操作的响应
        if response == "操作已取消":
            return  # 不显示，因为已经在cancel_current_task中显示了
        
        # 如果已经通过流式处理了，就不要重复创建消息
        if hasattr(s, '_current_message_id'):
            # 流式响应已经处理过了，删除标记
            delattr(s, '_current_message_id')
            s.progress_widget.stop_loading()
            return

        if not s.current_response:  # 如果流式没有收到数据，使用最终结果
            from ui.response_utils import extract_message
            final_message = extract_message(response)
            s.add_user_message(AI_NAME, final_message)
        s.progress_widget.stop_loading()

    def toggle_self_game(s):
        """切换博弈论流程开关"""
        s.self_game_enabled = not s.self_game_enabled
        status = '启用' if s.self_game_enabled else '禁用'
        s.add_user_message("系统", f"● 博弈论流程已{status}")
    
    def on_batch_response_finished(s, response):
        """处理完成的响应（批量模式）"""
        # 检查是否是取消操作的响应
        if response == "操作已取消":
            return  # 不显示，因为已经在cancel_current_task中显示了
        from ui.response_utils import extract_message
        final_message = extract_message(response)
        s.add_user_message(AI_NAME, final_message)
        s.progress_widget.stop_loading()
    
    def handle_error(s, error_msg):
        """处理错误"""
        s.add_user_message("系统", f"❌ {error_msg}")
        s.progress_widget.stop_loading()
    
    def handle_tool_call(s, notification):
        """处理工具调用通知 - 创建工具调用专用渲染框"""
        # 标记进入工具调用模式
        s._in_tool_call_mode = True

        # 创建专门的工具调用内容对话框（没有用户名）
        tool_call_dialog = MessageRenderer.create_tool_call_content_message(notification, s.chat_content)

        # 设置嵌套对话框内容
        nested_title = "工具调用详情"
        nested_content = f"""
工具名称: {notification}
状态: 正在执行...
时间: {time.strftime('%H:%M:%S')}
        """.strip()
        tool_call_dialog.set_nested_content(nested_title, nested_content)

        # 生成消息ID
        if not hasattr(s, '_message_counter'):
            s._message_counter = 0
        s._message_counter += 1
        message_id = f"tool_call_{s._message_counter}"

        # 初始化消息存储
        if not hasattr(s, '_messages'):
            s._messages = {}

        # 存储工具调用消息信息
        s._messages[message_id] = {
            'name': '工具调用',
            'content': notification,
            'full_content': notification,
            'dialog_widget': tool_call_dialog,
            'is_tool_call': True  # 标记为工具调用消息
        }

        # 先移除stretch
        for i in reversed(range(s.chat_layout.count())):
            item = s.chat_layout.itemAt(i)
            if item and not item.widget():  # 找到stretch
                s.chat_layout.removeItem(item)
                break

        # 添加工具调用对话框
        s.chat_layout.addWidget(tool_call_dialog)

        # 重新添加stretch到最后
        s.chat_layout.addStretch()

        # 滚动到底部
        s.scroll_to_bottom()

        # 在状态栏也显示工具调用状态
        s.progress_widget.status_label.setText(f"🔧 {notification}")
        logger.debug(f"工具调用: {notification}")
    
    def handle_tool_result(s, result):
        """处理工具执行结果 - 更新工具调用专用渲染框"""
        # 查找最近的工具调用对话框并更新
        if hasattr(s, '_messages'):
            for message_id, message_info in reversed(list(s._messages.items())):
                if message_id.startswith('tool_call_'):
                    dialog_widget = message_info.get('dialog_widget')
                    if dialog_widget:
                        # 更新工具调用对话框显示结果
                        MessageRenderer.update_message_content(dialog_widget, f"✅ {result}")
                        
                        # 更新嵌套对话框内容
                        if hasattr(dialog_widget, 'set_nested_content'):
                            nested_title = "工具调用结果"
                            nested_content = f"""
工具名称: {message_info.get('content', '未知工具')}
状态: 执行完成 ✅
时间: {time.strftime('%H:%M:%S')}
结果: {result[:200]}{'...' if len(result) > 200 else ''}
                            """.strip()
                            dialog_widget.set_nested_content(nested_title, nested_content)
                        break
        
        # 工具调用完成，退出工具调用模式，准备接收后续内容
        s._in_tool_call_mode = False
        
        # 在状态栏也显示工具执行结果
        s.progress_widget.status_label.setText(f"✅ {result[:50]}...")
        logger.debug(f"工具结果: {result}")
    
    def cancel_current_task(s):
        """取消当前任务 - 优化版本，减少卡顿"""
        # 停止所有打字机效果
        if hasattr(s, '_non_stream_timer') and s._non_stream_timer and s._non_stream_timer.isActive():
            s._non_stream_timer.stop()
            s._non_stream_timer.deleteLater()
            s._non_stream_timer = None
            # 清理非流式打字机变量
            if hasattr(s, '_non_stream_text'):
                delattr(s, '_non_stream_text')
            if hasattr(s, '_non_stream_index'):
                delattr(s, '_non_stream_index')
            if hasattr(s, '_non_stream_message_id'):
                delattr(s, '_non_stream_message_id')
            # 清理当前消息ID
            if hasattr(s, '_current_message_id'):
                delattr(s, '_current_message_id')

        if hasattr(s, '_stream_typewriter_timer') and s._stream_typewriter_timer and s._stream_typewriter_timer.isActive():
            s._stream_typewriter_timer.stop()
            s._stream_typewriter_timer.deleteLater()
            s._stream_typewriter_timer = None

        if hasattr(s, '_typewriter_timer') and s._typewriter_timer and s._typewriter_timer.isActive():
            s._typewriter_timer.stop()
            s._typewriter_timer.deleteLater()
            s._typewriter_timer = None

        # 处理worker
        if s.worker and s.worker.isRunning():
            # 立即设置取消标志
            s.worker.cancel()
            
            # 非阻塞方式处理线程清理
            s.progress_widget.stop_loading()
            s.add_user_message("系统", "🚫 操作已取消")
            
            # 清空当前响应缓冲，避免部分响应显示
            s.current_response = ""
            
            # 使用QTimer延迟处理线程清理，避免UI卡顿
            def cleanup_worker():
                if s.worker:
                    s.worker.quit()
                    if not s.worker.wait(500):  # 只等待500ms
                        s.worker.terminate()
                        s.worker.wait(200)  # 再等待200ms
                    s.worker.deleteLater()
                    s.worker = None
            
            # 50ms后异步清理，避免阻塞UI
            QTimer.singleShot(50, cleanup_worker)
        else:
            s.progress_widget.stop_loading()

    def toggle_full_img(s,e):
        if getattr(s, '_animating', False):  # 动画期间禁止重复点击
            return
        s._animating = True  # 设置动画标志位
        s.full_img^=1  # 立绘展开标志切换
        target_width = s.expanded_width if s.full_img else s.collapsed_width  # 目标宽度：展开或收缩
        
        # --- 立即切换界面状态 ---
        if s.full_img:  # 展开状态 - 进入设置页面
            s.input_wrap.hide()  # 隐藏输入框
            s.chat_stack.setCurrentIndex(1)  # 切换到设置页
            s.side.setCursor(Qt.PointingHandCursor)  # 保持点击指针，可点击收缩
            s.titlebar.text = "SETTING PAGE"
            s.titlebar.update()
            s.side.setStyleSheet(f"""
                QWidget {{
                    background: rgba(17,17,17,{int(BG_ALPHA*255*0.9)});
                    border-radius: 15px;
                    border: 1px solid rgba(255, 255, 255, 80);
                }}
            """)
        else:  # 收缩状态 - 主界面聊天模式
            s.input_wrap.show()  # 显示输入框
            s.chat_stack.setCurrentIndex(0)  # 切换到聊天页
            s.input.setFocus()  # 恢复输入焦点
            s.side.setCursor(Qt.PointingHandCursor)  # 保持点击指针
            s.titlebar.text = "NAGA AGENT"
            s.titlebar.update()
            s.side.setStyleSheet(f"""
                QWidget {{
                    background: rgba(17,17,17,{int(BG_ALPHA*255*0.7)});
                    border-radius: 15px;
                    border: 1px solid rgba(255, 255, 255, 40);
                }}
            """)
        # --- 立即切换界面状态 END ---
        
        # 创建优化后的动画组
        group = QParallelAnimationGroup(s)
        
        # 侧栏宽度动画 - 合并为单个动画
        side_anim = QPropertyAnimation(s.side, b"minimumWidth", s)
        side_anim.setDuration(ANIMATION_DURATION)
        side_anim.setStartValue(s.side.width())
        side_anim.setEndValue(target_width)
        side_anim.setEasingCurve(QEasingCurve.OutCubic)  # 使用更流畅的缓动
        group.addAnimation(side_anim)
        
        side_anim2 = QPropertyAnimation(s.side, b"maximumWidth", s)
        side_anim2.setDuration(ANIMATION_DURATION)
        side_anim2.setStartValue(s.side.width())
        side_anim2.setEndValue(target_width)
        side_anim2.setEasingCurve(QEasingCurve.OutCubic)
        group.addAnimation(side_anim2)
        
        # 输入框动画 - 进入设置时隐藏，退出时显示
        if s.full_img:
            input_hide_anim = QPropertyAnimation(s.input_wrap, b"maximumHeight", s)
            input_hide_anim.setDuration(ANIMATION_DURATION // 2)
            input_hide_anim.setStartValue(s.input_wrap.height())
            input_hide_anim.setEndValue(0)
            input_hide_anim.setEasingCurve(QEasingCurve.OutQuad)
            group.addAnimation(input_hide_anim)
        else:
            input_show_anim = QPropertyAnimation(s.input_wrap, b"maximumHeight", s)
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
            s._animating = False  # 动画结束标志
            # Live2D侧栏会自动处理最终调整
            pass
        
        # 连接信号
        side_anim.valueChanged.connect(on_side_width_changed)
        group.finished.connect(on_animation_finished)
        group.start()
        

    # 添加整个窗口的拖动支持
    def mousePressEvent(s, event):
        if event.button() == Qt.LeftButton:
            s._offset = event.globalPos() - s.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(s, event):
        if s._offset and event.buttons() & Qt.LeftButton:
            s.move(event.globalPos() - s._offset)
            event.accept()

    def mouseReleaseEvent(s, event):
        s._offset = None
        event.accept()

    def paintEvent(s, event):
        """绘制窗口背景"""
        painter = QPainter(s)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 绘制主窗口背景 - 使用可调节的透明度
        painter.setBrush(QBrush(QColor(25, 25, 25, WINDOW_BG_ALPHA)))
        painter.setPen(QColor(255, 255, 255, 30))
        painter.drawRoundedRect(s.rect(), 20, 20)

    def on_settings_changed(s, setting_key, value):
        """处理设置变化"""
        logger.debug(f"设置变化: {setting_key} = {value}")
        
        # 透明度设置将在保存时统一应用，避免动画卡顿
        if setting_key in ("all", "ui.bg_alpha", "ui.window_bg_alpha"):  # UI透明度变化 #
            # 保存时应用透明度设置
            s.apply_opacity_from_config()
            return
        if setting_key in ("system.stream_mode", "STREAM_MODE"):
            s.streaming_mode = value if setting_key == "system.stream_mode" else value  # 兼容新旧键名 #
            s.add_user_message("系统", f"● 流式模式已{'启用' if s.streaming_mode else '禁用'}")
        elif setting_key in ("system.debug", "DEBUG"):
            s.add_user_message("系统", f"● 调试模式已{'启用' if value else '禁用'}")
        
        # 发送设置变化信号给其他组件
        # 这里可以根据需要添加更多处理逻辑

    def set_window_background_alpha(s, alpha):
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
        s.setStyleSheet(f"""
            ChatWindow {{
                background: rgba(25, 25, 25, {WINDOW_BG_ALPHA});
                border-radius: 20px;
                border: 1px solid rgba(255, 255, 255, 30);
            }}
        """)
    
        # 触发重绘
        s.update()

        logger.info(f"✅ 窗口背景透明度已设置为: {WINDOW_BG_ALPHA}/255 ({WINDOW_BG_ALPHA/255*100:.1f}%不透明度)")

    def apply_opacity_from_config(s):
        """从配置中应用UI透明度(聊天区/输入框/侧栏/窗口)"""
        # 更新全局变量，保持其它逻辑一致 #
        global BG_ALPHA, WINDOW_BG_ALPHA
        # 直接读取配置值，避免函数调用开销
        BG_ALPHA = config.ui.bg_alpha
        WINDOW_BG_ALPHA = config.ui.window_bg_alpha

        # 计算alpha #
        alpha_px = int(BG_ALPHA * 255)

        # 更新聊天区域背景 - 现在使用透明背景，对话框有自己的背景
        s.chat_content.setStyleSheet(f"""
            QWidget {{
                background: transparent;
                border: none;
            }}
        """)

        # 更新输入框背景 #
        fontfam, fontsize = 'Lucida Console', 16
        s.input.setStyleSheet(f"""
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
        if hasattr(s, 'side') and isinstance(s.side, QWidget):
            try:
                s.side.set_background_alpha(alpha_px)
            except Exception:
                pass

        # 更新主窗口背景 #
        s.set_window_background_alpha(WINDOW_BG_ALPHA)
    

    def showEvent(s, event):
        """窗口显示事件"""
        super().showEvent(event)
        
        # 其他初始化代码...
        s.setFocus()
        s.input.setFocus()
        # 图片初始化现在由Live2DSideWidget处理
        s._img_inited = True

    def upload_document(s):
        """上传文档功能"""
        try:
            # 打开文件选择对话框
            file_path, _ = QFileDialog.getOpenFileName(
                s,
                "选择要上传的文档",
                "",
                "支持的文档格式 (*.docx *.txt *.md);;Word文档 (*.docx);;文本文件 (*.txt);;Markdown文件 (*.md);;所有文件 (*)"
            )
            
            if not file_path:
                return  # 用户取消选择
            
            # 检查文件格式
            file_ext = Path(file_path).suffix.lower()
            supported_formats = ['.docx', '.txt', '.md']
            
            if file_ext not in supported_formats:
                QMessageBox.warning(s, "格式不支持", 
                                   f"不支持的文件格式: {file_ext}\n\n支持的格式: {', '.join(supported_formats)}")
                return
            
            # 检查文件大小 (限制为10MB)
            file_size = os.path.getsize(file_path)
            if file_size > 10 * 1024 * 1024:  # 10MB
                QMessageBox.warning(s, "文件过大", "文件大小不能超过10MB")
                return
            
            # 上传文件到API服务器
            s.upload_file_to_server(file_path)
            
        except Exception as e:
            QMessageBox.critical(s, "上传错误", f"文档上传失败:\n{str(e)}")
    
    def upload_file_to_server(s, file_path):
        """将文件上传到API服务器"""
        try:
            # 显示上传进度
            s.add_user_message("系统", f"📤 正在上传文档: {Path(file_path).name}")
            s.progress_widget.set_thinking_mode()
            s.progress_widget.status_label.setText("上传文档中...")
            
            # 准备上传数据
            api_url = "http://localhost:8000/upload/document"
            
            with open(file_path, 'rb') as f:
                files = {'file': (Path(file_path).name, f, 'application/octet-stream')}
                data = {'description': f'通过NAGA聊天界面上传的文档'}
                
                # 发送上传请求
                response = requests.post(api_url, files=files, data=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                s.progress_widget.stop_loading()
                s.add_user_message("系统", f"✅ 文档上传成功: {result['filename']}")
                
                # 询问用户想要进行什么操作
                s.show_document_options(result['file_path'], result['filename'])
            else:
                s.progress_widget.stop_loading()
                s.add_user_message("系统", f"❌ 上传失败: {response.text}")
                
        except requests.exceptions.ConnectionError:
            s.progress_widget.stop_loading()
            s.add_user_message("系统", "❌ 无法连接到API服务器，请确保服务器正在运行")
        except Exception as e:
            s.progress_widget.stop_loading()
            s.add_user_message("系统", f"❌ 上传失败: {str(e)}")
    
    def show_document_options(s, file_path, filename):
        """显示文档处理选项"""
        from nagaagent_core.vendors.PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QFrame, QPushButton  # 统一入口 #
        from nagaagent_core.vendors.PyQt5.QtCore import Qt  # 统一入口 #
        from nagaagent_core.vendors.PyQt5.QtGui import QFont  # 统一入口 #
        
        dialog = QDialog(s)
        dialog.setWindowTitle("文档处理选项")
        dialog.setFixedSize(650, 480)
        # 隐藏标题栏的图标按钮
        dialog.setWindowFlags(Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        dialog.setStyleSheet("""
            QDialog {
                background-color: white;
                border: 2px solid #ddd;
                border-radius: 10px;
            }
        """)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(20)
        
        # 标题
        title_label = QLabel("文档上传成功")
        title_font = QFont("Microsoft YaHei", 16, QFont.Bold)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #2c3e50; margin-bottom: 25px; padding: 15px; min-height: 40px;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # 文件信息
        info_label = QLabel(f"文件名: {filename}")
        info_label.setStyleSheet("color: #34495e; font-size: 14px; padding: 10px;")
        layout.addWidget(info_label)
        
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #bdc3c7;")
        layout.addWidget(line)
        
        # 操作按钮
        actions = [
            ("📖 读取内容", "read", "读取文档的完整内容"),
            ("🔍 分析文档", "analyze", "分析文档结构和内容"),
            ("📝 生成摘要", "summarize", "生成文档的简洁摘要")
        ]
        
        for btn_text, action, description in actions:
            btn = ButtonFactory.create_document_action_button(btn_text)
            
            # 添加描述标签
            desc_label = QLabel(description)
            desc_label.setStyleSheet("color: #7f8c8d; font-size: 12px; margin-bottom: 10px;")
            layout.addWidget(desc_label)
            layout.addWidget(btn)
            
            # 连接按钮事件
            btn.clicked.connect(lambda checked, f=file_path, a=action, d=dialog: s.process_document(f, a, d))
        
        # 取消按钮
        cancel_btn = ButtonFactory.create_cancel_button()
        cancel_btn.clicked.connect(dialog.close)
        layout.addWidget(cancel_btn)
        
        dialog.exec_()
    
    def process_document(s, file_path, action, dialog=None):
        """处理文档"""
        if dialog:
            dialog.close()
        
        try:
            s.add_user_message("系统", f"🔄 正在处理文档: {Path(file_path).name}")
            s.progress_widget.set_thinking_mode()
            s.progress_widget.status_label.setText("处理文档中...")
            
            # 调用API处理文档
            api_url = "http://localhost:8000/document/process"
            data = {
                "file_path": file_path,
                "action": action
            }
            
            response = requests.post(api_url, json=data, timeout=60)
            
            if response.status_code == 200:
                result = response.json()
                s.progress_widget.stop_loading()
                
                if action == "read":
                    s.add_user_message(AI_NAME, f"📖 文档内容:\n\n{result['content']}")
                elif action == "analyze":
                    s.add_user_message(AI_NAME, f"🔍 文档分析:\n\n{result['analysis']}")
                elif action == "summarize":
                    s.add_user_message(AI_NAME, f"📝 文档摘要:\n\n{result['summary']}")
            else:
                s.progress_widget.stop_loading()
                s.add_user_message("系统", f"❌ 文档处理失败: {response.text}")
                
        except requests.exceptions.ConnectionError:
            s.progress_widget.stop_loading()
            s.add_user_message("系统", "❌ 无法连接到API服务器，请确保服务器正在运行")
        except Exception as e:
            s.progress_widget.stop_loading()
            s.add_user_message("系统", f"❌ 文档处理失败: {str(e)}")
    
    def open_mind_map(s):
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
                s.add_user_message("系统", "🔄 正在生成心智云图...")
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
                        s.add_user_message("系统", "🧠 心智云图已生成并打开")
                    else:
                        s.add_user_message("系统", "❌ 心智云图生成失败")
                except Exception as e:
                    s.add_user_message("系统", f"❌ 生成心智云图失败: {str(e)}")
            else:
                # 没有五元组数据，提示用户
                s.add_user_message("系统", "❌ 未找到五元组数据，请先进行对话以生成知识图谱")
        except Exception as e:
            s.add_user_message("系统", f"❌ 打开心智云图失败: {str(e)}")
    
    def initialize_live2d(s):
        """初始化Live2D"""
        if s.live2d_enabled and s.live2d_model_path:
            if os.path.exists(s.live2d_model_path):
                s.side.set_live2d_model(s.live2d_model_path) # 调用已有输出逻辑
            else:
                logger.warning(f"⚠️ Live2D模型文件不存在: {s.live2d_model_path}")
        else:
            logger.info("📝 Live2D功能未启用或未配置模型路径")
    
    def on_live2d_model_loaded(s, success):
        """Live2D模型加载状态回调"""
        if success:
            logger.info("✅ Live2D模型已成功加载")
        else:
            logger.info("🔄 已回退到图片模式")
    
    def on_live2d_error(s, error_msg):
        """Live2D错误回调"""
        s.add_user_message("系统", f"❌ Live2D错误: {error_msg}")
    
    def set_live2d_model(s, model_path):
        """设置Live2D模型"""
        if not os.path.exists(model_path):
            s.add_user_message("系统", f"❌ Live2D模型文件不存在: {model_path}")
            return False
        
        s.live2d_model_path = model_path
        s.live2d_enabled = True
        
        s.add_user_message("系统", "🔄 正在切换Live2D模型...")
        success = s.side.set_live2d_model(model_path)
        
        if success:
            s.add_user_message("系统", "✅ Live2D模型切换成功")
        else:
            s.add_user_message("系统", "⚠️ Live2D模型切换失败，已回退到图片模式")
        
        return success
    
    def set_fallback_image(s, image_path):
        """设置回退图片"""
        if not os.path.exists(image_path):
            s.add_user_message("系统", f"❌ 图片文件不存在: {image_path}")
            return False
        
        s.side.set_fallback_image(image_path)
        s.add_user_message("系统", f"✅ 回退图片已设置: {os.path.basename(image_path)}")
        return True
    
    def get_display_mode(s):
        """获取当前显示模式"""
        return s.side.get_display_mode()
    
    def is_live2d_available(s):
        """检查Live2D是否可用"""
        return s.side.is_live2d_available()

    def toggle_voice_realtime(s):
        """切换实时语音对话状态"""
        # 添加防抖动机制
        import time
        current_time = time.time()
        if hasattr(s, '_last_voice_toggle_time'):
            if current_time - s._last_voice_toggle_time < 1.0:  # 1秒内防止重复点击
                return
        s._last_voice_toggle_time = current_time

        # 如果是超时断开状态，视为未激活
        if getattr(s, '_is_timeout_disconnect', False):
            s.voice_realtime_active = False

        if not s.voice_realtime_active:
            # 启动语音服务
            s.start_voice_realtime()
        else:
            # 语音输入功能由统一语音管理器处理
            from system.config import config
            if config.voice_realtime.provider == "local" and hasattr(s.voice_integration, 'voice_integration'):
                # 本地模式：切换录音
                if hasattr(s.voice_integration.voice_integration, 'toggle_recording'):
                    s.voice_integration.voice_integration.toggle_recording()
                    return

            # 其他模式：停止服务
            s.stop_voice_realtime()

    def start_voice_realtime(s):
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
                s.add_user_message("系统", "❌ 请先在设置中配置语音服务API密钥")
                return

            # 使用统一语音管理器启动
            from voice.input.unified_voice_manager import VoiceMode

            # 确定要使用的模式
            mode = getattr(s, 'default_voice_mode', None)

            success = s.voice_integration.start_voice(mode=mode)

            if not success:
                s.add_user_message("系统", "❌ 语音服务启动失败，请检查配置和服务状态")
            else:
                # 设置激活标志
                s.voice_realtime_active = True

        except Exception as e:
            s.add_user_message("系统", f"❌ 启动语音服务失败: {str(e)}")

    def stop_voice_realtime(s):
        """停止实时语音对话"""
        try:
            # 检查是否因为超时断开而自动调用的停止
            if getattr(s, '_is_timeout_disconnect', False):
                # 超时断开的情况下，清理标记后直接返回
                # 因为状态已经在on_voice_status中处理过了
                s._is_timeout_disconnect = False
                return True

            # 使用线程安全的语音集成管理器停止语音
            success = s.voice_integration.stop_voice()

            # 无论成功与否，都设置标志为False
            s.voice_realtime_active = False

            if not success:
                s.add_user_message("系统", "⚠️ 语音服务未在运行")

        except Exception as e:
            s.voice_realtime_active = False  # 确保异常时也设置为False
            s.add_user_message("系统", f"❌ 停止语音服务失败: {str(e)}")

    def on_voice_user_text(s, text):
        """处理用户语音识别结果"""
        # 清理之前可能存在的所有消息ID，确保新的语音会创建新消息
        if hasattr(s, '_current_ai_voice_message_id'):
            delattr(s, '_current_ai_voice_message_id')
        if hasattr(s, '_current_message_id'):
            delattr(s, '_current_message_id')

        # 始终显示在聊天界面（移除条件判断）
        s.add_user_message(config.ui.user_name, f"🎤 {text}")

        # 保存用户语音文本用于知识提取
        s._last_user_voice_text = text

        # 历史记录现在由API Server管理，无需手动添加
        # API Server会在处理消息时自动管理对话历史
        logger.debug(f"[语音] 用户输入: {text}")

    def on_voice_ai_text(s, text):
        """处理AI语音响应文本（流式）"""
        # 初始化响应变量
        if not hasattr(s, '_current_ai_voice_response'):
            s._current_ai_voice_response = ""

        # 初始化打字机效果变量（每次都检查）
        if not hasattr(s, '_typewriter_buffer'):
            s._typewriter_buffer = ""  # 打字机效果缓冲区
        if not hasattr(s, '_typewriter_index'):
            s._typewriter_index = 0     # 当前显示的字符索引
        if not hasattr(s, '_typewriter_timer'):
            s._typewriter_timer = None   # 打字机效果定时器

        # 累积完整文本
        s._current_ai_voice_response += text
        s._typewriter_buffer += text

        # 如果没有消息ID，创建新消息
        if not hasattr(s, '_current_ai_voice_message_id') or s._current_ai_voice_message_id is None:
            # 先清理可能存在的文本消息ID，避免冲突
            if hasattr(s, '_current_message_id'):
                delattr(s, '_current_message_id')

            s._current_ai_voice_message_id = s.add_user_message(AI_NAME, "🔊 ")

            # 为了兼容update_last_message，暂时也设置_current_message_id
            # 但要注意这只是临时的，voice完成后会清理
            s._current_message_id = s._current_ai_voice_message_id
            # 启动打字机效果
            s._start_typewriter_effect()

        # 如果定时器没在运行，重新启动（可能新文本到达）
        if s._typewriter_timer and not s._typewriter_timer.isActive():
            s._start_typewriter_effect()

    def _start_typewriter_effect(s):
        """启动打字机效果"""
        if not hasattr(s, '_typewriter_timer') or s._typewriter_timer is None:
            s._typewriter_timer = QTimer()
            s._typewriter_timer.timeout.connect(s._typewriter_tick)

        # 设置打字速度（每次显示几个字符的间隔，毫秒）
        s._typewriter_timer.start(100)  # 30ms一个字符，可调整速度

    def _typewriter_tick(s):
        """打字机效果的每一个tick"""
        # 检查必要的属性是否存在
        if not hasattr(s, '_typewriter_buffer') or not hasattr(s, '_current_ai_voice_response') or not hasattr(s, '_typewriter_index'):
            if hasattr(s, '_typewriter_timer') and s._typewriter_timer:
                s._typewriter_timer.stop()
            return

        # 获取已经显示的文本
        displayed_text = s._current_ai_voice_response[:s._typewriter_index]

        # 如果还有字符未显示
        if s._typewriter_index < len(s._current_ai_voice_response):
            # 每次显示1-2个字符（中文算1个，英文可以多个）
            next_char = s._current_ai_voice_response[s._typewriter_index]
            chars_to_add = 1

            # 如果是英文字符，可以一次显示多个
            if ord(next_char) < 128:  # ASCII字符
                chars_to_add = min(2, len(s._current_ai_voice_response) - s._typewriter_index)

            s._typewriter_index += chars_to_add
            displayed_text = s._current_ai_voice_response[:s._typewriter_index]

            # 更新消息显示
            s.update_last_message(f"🔊 {displayed_text}")
        else:
            # 所有字符都显示完了，停止定时器
            s._typewriter_timer.stop()

    def on_voice_response_complete(s):
        """处理AI响应完成"""
        # 停止打字机效果定时器
        if hasattr(s, '_typewriter_timer') and s._typewriter_timer:
            s._typewriter_timer.stop()
            s._typewriter_timer.deleteLater()
            # 确保显示所有剩余文本
            if hasattr(s, '_current_ai_voice_response') and s._current_ai_voice_response:
                s.update_last_message(f"🔊 {s._current_ai_voice_response}")

        # 历史记录现在由API Server管理，无需手动添加
        if hasattr(s, '_current_ai_voice_response') and s._current_ai_voice_response:
            try:
                logger.debug(f"[语音] AI响应完成: {s._current_ai_voice_response[:50]}...")

                # 触发知识图谱提取（如果启用）
                if config.grag.enabled and config.grag.auto_extract:
                    # 构造最近的对话用于提取
                    recent_messages = []

                    # 从UI消息中获取最近的对话（如果有保存）
                    if hasattr(s, '_last_user_voice_text'):
                        recent_messages.append({
                            'role': 'user',
                            'content': s._last_user_voice_text
                        })

                    if s._current_ai_voice_response:
                        recent_messages.append({
                            'role': 'assistant',
                            'content': s._current_ai_voice_response
                        })

                    if recent_messages:
                        # 异步触发知识提取
                        import asyncio
                        import threading

                        def extract_knowledge_async():
                            try:
                                from summer_memory.memory_manager import memory_manager
                                if memory_manager and hasattr(memory_manager, 'extract_from_conversation'):
                                    # 创建新的事件循环（因为在线程中）
                                    loop = asyncio.new_event_loop()
                                    asyncio.set_event_loop(loop)

                                    # 执行异步提取
                                    loop.run_until_complete(
                                        memory_manager.extract_from_conversation(recent_messages)
                                    )
                                    loop.close()

                                    logger.debug(f"[语音] 知识图谱提取完成")
                            except Exception as e:
                                logger.error(f"[语音] 知识提取失败: {e}")

                        # 在后台线程中执行提取
                        extract_thread = threading.Thread(target=extract_knowledge_async, daemon=True)
                        extract_thread.start()
                        logger.debug(f"[语音] 已触发知识图谱提取")

            except Exception as e:
                logger.error(f"[语音] 处理AI响应完成时出错: {e}")
                import traceback
                traceback.print_exc()

            # 清理临时变量
            s._current_ai_voice_response = ""
            if hasattr(s, '_current_ai_voice_message_id'):
                delattr(s, '_current_ai_voice_message_id')
            # 清理当前消息ID，避免影响后续消息
            if hasattr(s, '_current_message_id'):
                delattr(s, '_current_message_id')
            if hasattr(s, '_last_user_voice_text'):
                delattr(s, '_last_user_voice_text')
            if hasattr(s, '_typewriter_buffer'):
                delattr(s, '_typewriter_buffer')
            if hasattr(s, '_typewriter_index'):
                delattr(s, '_typewriter_index')
            if hasattr(s, '_typewriter_timer'):
                s._typewriter_timer = None

    def on_voice_status(s, status):
        """处理语音状态变化"""
        status_map = {
            'connected': ('已连接', 'listening'),
            'listening': ('监听中', 'listening'),
            'processing': ('处理中', 'recording'),
            'ai_speaking': ('AI说话中', 'ai_speaking'),
            'cooldown': ('冷却期', 'listening'),
            'disconnected': ('已断开', 'idle'),
            'error': ('错误', 'idle')
        }

        if status in status_map:
            msg, button_state = status_map[status]
            s.voice_realtime_state = button_state
            s.update_voice_button_state(button_state)

            # 如果断开连接或出错，确保设置voice_realtime_active为False
            if status in ['disconnected', 'error']:
                # 检查是否是主动停止（用户点击按钮）
                if getattr(s, '_is_manual_stop', False):
                    # 主动停止，不设置超时标记，不显示超时消息
                    s.voice_realtime_active = False
                    logger.info("[语音状态] 用户主动停止，不设置超时标记")
                else:
                    # 检查是否已经处理过超时断开（避免重复）
                    was_active = s.voice_realtime_active
                    s.voice_realtime_active = False

                    # 如果是断开连接且之前是激活状态，且没有超时标记，显示超时提示
                    if status == 'disconnected' and was_active and not getattr(s, '_is_timeout_disconnect', False):
                        s._is_timeout_disconnect = True  # 设置超时断开标记
                        s.add_user_message("系统", "⏱️ 长时间未进行语音交流，语音连接已自动断开")

            # 在状态栏显示状态（可选）
            if config.voice_realtime.debug:
                logger.debug(f"[语音状态] {msg}")

    def on_voice_error(s, error):
        """处理语音错误"""
        # 特殊处理超时断开消息
        if "长时间未进行语音交流" in str(error):
            # 如果已经设置了超时标记，说明已经显示过了，不重复显示
            if not getattr(s, '_is_timeout_disconnect', False):
                s._is_timeout_disconnect = True  # 设置超时断开标记
                s.add_user_message("系统", str(error))
            # 超时断开不需要调用stop_voice_realtime，因为已经自动断开了
        elif "语音连接已自动断开" in str(error):
            # 同样避免重复
            if not getattr(s, '_is_timeout_disconnect', False):
                s._is_timeout_disconnect = True  # 设置超时断开标记
                s.add_user_message("系统", str(error))
            # 同上，已经自动断开了
        else:
            s.add_user_message("系统", f"❌ 语音错误: {error}")
            # 其他错误时停止语音服务
            s.stop_voice_realtime()

    def update_voice_button_state(s, state):
        """更新语音按钮状态"""
        if state == "idle":
            s.voice_realtime_btn.setText("🎤")
            s.voice_realtime_btn.setProperty("recording", False)
            s.voice_realtime_btn.setProperty("ai_speaking", False)
            s.voice_realtime_btn.setToolTip("点击启动实时语音对话")
        elif state == "listening":
            s.voice_realtime_btn.setText("👂")
            s.voice_realtime_btn.setProperty("recording", False)
            s.voice_realtime_btn.setProperty("ai_speaking", False)
            s.voice_realtime_btn.setToolTip("监听中...点击停止")
        elif state == "recording":
            s.voice_realtime_btn.setText("🔴")
            s.voice_realtime_btn.setProperty("recording", True)
            s.voice_realtime_btn.setProperty("ai_speaking", False)
            s.voice_realtime_btn.setToolTip("正在录音...点击打断")
        elif state == "ai_speaking":
            s.voice_realtime_btn.setText("🔊")
            s.voice_realtime_btn.setProperty("recording", False)
            s.voice_realtime_btn.setProperty("ai_speaking", True)
            s.voice_realtime_btn.setToolTip("AI说话中...点击打断")

        # 刷新样式
        s.voice_realtime_btn.setStyle(s.voice_realtime_btn.style())
        # 强制重绘按钮
        s.voice_realtime_btn.update()
        # 处理事件队列
        from nagaagent_core.vendors.PyQt5.QtWidgets import QApplication
        QApplication.processEvents()

    def update_last_message(s, new_text):
        """更新最后一条消息的内容"""
        # 处理消息格式化
        from ui.response_utils import extract_message
        msg = extract_message(new_text)
        content_html = str(msg).replace('\\n', '\n').replace('\n', '<br>')

        # 优先使用当前消息ID（流式更新时设置的）
        message_id = None
        message_source = ""
        if hasattr(s, '_current_message_id') and s._current_message_id:
            message_id = s._current_message_id
            message_source = "text"
        elif hasattr(s, '_current_ai_voice_message_id') and s._current_ai_voice_message_id:
            message_id = s._current_ai_voice_message_id
            message_source = "voice"
        elif s._messages:
            # 如果没有当前消息ID，查找最后一个消息
            message_id = max(s._messages.keys(), key=lambda x: int(x.split('_')[-1]) if '_' in x else 0)
            message_source = "last"

        # 更新消息内容
        if message_id and message_id in s._messages:
            message_info = s._messages[message_id]

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
        s.smart_scroll_to_bottom()

if __name__=="__main__":
    app = QApplication(sys.argv)
    win = ChatWindow()
    win.show()
    sys.exit(app.exec_())
