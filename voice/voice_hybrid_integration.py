# -*- coding: utf-8 -*-
"""
混合模式语音集成管理器
使用通义千问ASR + API Server处理 + 服务器端TTS

架构：
- TTS完全由服务器端处理，客户端只负责播放
- 使用实例方法避免闭包生命周期问题
- 支持正常关闭和状态管理
"""

from nagaagent_core.vendors.PyQt5.QtCore import QObject, pyqtSignal, QThread
import threading
import requests
import json
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any
import logging
import time
import os
import gc
import sys
import uuid  # 添加UUID来追踪调用
import traceback as tb  # 用于获取调用栈

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 全局初始化pygame mixer
try:
    import pygame
    if not pygame.mixer.get_init():
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=1024)
            logger.info("[全局] pygame mixer已初始化")
        except:
            try:
                pygame.mixer.init(frequency=16000, size=-16, channels=1, buffer=512)
                logger.info("[全局] pygame mixer已用最小配置初始化")
            except:
                logger.warning("[全局] pygame mixer初始化失败")
except ImportError:
    logger.info("[全局] pygame未安装")
except Exception as e:
    logger.warning(f"[全局] pygame mixer初始化异常: {e}")


class SafeAudioPlayer(QThread):
    """安全的音频播放器线程"""
    play_finished = pyqtSignal()
    play_error = pyqtSignal(str)

    def __init__(self, audio_file: str):
        super().__init__()
        self.audio_file = audio_file
        self._stop_flag = False
        self.tts_id = "unknown"  # TTS追踪ID

    def run(self):
        """播放音频"""
        success = False
        try:
            logger.info(f"[SafeAudioPlayer] 开始播放音频文件: {self.audio_file}")

            # 检查文件是否存在
            if not os.path.exists(self.audio_file):
                logger.error(f"[SafeAudioPlayer] 音频文件不存在: {self.audio_file}")
                self.play_error.emit("音频文件不存在")
                return

            file_size = os.path.getsize(self.audio_file)
            logger.info(f"[SafeAudioPlayer] 文件大小: {file_size} bytes")

            success = self._try_pygame()
            if not success:
                logger.warning(f"[SafeAudioPlayer] pygame播放失败，尝试系统播放器")
                success = self._try_system_player()

            if not success:
                logger.error(f"[SafeAudioPlayer] 所有播放方式都失败")
                self.play_error.emit("所有播放方式都失败了")
            else:
                logger.info(f"[SafeAudioPlayer] 播放成功完成")

        except Exception as e:
            logger.error(f"[SafeAudioPlayer] 播放错误: {e}")
            self.play_error.emit(str(e))
        finally:
            self.play_finished.emit()

    def _try_pygame(self) -> bool:
        """尝试使用pygame播放"""
        try:
            import pygame

            if not pygame.mixer.get_init():
                configs = [
                    {"frequency": 22050, "size": -16, "channels": 2, "buffer": 1024},
                    {"frequency": 16000, "size": -16, "channels": 1, "buffer": 512},
                ]

                for cfg in configs:
                    try:
                        pygame.mixer.init(**cfg)
                        if pygame.mixer.get_init():
                            break
                    except:
                        pass

            if pygame.mixer.get_init() and os.path.exists(self.audio_file):
                pygame.mixer.music.load(self.audio_file)
                pygame.mixer.music.play()

                while pygame.mixer.music.get_busy():
                    if self._stop_flag:
                        pygame.mixer.music.stop()
                        break
                    time.sleep(0.1)

                pygame.mixer.music.unload()
                logger.info("[SafeAudioPlayer] pygame播放完成")
                return True

            return False

        except Exception as e:
            logger.error(f"[SafeAudioPlayer] pygame异常: {e}")
            return False

    def _try_system_player(self) -> bool:
        """尝试使用系统播放器"""
        try:
            import platform
            system = platform.system()

            if system == "Windows":
                import winsound
                winsound.PlaySound(self.audio_file, winsound.SND_FILENAME)
                logger.info("[SafeAudioPlayer] winsound播放完成")
                return True

            return False

        except Exception as e:
            logger.error(f"[SafeAudioPlayer] 系统播放器失败: {e}")
            return False

    def stop(self):
        """停止播放"""
        self._stop_flag = True


class HybridVoiceIntegration(QObject):
    """混合模式语音集成管理器"""

    # 信号定义
    update_ui_signal = pyqtSignal(str, object)  # (action, data)
    audio_done_signal = pyqtSignal(str)  # tts_id - 用于音频播放完成通知

    # 状态常量
    STATE_IDLE = "idle"
    STATE_LISTENING = "listening"
    STATE_PROCESSING = "processing"
    STATE_SPEAKING = "speaking"

    def __init__(self, parent_widget):
        """初始化"""
        super().__init__()
        self.parent = parent_widget
        self.voice_client = None

        # 状态管理
        self._state_lock = threading.RLock()
        self._is_active = False
        self._is_stopping = False  # V19: 添加停止标志，防止自动重连
        self._current_state = self.STATE_IDLE
        self._session_active = True  # 会话活跃标志

        # 音频播放
        self._audio_player: Optional[SafeAudioPlayer] = None
        self._audio_files_to_clean = []
        self._current_tts_id = "unknown"  # 保存当前TTS ID

        # 消息管理
        self._api_response = ""
        self._message_id = None

        # 配置
        from system.config import config
        self._config = {
            'tts_voice': getattr(config.voice_realtime, 'tts_voice', 'zh-CN-XiaoyiNeural'),
            'tts_speed': 1.0,
            'ai_name': config.system.ai_name,
            'user_name': config.ui.user_name,
        }

        # 连接信号
        self.update_ui_signal.connect(self._on_ui_signal)
        self.audio_done_signal.connect(self._on_audio_done)

        # 启动清理线程
        self._start_cleanup_thread()

        logger.info("[混合模式] 初始化完成")

    def _set_state(self, new_state: str, update_ui: bool = True):
        """统一的状态设置方法"""
        with self._state_lock:
            if self._current_state == new_state:
                return  # 状态未改变

            old_state = self._current_state
            self._current_state = new_state
            logger.info(f"[混合模式] 状态切换: {old_state} -> {new_state}")

            # 更新UI
            if update_ui and self._is_active:
                # 映射内部状态到UI状态
                ui_state = new_state
                if new_state == self.STATE_SPEAKING:
                    ui_state = "ai_speaking"
                elif new_state == self.STATE_PROCESSING:
                    ui_state = "processing"
                elif new_state == self.STATE_LISTENING:
                    ui_state = "listening"
                elif new_state == self.STATE_IDLE:
                    ui_state = "idle"

                self.update_ui_signal.emit("state", ui_state)
                logger.info(f"[混合模式] UI状态更新: {ui_state}")

    def _start_cleanup_thread(self):
        """启动文件清理线程"""
        def cleanup_worker():
            while self._session_active:
                time.sleep(10)
                if self._session_active:
                    self._cleanup_old_files()

        thread = threading.Thread(target=cleanup_worker, daemon=True)
        thread.start()

    def _cleanup_old_files(self):
        """清理旧的音频文件"""
        with self._state_lock:
            files_to_clean = self._audio_files_to_clean.copy()
            self._audio_files_to_clean.clear()

        for file_path in files_to_clean:
            try:
                if os.path.exists(file_path):
                    for _ in range(3):
                        try:
                            os.unlink(file_path)
                            logger.debug(f"[混合模式] 清理文件成功: {file_path}")
                            break
                        except PermissionError:
                            time.sleep(1)
            except Exception as e:
                logger.debug(f"[混合模式] 清理文件失败: {e}")

    def start_voice(self, config_params: dict) -> bool:
        """启动语音服务"""
        try:
            logger.info("[混合模式] 启动语音服务...")

            # 导入voice_realtime模块
            from voice.voice_realtime import create_voice_client

            # 添加使用语音提示词的设置
            config_params['use_voice_prompt'] = True  # 混合模式也使用语音提示词

            # 先进行类级别的猴子补丁（以防万一）
            try:
                from voice.voice_realtime.core import audio_manager

                # 保存原始方法
                original_add_output_audio = audio_manager.AudioManager.add_output_audio

                # 定义拦截函数
                def intercepted_add_output_audio(self, audio_b64: str):
                    """拦截音频输出"""
                    logger.debug("[混合模式] 类级别拦截了add_output_audio调用")
                    return

                # 替换类方法
                audio_manager.AudioManager.add_output_audio = intercepted_add_output_audio
                logger.info("[混合模式] AudioManager类方法已被替换")

            except Exception as e:
                logger.warning(f"[混合模式] 类级别补丁失败: {e}")

            # 创建语音客户端
            self.voice_client = create_voice_client(**config_params)
            if not self.voice_client:
                self._show_error("创建语音客户端失败")
                return False

            # 设置客户端配置，确保可以控制重连行为
            if hasattr(self.voice_client, '_client'):
                if hasattr(self.voice_client._client, 'config'):
                    # 默认允许重连，但确保可以被stop_voice方法禁用
                    if 'auto_reconnect' not in self.voice_client._client.config:
                        self.voice_client._client.config['auto_reconnect'] = True
                    logger.info(f"[混合模式] 客户端auto_reconnect设置为: {self.voice_client._client.config.get('auto_reconnect', True)}")

            # 关键：对实例进行猴子补丁
            try:
                # 获取AudioManager实例
                if hasattr(self.voice_client, '_client'):
                    qwen_client = self.voice_client._client
                    if hasattr(qwen_client, 'audio_manager'):
                        audio_mgr = qwen_client.audio_manager

                        # 保存原始方法
                        original_instance_add_output = audio_mgr.add_output_audio
                        original_instance_mark_done = audio_mgr.mark_response_done

                        # 定义实例级别的拦截函数
                        audio_intercept_count = [0]  # 使用列表来在闭包中记录计数

                        def instance_add_output_audio(audio_b64: str):
                            """实例级别拦截音频输出"""
                            audio_intercept_count[0] += 1
                            audio_size = len(audio_b64) if audio_b64 else 0
                            logger.debug(f"[混合模式] 拦截千问音频 #{audio_intercept_count[0]}，大小: {audio_size}")

                            # 打印调用栈
                            stack = tb.extract_stack()
                            for frame in stack[-5:-1]:  # 显示调用链
                                logger.debug(f"  -> {frame.filename}:{frame.lineno} in {frame.name}")

                            # 什么都不做，完全忽略
                            return

                        def instance_mark_response_done():
                            """实例级别拦截响应完成"""
                            logger.debug("[混合模式] 实例级别拦截了mark_response_done")
                            audio_mgr.ai_response_done = True
                            # 不在这里调用_on_audio_done，等待我们自己的音频播放完成

                        # 替换实例方法
                        audio_mgr.add_output_audio = instance_add_output_audio
                        audio_mgr.mark_response_done = instance_mark_response_done

                        logger.info("[混合模式] AudioManager实例方法已被成功替换")

                        # 额外：清空可能已经存在的音频队列
                        if hasattr(audio_mgr, 'output_queue'):
                            try:
                                while not audio_mgr.output_queue.empty():
                                    audio_mgr.output_queue.get_nowait()
                                logger.info("[混合模式] 已清空输出音频队列")
                            except:
                                pass

                        if hasattr(audio_mgr, 'b64_output_queue'):
                            try:
                                while not audio_mgr.b64_output_queue.empty():
                                    audio_mgr.b64_output_queue.get_nowait()
                                logger.info("[混合模式] 已清空B64音频队列")
                            except:
                                pass

            except Exception as e:
                logger.error(f"[混合模式] 实例级别补丁失败: {e}")
                import traceback
                traceback.print_exc()

            # 设置回调
            logger.info("[混合模式] 设置回调函数...")

            callbacks = {
                'on_user_text': self._on_user_speech,  # 用户语音识别
                'on_text': self._on_ai_text_ignored,  # AI文本响应 - 忽略
                'on_response_complete': self._on_response_complete,  # 响应完成 - 处理
                'on_status': self._on_status_changed,  # 状态变化
                'on_error': lambda e: self.update_ui_signal.emit("error", e)
            }

            self.voice_client.set_callbacks(**callbacks)

            # 连接服务
            if not self.voice_client.connect():
                self._show_error("连接语音服务失败")
                self.voice_client = None
                return False

            # 更新状态
            with self._state_lock:
                self._is_active = True
            self._set_state(self.STATE_LISTENING)
            self._show_info("✅ 实时语音模式已启动，请说话...")

            return True

        except Exception as e:
            logger.error(f"[混合模式] 启动失败: {e}")
            import traceback
            traceback.print_exc()
            self._show_error(f"启动失败: {str(e)}")
            return False

    def _on_ai_text_ignored(self, text):
        """忽略AI文本"""
        logger.debug(f"[混合模式] 忽略千问文本: {text[:50] if text else ''}...")
        return

    def _on_response_complete(self):
        """处理响应完成 - 确保继续监听"""
        logger.info("[混合模式] 千问响应完成，但我们使用API Server的响应")
        # 不在这里改变状态，等待TTS播放完成后再改变

    def _on_status_changed(self, status):
        """处理状态变化"""
        logger.info(f"[混合模式] 千问客户端状态变化: {status}")

        # 优先检查停止标志
        if self._is_stopping or not self._is_active:
            logger.info(f"[混合模式] 忽略状态变化 (stopping={self._is_stopping}, active={self._is_active})")
            return

        # 只在监听状态更新UI
        if status in ["listening", "connected"]:
            if self._is_active and self._session_active:
                self._set_state(self.STATE_LISTENING)
        elif status == "disconnected":
            # 检查是否是主动停止
            if getattr(self.parent, '_is_manual_stop', False):
                # 主动停止，不处理为超时断开
                logger.info("[混合模式] 用户主动停止，不设置超时标记")
            else:
                # 更严格的重连条件检查
                if self._is_active and self._session_active and not self._is_stopping:
                    logger.warning("[混合模式] 连接意外断开（可能是超时）")
                    # 标记为超时断开（在父窗口上设置）
                    self.parent._is_timeout_disconnect = True
                    # 更新父窗口状态
                    self.parent.voice_realtime_active = False
                    self.parent.voice_realtime_state = "idle"
                    self.parent.update_voice_button_state("idle")
                    # 通过error信号发送超时消息（父窗口会检查避免重复）
                    self.update_ui_signal.emit("error", "⏱️ 长时间未进行语音交流，语音连接已自动断开")
                    # 重置内部状态
                    self._is_active = False
                    self._session_active = False
                    self._set_state(self.STATE_IDLE)
                else:
                    logger.info(f"[混合模式] 正常断开连接，不处理")

    def _on_user_speech(self, text: str):
        """用户语音识别回调 - 核心功能"""
        logger.info(f"[混合模式] 识别到用户语音: {text}")

        if not text or not text.strip():
            logger.warning("[混合模式] 识别文本为空，忽略")
            return

        with self._state_lock:
            if self._current_state != self.STATE_LISTENING:
                logger.info(f"[混合模式] 当前状态为{self._current_state}，忽略新输入")
                return

        # 切换到处理状态
        self._set_state(self.STATE_PROCESSING)

        # 通过信号在主线程处理
        self.update_ui_signal.emit("user_speech", text)

    def _on_ui_signal(self, action: str, data: Any):
        """处理UI信号（主线程）"""
        try:
            if action == "user_speech":
                self._handle_user_speech(data)

            elif action == "state":
                # 更新UI状态
                self.parent.voice_realtime_state = data
                self.parent.update_voice_button_state(data)

            elif action == "progress":
                # 处理进度条
                if data:
                    self.parent.progress_widget.set_thinking_mode()
                else:
                    if hasattr(self.parent, 'progress_widget'):
                        self.parent.progress_widget.stop_loading()

            elif action == "add_msg":
                # 添加消息 - 使用打字机效果
                name, content = data
                # 创建空消息，通过打字机效果逐步显示
                msg_id = self.parent.add_user_message(name, "🔊 ")
                if name == self._config['ai_name']:
                    self._message_id = msg_id
                    self.parent._current_message_id = msg_id
                    # 初始化混合模式打字机效果
                    self._init_hybrid_typewriter(content[3:] if content.startswith("🔊 ") else content)  # 去掉🔊前缀

            elif action == "update_msg":
                # 更新消息 - 继续打字机效果
                if self._message_id or hasattr(self.parent, '_current_message_id'):
                    # 更新缓冲区并继续打字机
                    content = data[3:] if data.startswith("🔊 ") else data  # 去掉🔊前缀
                    self._hybrid_typewriter_buffer = content
                    # 如果打字机没在运行，重新启动
                    if hasattr(self, '_hybrid_typewriter_timer') and self._hybrid_typewriter_timer and not self._hybrid_typewriter_timer.isActive():
                        self._hybrid_typewriter_timer.start()

            elif action == "update_display":
                # 更新消息显示（来自打字机效果）
                if hasattr(self.parent, 'update_last_message'):
                    self.parent.update_last_message(data)

            elif action == "error":
                # 显示错误
                self.parent.add_user_message("系统", f"❌ {data}")

            elif action == "info":
                # 显示信息
                self.parent.add_user_message("系统", data)

        except Exception as e:
            logger.error(f"[混合模式] UI信号处理失败: {e}")
            import traceback
            traceback.print_exc()

    def _init_hybrid_typewriter(self, initial_text):
        """初始化混合模式打字机效果"""
        from nagaagent_core.vendors.PyQt5.QtCore import QTimer

        self._hybrid_typewriter_buffer = initial_text
        self._hybrid_typewriter_index = 0

        if not hasattr(self, '_hybrid_typewriter_timer') or self._hybrid_typewriter_timer is None:
            self._hybrid_typewriter_timer = QTimer()
            self._hybrid_typewriter_timer.timeout.connect(self._hybrid_typewriter_tick)

        # 启动打字机
        self._hybrid_typewriter_timer.start(30)  # 30ms一个字符

    def _hybrid_typewriter_tick(self):
        """混合模式打字机效果tick"""
        if not hasattr(self, '_hybrid_typewriter_buffer'):
            self._hybrid_typewriter_timer.stop()
            return

        # 如果还有字符未显示
        if self._hybrid_typewriter_index < len(self._hybrid_typewriter_buffer):
            # 每次显示1-2个字符
            next_char = self._hybrid_typewriter_buffer[self._hybrid_typewriter_index] if self._hybrid_typewriter_index < len(self._hybrid_typewriter_buffer) else ''
            chars_to_add = 1

            # 如果是英文字符，可以一次显示多个
            if next_char and ord(next_char) < 128:  # ASCII字符
                chars_to_add = min(2, len(self._hybrid_typewriter_buffer) - self._hybrid_typewriter_index)

            self._hybrid_typewriter_index += chars_to_add
            displayed_text = self._hybrid_typewriter_buffer[:self._hybrid_typewriter_index]

            # 通过信号更新消息显示
            self.update_ui_signal.emit("update_display", f"🔊 {displayed_text}")
        else:
            # 所有字符都显示完了，停止定时器
            self._hybrid_typewriter_timer.stop()

    def _handle_user_speech(self, text: str):
        """处理用户语音（主线程）"""
        try:
            # 显示用户消息
            self.parent.add_user_message(self._config['user_name'], f"🎤 {text}")

            # 显示进度条
            self.update_ui_signal.emit("progress", True)

            # 启动API调用线程
            thread = threading.Thread(
                target=self._call_api,
                args=(text,),
                daemon=True
            )
            thread.start()

        except Exception as e:
            logger.error(f"[混合模式V19] 处理用户语音失败: {e}")
            import traceback
            traceback.print_exc()
            self._reset_state()

    def _call_api(self, text: str):
        """调用API Server（后台线程）"""
        try:
            url = "http://localhost:8000/chat/stream"

            # 请求服务器返回音频
            data = {
                "message": text,
                "stream": True,
                "use_self_game": False,
                "voice_mode": "hybrid",  # 告知服务器这是混合模式
                "return_audio": True  # 请求返回音频URL
            }

            logger.info(f"[混合模式] API调用: {text}")
            resp = requests.post(url, json=data, timeout=120, stream=True)

            if resp.status_code == 200:
                self._handle_stream(resp)
            else:
                self.update_ui_signal.emit("error", f"API错误: {resp.status_code}")
                self._reset_state()

        except Exception as e:
            logger.error(f"[混合模式] API调用失败: {e}")
            self.update_ui_signal.emit("error", str(e))
            self._reset_state()

    def _handle_stream(self, resp):
        """处理流式响应 - 接收音频URL而不是生成TTS"""
        try:
            self._api_response = ""
            audio_url = None
            created = False

            for line in resp.iter_lines():
                if line:
                    line_str = line.decode('utf-8')
                    if line_str.startswith('data: '):
                        data = line_str[6:]

                        if data == '[DONE]':
                            break
                        elif data.startswith('audio_url: '):
                            # 接收音频URL
                            audio_url = data[11:]
                            logger.info(f"[混合模式] 接收到音频URL: {audio_url}")
                        elif data.startswith('session_id: '):
                            continue
                        else:
                            # 文本内容
                            self._api_response += data

                            if not created:
                                self.update_ui_signal.emit("add_msg",
                                    (self._config['ai_name'], f"🔊 {data}"))
                                created = True
                            else:
                                self.update_ui_signal.emit("update_msg",
                                    f"🔊 {self._api_response}")

            logger.info(f"[混合模式] API响应完成: {len(self._api_response)}字")

            # 停止进度条
            self.update_ui_signal.emit("progress", False)

            # 停止打字机效果并显示完整内容
            if hasattr(self, '_hybrid_typewriter_timer') and self._hybrid_typewriter_timer:
                self._hybrid_typewriter_timer.stop()
                self._hybrid_typewriter_timer.deleteLater()
                self._hybrid_typewriter_timer = None
                # 确保显示完整内容（通过信号）
                if self._api_response:
                    self.update_ui_signal.emit("update_display", f"🔊 {self._api_response}")

            # 播放音频URL
            if audio_url and self._api_response:  # 确保有响应文本才播放音频
                logger.info(f"[混合模式] 准备播放服务器返回的音频")
                self._play_audio_url(audio_url)
            elif self._api_response:
                # 如果服务器没有返回音频，降级到客户端TTS（兼容）
                logger.warning("[混合模式] 服务器未返回音频，降级到客户端TTS")
                self._convert_tts(self._api_response)
            else:
                logger.info("[混合模式] 无响应内容，重置状态")
                self._reset_state()

        except Exception as e:
            logger.error(f"[混合模式] 处理流失败: {e}")
            self.update_ui_signal.emit("progress", False)
            self._reset_state()

    def _play_audio_url(self, audio_url: str):
        """播放音频URL"""
        try:
            logger.info(f"[混合模式] 准备播放音频: {audio_url}")

            # 检查是否需要添加到清理列表
            should_cleanup = False

            # 如果是URL，下载文件
            if audio_url.startswith("http://") or audio_url.startswith("https://"):
                temp_file = tempfile.mktemp(suffix=".mp3")
                resp = requests.get(audio_url)
                with open(temp_file, 'wb') as f:
                    f.write(resp.content)
                logger.info(f"[混合模式] 音频下载完成: {temp_file}")
                audio_file = temp_file
                should_cleanup = True
            else:
                # 本地文件路径，直接使用
                audio_file = audio_url
                # 服务器生成的文件也需要清理
                if audio_file.startswith(tempfile.gettempdir()):
                    should_cleanup = True

            # 检查文件是否存在
            if not os.path.exists(audio_file):
                logger.error(f"[混合模式] 音频文件不存在: {audio_file}")
                self._reset_state()
                return

            # 播放音频
            self._play_audio(audio_file, "server-audio")

            # 如果需要，添加到清理列表
            if should_cleanup:
                self._audio_files_to_clean.append(audio_file)

        except Exception as e:
            logger.error(f"[混合模式] 播放音频URL失败: {e}")
            tb.print_exc()
            self._reset_state()

    def _convert_tts(self, text: str):
        """转换为语音"""
        tts_id = str(uuid.uuid4())[:8]  # 生成唯一ID
        try:
            logger.info(f"[混合模式] TTS转换开始，文本长度: {len(text)}字")

            # 使用线程安全的TTS包装器，避免asyncio冲突
            from voice.tts_wrapper import generate_speech_safe

            audio_file = generate_speech_safe(
                text=text,
                voice=self._config['tts_voice'],
                response_format="mp3",
                speed=self._config['tts_speed']
            )

            logger.info(f"[混合模式] TTS生成音频文件: {audio_file}")
            self._play_audio(audio_file, tts_id)

        except Exception as e:
            logger.error(f"[混合模式] TTS失败: {e}")
            import traceback
            traceback.print_exc()
            self._reset_state()

    def _play_audio(self, audio_file: str, tts_id: str = "unknown"):
        """播放音频"""
        try:
            logger.info(f"[混合模式] 准备播放音频: {audio_file}")

            # 确保会话仍然活跃
            if not self._session_active:
                logger.warning(f"[混合模式] 会话已结束，跳过播放")
                self._set_state(self.STATE_LISTENING)
                return

            # 立即更新状态为说话中
            self._set_state(self.STATE_SPEAKING)

            # 添加到清理列表
            self._audio_files_to_clean.append(audio_file)

            # 清理旧的播放器
            if self._audio_player and self._audio_player.isRunning():
                logger.warning(f"[混合模式] 旧播放器还在运行，停止它")
                self._audio_player.stop()
                self._audio_player.wait(500)

            # 创建播放器
            self._audio_player = SafeAudioPlayer(audio_file)

            # 保存tts_id供后续使用
            self._current_tts_id = tts_id

            # 使用实例方法连接信号，避免闭包问题
            self._audio_player.play_finished.connect(self._on_play_finished_bridge)
            self._audio_player.play_error.connect(lambda e: logger.error(f"播放错误: {e}"))
            self._audio_player.tts_id = tts_id
            self._audio_player.start()

            logger.info(f"[混合模式] 播放器已启动")

        except Exception as e:
            logger.error(f"[混合模式] 播放失败: {e}")
            self._reset_state()

    def _on_play_finished_bridge(self):
        """播放完成信号桥接"""
        tts_id = getattr(self, '_current_tts_id', 'unknown')
        self.audio_done_signal.emit(tts_id)

    def _on_audio_done(self, tts_id: str = "unknown"):
        """音频播放完成 - 继续监听下一轮对话"""
        try:
            logger.info(f"[混合模式] 音频播放完成: {tts_id}")

            # 清理播放器引用
            if self._audio_player:
                self._audio_player.wait(100)
                self._audio_player = None

            # 重置消息状态
            self._api_response = ""
            self._message_id = None

            # 恢复到监听状态
            if self._is_active and self._session_active and not self._is_stopping:
                self._set_state(self.STATE_LISTENING)
                logger.info(f"[混合模式] 已恢复到监听状态")

                # 确保千问客户端也在监听状态
                if self.voice_client and hasattr(self.voice_client, '_client'):
                    try:
                        if hasattr(self.voice_client._client, 'state_manager'):
                            from voice.voice_realtime.core.state_manager import ConversationState
                            self.voice_client._client.state_manager.transition_to(ConversationState.LISTENING)
                            logger.info("[混合模式] 千问客户端已恢复到监听状态")
                    except Exception as e:
                        logger.warning(f"[混合模式] 无法更新千问客户端状态: {e}")

        except Exception as e:
            logger.error(f"[混合模式] 处理音频完成时出错: {e}")
            self._reset_state()

    def _reset_state(self):
        """重置状态"""
        try:
            # 清理消息状态
            self._api_response = ""
            self._message_id = None

            # 恢复状态
            if self._is_active and self._session_active:
                self._set_state(self.STATE_LISTENING)
            else:
                # 如果服务不活跃，确保更新UI
                self._set_state(self.STATE_IDLE, update_ui=True)

            # 确保进度条停止
            self.update_ui_signal.emit("progress", False)

            logger.info("[混合模式] 状态已重置")
        except Exception as e:
            logger.error(f"[混合模式] 重置状态失败: {e}")

    def _show_info(self, msg: str):
        """显示信息"""
        self.update_ui_signal.emit("info", msg)

    def _show_error(self, msg: str):
        """显示错误"""
        self.update_ui_signal.emit("error", msg)

    def stop_voice(self) -> bool:
        """停止语音服务"""
        try:
            logger.info("[混合模式] 停止服务")

            # 设置主动停止标记，防止误判为超时断开
            self.parent._is_manual_stop = True

            # 先设置所有停止标志，防止任何异步回调触发重连
            with self._state_lock:
                self._is_stopping = True
                self._session_active = False
                self._is_active = False

            # 立即更新状态为IDLE
            self._set_state(self.STATE_IDLE, update_ui=False)

            # 停止播放
            if self._audio_player and self._audio_player.isRunning():
                logger.info("[混合模式] 停止音频播放")
                self._audio_player.stop()
                self._audio_player.wait(1000)

            # 断开连接
            if self.voice_client:
                try:
                    # 先禁用千问客户端的所有回调，防止断开时触发事件
                    if hasattr(self.voice_client, 'set_callbacks'):
                        self.voice_client.set_callbacks(
                            on_user_text=None,
                            on_text=None,
                            on_response_complete=None,
                            on_status=None,
                            on_error=None
                        )
                        logger.info("[混合模式] 已清除所有回调")

                    # 确保auto_reconnect被禁用
                    if hasattr(self.voice_client, '_client'):
                        client = self.voice_client._client

                        # 设置多个断开标志，确保不会重连
                        if hasattr(client, 'config'):
                            client.config['auto_reconnect'] = False
                            logger.info("[混合模式] 已禁用auto_reconnect")

                        # 设置断开标志（必须在disconnect之前设置）
                        if hasattr(client, 'is_disconnecting'):
                            client.is_disconnecting = True

                        # 设置停止标志
                        if hasattr(client, '_stop_requested'):
                            client._stop_requested = True

                        # 破坏_attempt_reconnect方法，防止其被调用
                        if hasattr(client, '_attempt_reconnect'):
                            def blocked_reconnect():
                                return
                            client._attempt_reconnect = blocked_reconnect

                        # 破坏connect方法，防止重连
                        if hasattr(client, 'connect'):
                            def blocked_connect():
                                return
                            client.connect = blocked_connect

                        # 关闭WebSocket连接
                        if hasattr(client, 'ws_manager') and client.ws_manager:
                            if hasattr(client.ws_manager, 'websocket'):
                                try:
                                    client.ws_manager.websocket.close()
                                except:
                                    pass

                            if hasattr(client.ws_manager, 'stop'):
                                client.ws_manager.stop()

                        # 停止所有运行的线程
                        if hasattr(client, 'stop'):
                            client.stop()

                    # 断开连接
                    self.voice_client.disconnect()
                    logger.info("[混合模式] 已断开语音客户端连接")

                except Exception as e:
                    logger.warning(f"[混合模式] 断开连接时出现警告: {e}")
                finally:
                    # 确保清理客户端引用
                    self.voice_client = None

            # 清理文件
            self._cleanup_old_files()

            # 更新UI
            self.parent.voice_realtime_active = False
            self.parent.voice_realtime_state = "idle"
            self.parent.update_voice_button_state("idle")

            # 确保进度条停止
            if hasattr(self.parent, 'progress_widget'):
                self.parent.progress_widget.stop_loading()

            # 只有主动停止时才显示停止消息（不是因为超时断开）
            if not getattr(self.parent, '_is_timeout_disconnect', False):
                self._show_info("🔇 实时语音模式已停止")

            # 清理超时标记（在判断后清理）
            if hasattr(self.parent, '_is_timeout_disconnect'):
                self.parent._is_timeout_disconnect = False

            # 清理主动停止标记
            if hasattr(self.parent, '_is_manual_stop'):
                self.parent._is_manual_stop = False

            # 最后才重置停止标志（确保所有异步操作完成）
            with self._state_lock:
                self._is_stopping = False

            return True

        except Exception as e:
            logger.error(f"[混合模式] 停止失败: {e}")
            self._show_error(f"停止服务失败: {str(e)}")
            # 强制清理
            self.voice_client = None
            self._is_active = False
            self._session_active = False
            self.parent.voice_realtime_active = False
            self.parent.voice_realtime_state = "idle"
            self.parent.update_voice_button_state("idle")
            return False

    def is_active(self) -> bool:
        """检查是否活跃"""
        return self._is_active and self._session_active