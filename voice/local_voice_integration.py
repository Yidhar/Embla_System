# -*- coding: utf-8 -*-
"""
本地FunASR语音集成
完全离线的语音识别方案
"""

from nagaagent_core.vendors.PyQt5.QtCore import QObject, pyqtSignal, QTimer
import threading
import requests
import json
import asyncio
import pyaudio
import logging
from typing import Optional
from pathlib import Path

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LocalVoiceIntegration(QObject):
    """本地FunASR语音集成管理器"""

    # 定义信号
    update_ui_signal = pyqtSignal(str, str)  # (action, data)

    def __init__(self, parent_widget):
        """
        初始化
        :param parent_widget: 父窗口（ChatWindow）
        """
        super().__init__()
        self.parent = parent_widget
        self.asr_client = None
        self._lock = threading.Lock()
        self._is_recording = False
        self._stop_recording = False
        self._api_response = ""
        self._is_processing = False

        # 从配置读取参数
        from system.config import config

        # TTS配置
        self._tts_voice = getattr(config.voice_realtime, 'tts_voice', 'zh-CN-XiaoyiNeural')
        self._tts_speed = 1.0

        # 音频录制配置
        self.sample_rate = 16000
        self.chunk_size = 1024
        self.record_seconds = getattr(config.voice_realtime, 'record_duration', 10)  # 从配置读取
        self.asr_host = getattr(config.voice_realtime, 'asr_host', 'localhost')
        self.asr_port = getattr(config.voice_realtime, 'asr_port', 5000)

        # 连接信号
        self.update_ui_signal.connect(self._handle_ui_update)

        logger.info("[本地语音] 集成管理器初始化完成")

    def start_voice(self, config_params: dict = None):
        """
        启动本地语音服务
        :param config_params: 配置参数（兼容接口）
        """
        try:
            logger.info("[本地语音] 开始启动服务...")

            # 清理可能存在的超时断开标记
            if hasattr(self.parent, '_is_timeout_disconnect'):
                self.parent._is_timeout_disconnect = False

            # 检查ASR服务是否运行
            asr_url = f"http://{self.asr_host}:{self.asr_port}/health"
            try:
                response = requests.get(asr_url, timeout=2)
                if response.status_code != 200:
                    logger.error("[本地语音] ASR服务未响应")
                    self.parent.add_user_message("系统", f"❌ ASR服务未运行，请先启动: python voice/input/server.py (端口{self.asr_port})")
                    return False
            except requests.exceptions.RequestException:
                logger.error("[本地语音] 无法连接到ASR服务")
                self.parent.add_user_message("系统", f"❌ 无法连接到ASR服务 {asr_url}")
                return False

            # 初始化ASR客户端
            from voice.input.asr_client import ASRClient
            self.asr_client = ASRClient(host=self.asr_host, port=self.asr_port)

            logger.info("[本地语音] ASR客户端创建成功")

            # 更新UI状态
            self.parent.voice_realtime_active = True
            self.parent.voice_realtime_state = "listening"
            self.parent.update_voice_button_state("listening")
            self.parent.add_user_message("系统", "✅ 实时语音模式已启动（本地ASR）")
            self.parent.add_user_message("系统", "💡 再次点击🎤按钮开始录音，录音将在10秒后或再次点击时结束")

            return True

        except ImportError as e:
            logger.error(f"[本地语音] 导入ASR客户端失败: {e}")
            self.parent.add_user_message("系统", "❌ ASR客户端模块未找到，请检查voice/input/目录")
            return False
        except Exception as e:
            logger.error(f"[本地语音] 启动失败: {e}")
            import traceback
            traceback.print_exc()
            self.parent.add_user_message("系统", f"❌ 启动本地语音失败: {str(e)}")
            return False


    def start_recording(self):
        """开始录音（用户点击或VAD触发）"""
        if self._is_recording:
            logger.warning("[本地语音] 已在录音中")
            return

        self._is_recording = True
        self._stop_recording = False

        # 更新UI状态
        self.parent.voice_realtime_state = "recording"
        self.parent.update_voice_button_state("recording")

        # 在后台线程录音
        def record_thread():
            try:
                # 使用PyAudio录音
                p = pyaudio.PyAudio()
                stream = p.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=self.sample_rate,
                    input=True,
                    frames_per_buffer=self.chunk_size
                )

                logger.info("[本地语音] 开始录音...")
                frames = []

                for _ in range(0, int(self.sample_rate / self.chunk_size * self.record_seconds)):
                    if self._stop_recording:
                        break
                    data = stream.read(self.chunk_size)
                    frames.append(data)

                stream.stop_stream()
                stream.close()
                p.terminate()

                if frames and not self._stop_recording:
                    # 将音频数据发送到ASR服务
                    audio_data = b''.join(frames)
                    self._process_audio(audio_data)

            except Exception as e:
                logger.error(f"[本地语音] 录音失败: {e}")
                self.update_ui_signal.emit("error", str(e))
            finally:
                self._is_recording = False

        threading.Thread(target=record_thread, daemon=True).start()

    def stop_recording(self):
        """停止录音"""
        logger.info("[本地语音] 停止录音")
        self._stop_recording = True

    def _process_audio(self, audio_data):
        """处理录音数据"""
        try:
            logger.info("[本地语音] 发送音频到ASR服务...")

            # 发送到ASR服务识别
            import base64
            asr_api_url = f"http://{self.asr_host}:{self.asr_port}/recognize"
            response = requests.post(
                asr_api_url,
                json={
                    "audio": base64.b64encode(audio_data).decode(),
                    "format": "wav",
                    "sample_rate": self.sample_rate
                },
                timeout=10
            )

            if response.status_code == 200:
                result = response.json()
                text = result.get('text', '').strip()

                if text:
                    logger.info(f"[本地语音] 识别结果: {text}")
                    # 通过信号触发UI更新
                    self.update_ui_signal.emit("user_speech_recognized", text)
                else:
                    logger.warning("[本地语音] 识别结果为空")
                    # 通过信号显示错误
                    self.update_ui_signal.emit("error", "⚠️ 未识别到有效语音")
            else:
                logger.error(f"[本地语音] ASR服务返回错误: {response.status_code}")
                # 通过信号显示错误
                self.update_ui_signal.emit("error", f"❌ 识别失败: {response.text}")

        except Exception as e:
            logger.error(f"[本地语音] 处理音频失败: {e}")
            # 通过信号显示错误
            self.update_ui_signal.emit("error", f"❌ 处理音频失败: {str(e)}")

        finally:
            # 通过信号恢复监听状态
            self.update_ui_signal.emit("restore_listening", "")

    def _handle_ui_update(self, action, data):
        """处理UI更新"""
        try:
            if action == "user_speech_recognized":
                self._process_user_speech(data)
            elif action == "error":
                # 显示错误消息
                if data.startswith("❌") or data.startswith("⚠️"):
                    self.parent.add_user_message("系统", data)
                else:
                    self.parent.on_voice_error(data)
            elif action == "api_response_ready":
                self._convert_to_speech(data)
            elif action == "restore_listening":
                # 恢复监听状态
                self.parent.voice_realtime_state = "listening"
                self.parent.update_voice_button_state("listening")
        except Exception as e:
            logger.error(f"[本地语音] UI更新失败: {e}")

    def _process_user_speech(self, text):
        """处理用户语音识别结果"""
        try:
            # 显示用户语音
            self.parent.add_user_message("👤", f"🎤 {text}")

            # 更新状态
            self.parent.voice_realtime_state = "processing"
            self.parent.update_voice_button_state("recording")

            # 显示进度
            if hasattr(self.parent, 'progress_widget'):
                self.parent.progress_widget.set_thinking_mode()

            # 调用API Server处理
            def call_api_server():
                try:
                    api_url = "http://localhost:8000/chat/stream"
                    data = {
                        "message": text,
                        "stream": True,
                        "use_self_game": False
                    }

                    logger.info(f"[本地语音] 发送到API Server: {text}")

                    resp = requests.post(
                        api_url,
                        json=data,
                        timeout=120,
                        stream=True
                    )

                    if resp.status_code == 200:
                        self._handle_api_stream(resp)
                    else:
                        error_msg = f"API调用失败: {resp.text}"
                        logger.error(f"[本地语音] {error_msg}")
                        self.parent.add_user_message("系统", f"❌ {error_msg}")

                except Exception as e:
                    error_msg = f"API调用错误: {str(e)}"
                    logger.error(f"[本地语音] {error_msg}")
                    self.parent.add_user_message("系统", f"❌ {error_msg}")

                finally:
                    if hasattr(self.parent, 'progress_widget'):
                        self.parent.progress_widget.stop_loading()
                    self._is_processing = False
                    self.parent.voice_realtime_state = "listening"
                    self.parent.update_voice_button_state("listening")

            threading.Thread(target=call_api_server, daemon=True).start()

        except Exception as e:
            logger.error(f"[本地语音] 处理语音失败: {e}")
            self._is_processing = False

    def _handle_api_stream(self, resp):
        """处理API流式响应"""
        try:
            self._api_response = ""
            message_started = False
            message_id = None

            for line in resp.iter_lines():
                if line:
                    line_str = line.decode('utf-8')
                    if line_str.startswith('data: '):
                        data_str = line_str[6:]
                        if data_str == '[DONE]':
                            break
                        elif not data_str.startswith('session_id: '):
                            self._api_response += data_str

                            if not message_started:
                                message_id = self.parent.add_user_message("🤖", data_str)
                                self.parent._current_message_id = message_id
                                message_started = True
                            else:
                                self.parent.update_last_message(self._api_response)

            logger.info(f"[本地语音] API响应完成")

            # 转换为语音
            if self._api_response:
                QTimer.singleShot(0, lambda: self.update_ui_signal.emit("api_response_ready", self._api_response))

        except Exception as e:
            logger.error(f"[本地语音] 处理API流失败: {e}")

    def _convert_to_speech(self, text):
        """将文本转换为语音"""
        def convert_and_play():
            try:
                logger.info(f"[本地语音] 开始TTS转换...")

                from voice.output.tts_handler import generate_speech

                # 生成语音文件
                audio_file = generate_speech(
                    text=text,
                    voice=self._tts_voice,
                    response_format="mp3",
                    speed=self._tts_speed
                )

                logger.info(f"[本地语音] TTS生成完成: {audio_file}")

                # 播放音频
                self._play_audio_file(audio_file)

                # 清理临时文件
                Path(audio_file).unlink(missing_ok=True)

            except Exception as e:
                logger.error(f"[本地语音] TTS转换失败: {e}")

        threading.Thread(target=convert_and_play, daemon=True).start()

    def _play_audio_file(self, audio_file):
        """播放音频文件"""
        try:
            logger.info(f"[本地语音] 播放音频: {audio_file}")

            # 更新状态
            self.parent.voice_realtime_state = "ai_speaking"
            self.parent.update_voice_button_state("ai_speaking")

            # 使用pygame播放
            try:
                import pygame

                # 尝试多种初始化参数
                init_success = False

                # 尝试1: 默认参数
                try:
                    pygame.mixer.quit()  # 先清理任何已存在的mixer
                    pygame.mixer.init()
                    init_success = True
                    logger.info("[本地语音] pygame默认初始化成功")
                except pygame.error:
                    logger.warning("[本地语音] pygame默认初始化失败，尝试备用参数")

                # 尝试2: 指定参数（44100Hz, 16位, 立体声）
                if not init_success:
                    try:
                        pygame.mixer.quit()
                        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
                        init_success = True
                        logger.info("[本地语音] pygame使用44100Hz初始化成功")
                    except pygame.error:
                        logger.warning("[本地语音] pygame 44100Hz初始化失败")

                # 尝试3: 降低采样率（22050Hz）
                if not init_success:
                    try:
                        pygame.mixer.quit()
                        pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=1024)
                        init_success = True
                        logger.info("[本地语音] pygame使用22050Hz初始化成功")
                    except pygame.error:
                        logger.warning("[本地语音] pygame 22050Hz初始化失败")

                # 尝试4: 单声道配置
                if not init_success:
                    try:
                        pygame.mixer.quit()
                        pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=1024)
                        init_success = True
                        logger.info("[本地语音] pygame使用单声道初始化成功")
                    except pygame.error as e:
                        logger.error(f"[本地语音] pygame所有初始化尝试均失败: {e}")
                        raise

                # 如果初始化成功，播放音频
                if init_success:
                    pygame.mixer.music.load(audio_file)
                    pygame.mixer.music.play()

                    while pygame.mixer.music.get_busy():
                        pygame.time.Clock().tick(10)

                    pygame.mixer.quit()
                    logger.info("[本地语音] 播放完成")
                else:
                    raise Exception("无法初始化pygame音频")

            except (ImportError, Exception) as e:
                if isinstance(e, ImportError):
                    logger.warning("[本地语音] pygame未安装，使用系统播放器")
                else:
                    logger.warning(f"[本地语音] pygame播放失败: {e}，使用系统播放器")
                import platform
                import subprocess

                system = platform.system()
                if system == "Windows":
                    import winsound
                    winsound.PlaySound(audio_file, winsound.SND_FILENAME)
                elif system == "Darwin":
                    subprocess.run(["afplay", audio_file], check=False)
                else:
                    subprocess.run(["aplay", audio_file], check=False)

            # 恢复状态
            self.parent.voice_realtime_state = "listening"
            self.parent.update_voice_button_state("listening")

        except Exception as e:
            logger.error(f"[本地语音] 播放失败: {e}")
            self.parent.voice_realtime_state = "listening"
            self.parent.update_voice_button_state("listening")

    def stop_voice(self):
        """停止语音服务"""
        try:
            logger.info("[本地语音] 停止服务...")

            self._stop_recording = True
            self.asr_client = None

            self.parent.voice_realtime_active = False
            self.parent.voice_realtime_state = "idle"
            self.parent.update_voice_button_state("idle")

            # 只有不是超时断开时才显示停止消息
            if not getattr(self.parent, '_is_timeout_disconnect', False):
                self.parent.add_user_message("系统", "🔇 实时语音模式已停止")

            # 清理超时标记（在判断后清理）
            if hasattr(self.parent, '_is_timeout_disconnect'):
                self.parent._is_timeout_disconnect = False

            return True

        except Exception as e:
            logger.error(f"[本地语音] 停止失败: {e}")
            return False

    def is_active(self):
        """检查是否活跃"""
        return self.asr_client is not None

    def toggle_recording(self):
        """切换录音状态（用于按钮点击）"""
        if self._is_recording:
            self.stop_recording()
        else:
            self.start_recording()