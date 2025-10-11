from nagaagent_core.vendors.PyQt5.QtWidgets import QWidget, QTextEdit, QSizePolicy, QHBoxLayout, QLabel, QVBoxLayout, QStackedWidget, QScrollArea, QSplitter
from nagaagent_core.vendors.PyQt5.QtCore import Qt
from ..components.widget_live2d_side import Live2DSideWidget  # 导入Live2D侧栏组件
from ..components.widget_progress import EnhancedProgressWidget  # 导入进度组件
from system.config import config
from ..styles.button_factory import ButtonFactory
from .tool_document import DocumentTool
from ..elegant_settings_widget import ElegantSettingsWidget

import logging
# 设置日志
logger = logging.getLogger(__name__)
class ChatTool():
    def __init__(self, window):
        self.window = window
      
        
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
    
    def adjust_input_height(self):
        doc = self.input.document()
        h = int(doc.size().height())+10
        self.input.setFixedHeight(min(max(60, h), 150))  # 增加最小高度，与字体大小匹配
        self.input_wrap.setFixedHeight(self.input.height())
    
    
    def add_user_message(self, name, content, is_streaming=False):
        """添加用户消息"""
        from utils.response_util import extract_message
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
        self.chat_tool.smart_scroll_to_bottom()

        return message_id
    
    
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
            self.chat_tool.add_user_message(USER_NAME, u)
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
                self.worker.error.connect(lambda err: (self.progress_widget.stop_loading(), self.chat_tool.add_user_message("系统", f"❌ 博弈论调用错误: {err}")))
                def _on_finish_text(text):
                    self.progress_widget.stop_loading()
                    self.streaming_tool._start_non_stream_typewriter(text)
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
                    self.worker.error.connect(lambda err: (self.progress_widget.stop_loading(), self.chat_tool.add_user_message("系统", f"❌ 流式调用错误: {err}")))
                    # 将返回的data_str包裹成伪SSE处理路径，直接复用append_response_chunk节流更新
                    def _on_chunk(data_str):
                        # 过滤session_id与audio_url行，保持与handle_streaming_response一致
                        if data_str.startswith('session_id: '):
                            return
                        if data_str.startswith('audio_url: '):
                            return
                        self.streaming_tool.append_response_chunk(data_str)
                    self.worker.chunk.connect(_on_chunk)
                    self.worker.done.connect(self.streaming_tool.finalize_streaming_response)
                    self.worker.start()
                else:
                    # 创建并启动非流式worker
                    self.worker = _NonStreamHttpWorker(api_url, data)
                    self.worker.status.connect(lambda st: self.progress_widget.status_label.setText(st))
                    self.worker.error.connect(lambda err: (self.progress_widget.stop_loading(), self.chat_tool.add_user_message("系统", f"❌ 非流式调用错误: {err}")))
                    def _on_finish_text(text):
                        self.progress_widget.stop_loading()
                        self.streaming_tool._start_non_stream_typewriter(text)
                    self.worker.finished_text.connect(_on_finish_text)
                    self.worker.start()
                return
            
    
    def add_system_message(self, content: str) -> str:
        """添加系统消息到聊天界面"""
        msg = extract_message(content)
        content_html = str(msg).replace('\\n', '\n').replace('\n', '<br>')
        
        # 生成消息ID
        self._message_counter += 1
        message_id = f"msg_{self._message_counter}"
        
        # 创建系统消息对话框
        parent_widget = self._chat_layout.parentWidget()
        message_dialog = MessageRenderer.create_system_message(
            "系统", content_html, parent_widget
        )
        
        # 存储消息信息
        self._messages[message_id] = {
            'name': "系统",
            'content': content_html,
            'full_content': content,
            'dialog_widget': message_dialog,
            'is_ai': False,
            'is_system': True
        }
        
        # 添加到布局
        self._remove_layout_stretch()
        self._chat_layout.addWidget(message_dialog)
        self._chat_layout.addStretch()
        
        # 滚动到底部
        self.smart_scroll_to_bottom()
        return message_id
    
    def add_ai_message(self, content: str = "") -> str:
        """添加AI消息到聊天界面（流式处理时初始化为空消息）"""
        msg = extract_message(content)
        content_html = str(msg).replace('\\n', '\n').replace('\n', '<br>')
        
        # 生成消息ID
        self._message_counter += 1
        message_id = f"msg_{self._message_counter}"
        
        # 创建AI消息对话框
        parent_widget = self._chat_layout.parentWidget()
        message_dialog = MessageRenderer.create_ai_message(
            self._ai_name, content_html, parent_widget
        )
        
        # 存储消息信息
        self._messages[message_id] = {
            'name': self._ai_name,
            'content': content_html,
            'full_content': content,
            'dialog_widget': message_dialog,
            'is_ai': True
        }
        
        # 添加到布局
        self._remove_layout_stretch()
        self._chat_layout.addWidget(message_dialog)
        self._chat_layout.addStretch()
        
        return message_id
    
    
    def update_last_message(self, new_text):
        """更新最后一条消息的内容"""
        # 处理消息格式化
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

    
    def clear_chat_history(self):
        """清除所有聊天历史"""
        # 清除UI组件
        for msg_id, msg_info in self._messages.items():
            if msg_info['dialog_widget']:
                msg_info['dialog_widget'].deleteLater()
        
        # 清除布局
        while self._chat_layout.count() > 0:
            item = self._chat_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        
        # 重置状态
        self._messages.clear()
        self._message_counter = 0
        self._current_message_id = None
        self._current_response = ""
        
        # 恢复stretch
        self._chat_layout.addStretch()
    
    def load_persistent_history(self, max_messages: int = 20):
        """从持久化存储加载历史对话"""
        try:
            # 调用MessageRenderer加载历史
            ui_messages = MessageRenderer.load_persistent_context_to_ui(
                parent_widget=self._chat_layout.parentWidget(),
                max_messages=max_messages
            )
            
            if not ui_messages:
                self._logger.info("未加载到历史对话")
                return
            
            # 清空现有布局
            self._remove_layout_stretch()
            while self._chat_layout.count() > 0:
                item = self._chat_layout.takeAt(0)
                if item and item.widget():
                    item.widget().deleteLater()
            
            # 加载历史消息到UI和存储
            for message_id, message_info, dialog in ui_messages:
                self._chat_layout.addWidget(dialog)
                self._messages[message_id] = message_info
                self._message_counter = max(self._message_counter, int(message_id.split('_')[-1]))
            
            # 恢复stretch并滚动到底部
            self._chat_layout.addStretch()
            self.scroll_to_bottom()
            self._logger.info(f"加载完成 {len(ui_messages)} 条历史对话")
        
        except Exception as e:
            self._logger.error(f"加载历史对话失败: {str(e)}")
            self.add_system_message(f"❌ 加载历史对话失败: {str(e)}")

from ..utils.lazy import lazy
@lazy
def chat():
    return ChatTool(config.window)