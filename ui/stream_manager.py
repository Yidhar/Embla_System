from nagaagent_core.vendors.PyQt5.QtWidgets import QApplication, QWidget, QTextEdit, QSizePolicy, QHBoxLayout, QLabel, QVBoxLayout, QStackedLayout, QPushButton, QStackedWidget, QDesktopWidget, QScrollArea, QSplitter, QFileDialog, QMessageBox, QFrame  # 统一入口 #
from nagaagent_core.vendors.PyQt5.QtCore import Qt, QRect, QParallelAnimationGroup, QPropertyAnimation, QEasingCurve, QTimer, QThread, pyqtSignal, QObject  # 统一入口 #
from nagaagent_core.vendors.PyQt5.QtGui import QColor, QPainter, QBrush, QFont, QPen  # 统一入口 #
from ui.response_utils import extract_message
from ui.message_renderer import MessageRenderer
from ui.styles.progress_widget import EnhancedProgressWidget


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
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            self.status.emit("连接到AI...")
            # 设置重试策略 - 增加重试次数
            retry_strategy = Retry(
                total=3,  # 增加重试次数
                backoff_factor=1,  # 增加退避时间
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["POST"]  # 明确允许POST方法重试
            )
            # 创建session并配置重试
            session = requests.Session()
            adapter = HTTPAdapter(max_retries=retry_strategy)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            # 设置headers以支持更好的连接管理
            headers = {
                'Connection': 'keep-alive',
                'Content-Type': 'application/json',
                'Accept': 'text/event-stream',  # 明确接受SSE
                'Accept-Encoding': 'gzip, deflate',  # 支持压缩
                'User-Agent': 'NagaAgent-Client/1.0'  # 添加User-Agent
            }
            # 增加超时时间并配置流式请求
            timeout = (30, 120)  # (连接超时, 读取超时)
            resp = session.post(
                self.url,
                json=self.payload,
                headers=headers,
                timeout=timeout,
                stream=True,
                verify=False  # 如果有SSL问题可以临时禁用
            )
            if resp.status_code != 200:
                self.error.emit(
                    f"流式调用失败: HTTP {resp.status_code} - {resp.text[:200]}")
                return
            self.status.emit("正在生成回复...")
            # 使用更大的块大小来读取流
            buffer = []
            for line in resp.iter_lines(chunk_size=8192, decode_unicode=False):
                if self._cancelled:
                    break
                if line:
                    # 处理可能的编码问题
                    try:
                        # 使用UTF-8解码，忽略错误字符
                        line_str = line.decode(
                            'utf-8', errors='ignore').strip()
                        if line_str.startswith('data: '):
                            data_str = line_str[6:]
                            if data_str == '[DONE]':
                                break
                            # 过滤掉心跳包
                            if data_str and data_str != '':
                                # 直接把内容行交回主线程
                                self.chunk.emit(data_str)
                    except Exception as e:
                        print(f"解码错误: {e}")
                        continue
                else:
                    # 处理空行（SSE中心跳）
                    continue
            # 检查响应是否正常结束
            if not self._cancelled:
                resp.close()  # 显式关闭响应
                self.done.emit()
        except requests.exceptions.ChunkedEncodingError as e:
            self.error.emit(f"流式数据解码错误: {str(e)}")
        except requests.exceptions.ConnectionError as e:
            self.error.emit(f"连接错误: {str(e)}")
        except requests.exceptions.ReadTimeout as e:
            self.error.emit(f"读取超时: {str(e)}")
        except requests.exceptions.RequestException as e:
            self.error.emit(f"请求异常: {str(e)}")
        except Exception as e:
            import traceback
            error_msg = f"未知错误: {str(e)}\n详细信息: {traceback.format_exc()}"
            self.error.emit(error_msg)

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
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            self.status.emit("正在思考...")
            # 设置重试策略
            retry_strategy = Retry(
                total=2,
                backoff_factor=0.5,
                status_forcelist=[429, 500, 502, 503, 504],
            )
            # 创建session并配置重试
            session = requests.Session()
            adapter = HTTPAdapter(max_retries=retry_strategy)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            # 设置headers以支持更好的连接管理
            headers = {
                'Connection': 'keep-alive',
                'Content-Type': 'application/json'
            }
            resp = session.post(self.url, json=self.payload,
                                headers=headers, timeout=120)
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
            
from nagaagent_core.vendors.PyQt5.QtWidgets import QVBoxLayout, QScrollArea, QLabel, QWidget
from nagaagent_core.vendors.PyQt5.QtCore import QTimer, Qt
import time
import logging
from typing import Dict, Optional, List, Tuple

class StreamingChatManager:
    """流式聊天管理器，负责处理所有与聊天相关的功能"""
    
    def __init__(self, 
                 chat_layout: QVBoxLayout, 
                 chat_scroll_area: QScrollArea, 
                 progress_widget: EnhancedProgressWidget,
                 user_name: str,
                 ai_name: str,
                 streaming_mode: bool,
                 logger: logging.Logger):
        """
        初始化流式聊天管理器
        
        参数:
            chat_layout: 聊天消息布局容器
            chat_scroll_area: 聊天滚动区域
            progress_widget: 进度显示组件
            user_name: 用户名
            ai_name: AI名称
            streaming_mode: 是否启用流式模式
            logger: 日志器
        """
        # 外部依赖
        self._chat_layout = chat_layout
        self._chat_scroll_area = chat_scroll_area
        self._progress_widget = progress_widget
        self._user_name = user_name
        self._ai_name = ai_name
        self._streaming_mode = streaming_mode
        self._logger = logger
        
        # 消息管理
        self._messages: Dict[str, Dict] = {}  # 消息存储：ID -> 消息信息
        self._message_counter = 0  # 消息ID计数器
        
        # 流式处理状态
        self._current_message_id: Optional[str] = None  # 当前处理的消息ID
        self._current_response = ""  # 当前响应内容
        self._last_update_time = 0  # 上次UI更新时间（用于节流）
        
        # 打字机效果相关
        self._stream_typewriter_buffer = ""
        self._stream_typewriter_index = 0
        self._stream_typewriter_timer: Optional[QTimer] = None
        self._non_stream_timer: Optional[QTimer] = None
        self._non_stream_text = ""
        self._non_stream_index = 0
        
        # Worker管理
        self._worker: Optional[_StreamHttpWorker] = None
        
        # 工具调用状态
        self._in_tool_call_mode = False

    # ------------------------------
    # 消息管理核心方法
    # ------------------------------
    
    def add_user_message(self, content: str) -> str:
        """添加用户消息到聊天界面"""
        msg = extract_message(content)
        content_html = str(msg).replace('\\n', '\n').replace('\n', '<br>')
        
        # 生成消息ID
        self._message_counter += 1
        message_id = f"msg_{self._message_counter}"
        
        # 创建用户消息对话框
        parent_widget = self._chat_layout.parentWidget()
        message_dialog = MessageRenderer.create_user_message(
            self._user_name, content_html, parent_widget
        )
        
        # 存储消息信息
        self._messages[message_id] = {
            'name': self._user_name,
            'content': content_html,
            'full_content': content,
            'dialog_widget': message_dialog,
            'is_ai': False
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
    
    def update_last_message(self, new_text: str):
        """更新最后一条消息的内容"""
        if not self._messages:
            return
        
        # 获取最后一条消息ID
        last_msg_id = max(self._messages.keys(), key=lambda x: int(x.split('_')[-1]))
        last_msg = self._messages[last_msg_id]
        
        # 格式化内容
        msg = extract_message(new_text)
        content_html = str(msg).replace('\\n', '\n').replace('\n', '<br>')
        
        # 更新存储与UI
        last_msg['content'] = content_html
        last_msg['full_content'] = new_text
        MessageRenderer.update_message_content(last_msg['dialog_widget'], content_html)
        
        # 智能滚动
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

    # ------------------------------
    # 流式响应处理
    # ------------------------------
    
    def handle_streaming_response(self, resp):
        """处理流式响应"""
        try:
            # 启动进度显示
            self._progress_widget.set_thinking_mode()
            
            # 累积响应内容
            response_content = ""
            message_started = False
            
            # 打字机效果相关
            self._stream_typewriter_buffer = ""
            self._stream_typewriter_index = 0
            
            # 处理流式数据
            for line in resp.iter_lines():
                if line:
                    # 使用UTF-8解码，忽略错误字符
                    line_str = line.decode('utf-8', errors='ignore')
                    if line_str.startswith('data: '):
                        data_str = line_str[6:]
                        if data_str == '[DONE]':
                            break
                        elif data_str.startswith('session_id: '):
                            # 处理会话ID
                            session_id = data_str[12:]
                            self._logger.debug(f"会话ID: {session_id}")
                        elif data_str.startswith('audio_url: '):
                            # 音频URL由apiserver直接处理
                            pass
                        else:
                            # 处理内容数据
                            response_content += data_str
                            self._stream_typewriter_buffer += data_str
                            
                            # 如果是第一条消息，创建新消息并设置当前消息ID
                            if not message_started:
                                self._current_message_id = self.add_ai_message("")
                                message_started = True
                                # 启动流式打字机效果
                                self._start_stream_typewriter()
            
            # 完成处理 - 停止打字机，显示完整内容
            self._stop_stream_typewriter()
            self.update_last_message(response_content)
            self._progress_widget.stop_loading()
            
        except Exception as e:
            self.add_system_message(f"❌ 流式处理错误: {str(e)}")
            self._progress_widget.stop_loading()
    
    def append_response_chunk(self, chunk: str):
        """追加响应片段（流式模式）- 实时显示到消息框"""
        # 检查是否为工具调用相关标记
        if any(marker in chunk for marker in ["[TOOL_CALL]", "[TOOL_START]", "[TOOL_RESULT]", "[TOOL_ERROR]"]):
            return

        # 检查是否在工具调用过程中
        if self._in_tool_call_mode:
            # 工具调用模式结束，创建新的消息框
            self._in_tool_call_mode = False
            self._current_message_id = None

        # 实时更新显示
        if not self._current_message_id:
            # 第一次收到chunk时，创建新消息
            self._current_message_id = self.add_ai_message(chunk)
            self._current_response = chunk
        else:
            # 后续chunk，追加到当前消息
            self._current_response += chunk
            
            # 限制更新频率（节流）
            current_time = time.time()
            # 每50毫秒更新一次UI，减少闪动
            if current_time - self._last_update_time >= 0.05:
                self.update_last_message(self._current_response)
                self._last_update_time = current_time
    
    def finalize_streaming_response(self):
        """完成流式响应处理"""
        if self._current_response:
            # 对累积的完整响应进行消息提取
            final_message = extract_message(self._current_response)
            
            # 更新最终消息
            if self._current_message_id:
                self.update_last_message(final_message)
        
        # 重置状态
        self._current_response = ""
        self._current_message_id = None
        if hasattr(self, '_last_update_time'):
            delattr(self, '_last_update_time')

        # 停止加载状态
        self._progress_widget.stop_loading()
    
    # ------------------------------
    # 打字机效果
    # ------------------------------
    
    def _start_stream_typewriter(self):
        """启动流式聊天的打字机效果"""
        if self._stream_typewriter_timer and self._stream_typewriter_timer.isActive():
            return

        self._stream_typewriter_timer = QTimer()
        self._stream_typewriter_timer.timeout.connect(self._stream_typewriter_tick)
        self._stream_typewriter_timer.start(100)  # 100ms一个字符
    
    def _stream_typewriter_tick(self):
        """流式聊天的打字机效果tick"""
        if self._stream_typewriter_index >= len(self._stream_typewriter_buffer):
            self._stop_stream_typewriter()
            return

        # 每次显示1-3个字符
        next_char = self._stream_typewriter_buffer[self._stream_typewriter_index]
        chars_to_add = 1

        # 如果是英文字符或空格，可以一次显示多个
        if next_char and ord(next_char) < 128:  # ASCII字符
            chars_to_add = min(3, len(self._stream_typewriter_buffer) - self._stream_typewriter_index)

        self._stream_typewriter_index += chars_to_add
        displayed_text = self._stream_typewriter_buffer[:self._stream_typewriter_index]

        # 更新消息显示
        self.update_last_message(displayed_text)
    
    def _stop_stream_typewriter(self):
        """停止流式打字机效果"""
        if self._stream_typewriter_timer and self._stream_typewriter_timer.isActive():
            self._stream_typewriter_timer.stop()
            self._stream_typewriter_timer.deleteLater()
            self._stream_typewriter_timer = None
    
    def start_non_stream_typewriter(self, full_text: str):
        """为非流式响应启动打字机效果"""
        # 创建空消息
        message_id = self.add_ai_message("")
        self._non_stream_message_id = message_id
        self._current_message_id = message_id  # 让update_last_message能找到这个消息

        # 初始化打字机变量
        self._non_stream_text = full_text
        self._non_stream_index = 0

        if not self._non_stream_timer:
            self._non_stream_timer = QTimer()
            self._non_stream_timer.timeout.connect(self._non_stream_typewriter_tick)

        # 启动定时器
        self._non_stream_timer.start(100)  # 100ms一个字符
    
    def _non_stream_typewriter_tick(self):
        """非流式响应的打字机效果tick"""
        if self._non_stream_index >= len(self._non_stream_text):
            # 所有字符都显示完了，停止定时器并清理
            self._non_stream_timer.stop()
            self._non_stream_timer.deleteLater()
            self._non_stream_timer = None
            
            # 清理临时变量
            delattr(self, '_non_stream_text')
            delattr(self, '_non_stream_index')
            delattr(self, '_non_stream_message_id')
            self._current_message_id = None
            return

        # 每次显示1-3个字符
        next_char = self._non_stream_text[self._non_stream_index]
        chars_to_add = 1

        # 如果是英文字符或空格，可以一次显示多个
        if next_char and ord(next_char) < 128:  # ASCII字符
            chars_to_add = min(3, len(self._non_stream_text) - self._non_stream_index)

        self._non_stream_index += chars_to_add
        displayed_text = self._non_stream_text[:self._non_stream_index]

        # 更新消息显示
        self.update_last_message(displayed_text)

    # ------------------------------
    # Worker管理
    # ------------------------------
    
    def setup_streaming_worker(self, worker: _StreamHttpWorker):
        """配置流式Worker的信号连接"""
        self._worker = worker
        worker.status.connect(lambda st: self._progress_widget.status_label.setText(st))
        worker.error.connect(lambda err: (
            self._progress_widget.stop_loading(),
            self.add_system_message(f"❌ 流式调用错误: {err}")
        ))
        worker.chunk.connect(self.append_response_chunk)
        worker.done.connect(self.finalize_streaming_response)
        worker.finished.connect(self._on_worker_finished)
    
    def setup_batch_worker(self, worker: _NonStreamHttpWorker):
        """配置批量Worker的信号连接"""
        self._worker = worker
        worker.status.connect(lambda st: self._progress_widget.status_label.setText(st))
        worker.error.connect(lambda err: (
            self._progress_widget.stop_loading(),
            self.add_system_message(f"❌ 批量调用错误: {err}")
        ))
        
        def on_finish_text(text):
            self._progress_widget.stop_loading()
            self.start_non_stream_typewriter(text)
            
        worker.finished_text.connect(on_finish_text)
        worker.finished.connect(self._on_worker_finished)
    
    def _on_worker_finished(self):
        """Worker完成后的清理工作"""
        self._worker = None
    
    def cancel_current_task(self):
        """取消当前任务"""
        # 停止所有打字机效果
        self._stop_stream_typewriter()
        
        if self._non_stream_timer and self._non_stream_timer.isActive():
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
        
        # 处理worker
        if self._worker and self._worker.isRunning():
            # 立即设置取消标志
            self._worker.cancel()
            
            # 非阻塞方式处理线程清理
            self._progress_widget.stop_loading()
            self.add_system_message("🚫 操作已取消")
            
            # 清空当前响应缓冲
            self._current_response = ""
            self._current_message_id = None
            
            # 使用QTimer延迟处理线程清理，避免UI卡顿
            QTimer.singleShot(50, self._cleanup_worker)
        else:
            self._progress_widget.stop_loading()
    
    def _cleanup_worker(self):
        """清理Worker资源"""
        if self._worker:
            self._worker.quit()
            if not self._worker.wait(500):  # 只等待500ms
                self._worker.terminate()
                self._worker.wait(200)  # 再等待200ms
            self._worker.deleteLater()
            self._worker = None

    # ------------------------------
    # 工具调用处理
    # ------------------------------
    
    def handle_tool_call(self, notification: str):
        """处理工具调用通知"""
        # 标记进入工具调用模式
        self._in_tool_call_mode = True

        # 创建专门的工具调用内容对话框
        parent_widget = self._chat_layout.parentWidget()
        tool_call_dialog = MessageRenderer.create_tool_call_content_message(notification, parent_widget)

        # 设置嵌套对话框内容
        nested_title = "工具调用详情"
        nested_content = f"""
工具名称: {notification}
状态: 正在执行...
时间: {time.strftime('%H:%M:%S')}
        """.strip()
        tool_call_dialog.set_nested_content(nested_title, nested_content)

        # 生成消息ID
        self._message_counter += 1
        message_id = f"tool_call_{self._message_counter}"

        # 存储工具调用消息信息
        self._messages[message_id] = {
            'name': '工具调用',
            'content': notification,
            'full_content': notification,
            'dialog_widget': tool_call_dialog,
            'is_tool_call': True
        }

        # 添加到布局
        self._remove_layout_stretch()
        self._chat_layout.addWidget(tool_call_dialog)
        self._chat_layout.addStretch()

        # 滚动到底部
        self.scroll_to_bottom()

        # 在状态栏显示工具调用状态
        self._progress_widget.status_label.setText(f"🔧 {notification}")
        self._logger.debug(f"工具调用: {notification}")
    
    def handle_tool_result(self, result: str):
        """处理工具执行结果"""
        # 查找最近的工具调用对话框并更新
        if self._messages:
            for message_id, message_info in reversed(list(self._messages.items())):
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
        
        # 工具调用完成，退出工具调用模式
        self._in_tool_call_mode = False
        
        # 在状态栏显示工具执行结果
        self._progress_widget.status_label.setText(f"✅ {result[:50]}...")
        self._logger.debug(f"工具结果: {result}")

    # ------------------------------
    # 滚动控制
    # ------------------------------
    
    def scroll_to_bottom(self):
        """滚动到聊天区域底部"""
        # 使用QTimer延迟滚动，确保布局完成
        QTimer.singleShot(10, lambda: self._chat_scroll_area.verticalScrollBar().setValue(
            self._chat_scroll_area.verticalScrollBar().maximum()
        ))
    
    def smart_scroll_to_bottom(self):
        """智能滚动到底部（如果用户正在查看历史消息，则不滚动）"""
        scrollbar = self._chat_scroll_area.verticalScrollBar()
        # 检查是否已经在底部附近（允许50像素的误差）
        is_at_bottom = scrollbar.value() >= scrollbar.maximum() - 50

        # 如果本来就在底部附近，则自动滚动到最新消息
        if is_at_bottom:
            self.scroll_to_bottom()
    
    def _remove_layout_stretch(self):
        """移除布局中最后一个stretch"""
        for i in reversed(range(self._chat_layout.count())):
            item = self._chat_layout.itemAt(i)
            if item and not item.widget():  # 识别stretch/spacer
                self._chat_layout.removeItem(item)
                break

    # ------------------------------
    # 属性访问器
    # ------------------------------
    
    @property
    def streaming_mode(self) -> bool:
        """获取当前是否为流式模式"""
        return self._streaming_mode
    
    @streaming_mode.setter
    def streaming_mode(self, value: bool):
        """设置是否为流式模式"""
        self._streaming_mode = value
        
    @property
    def messages(self) -> Dict[str, Dict]:
        """获取所有消息"""
        return self._messages.copy()  # 返回副本，防止外部修改
