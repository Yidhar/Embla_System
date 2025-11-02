from system.config import config, logger
from . import chat
from nagaagent_core.vendors.PyQt5.QtCore import QTimer
import random

class VoiceTool():
    def __init__(self, window):
        self.window = window
        self.chat_tool = chat  # 添加chat_tool引用

        # 实时语音相关
        self.voice_realtime_client = None  # 语音客户端（废弃，使用线程安全版本）
        self.voice_realtime_active = False  # 是否激活
        self.voice_realtime_state = "idle"  # idle/listening/recording/ai_speaking
        
        # Live2D嘴部同步相关
        self._lip_sync_timer = None  # 嘴部同步定时器
        self._lip_sync_active = False  # 嘴部同步是否激活
        
        self._init_voice()
        
    def _init_voice(self):
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
                chat.add_user_message("系统", "❌ 请先在设置中配置语音服务API密钥")
                return

            # 使用统一语音管理器启动
            from voice.input.unified_voice_manager import VoiceMode

            # 确定要使用的模式
            mode = self.default_voice_mode

            success = self.voice_integration.start_voice(mode=mode)

            if not success:
                chat.add_user_message("系统", "❌ 语音服务启动失败，请检查配置和服务状态")
            else:
                # 设置激活标志
                self.voice_realtime_active = True

        except Exception as e:
            chat.add_user_message("系统", f"❌ 启动语音服务失败: {str(e)}")

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
                chat.add_user_message("系统", "⚠️ 语音服务未在运行")

        except Exception as e:
            self.voice_realtime_active = False  # 确保异常时也设置为False
            chat.add_user_message("系统", f"❌ 停止语音服务失败: {str(e)}")

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

    # ========== 语音回调方法 ==========
    def on_voice_user_text(self, text: str):
        """处理用户语音输入文本"""
        try:
            # 显示用户说的话
            self.chat_tool.add_user_message("你", text)
        except Exception as e:
            logger.error(f"处理用户语音文本失败: {e}")

    def on_voice_ai_text(self, text: str):
        """处理AI响应文本（流式）"""
        try:
            # 流式显示AI响应 - 使用append_response_chunk方法
            self.chat_tool.append_response_chunk(text)
            # 注意：Live2D嘴部同步现在由音频播放循环驱动，不在这里处理
        except Exception as e:
            logger.error(f"处理AI语音文本失败: {e}")

    def on_voice_response_complete(self):
        """AI响应完成"""
        try:
            # 完成当前消息显示 - 使用finalize_streaming_response方法
            self.chat_tool.finalize_streaming_response()
            # 注意：Live2D嘴部同步现在由音频播放循环驱动，不在这里处理
        except Exception as e:
            logger.error(f"完成AI响应失败: {e}")

    def on_voice_status(self, status: str):
        """处理语音状态变化"""
        try:
            logger.info(f"语音状态: {status}")
            
            # 更新状态
            self.voice_realtime_state = status
            
            # 根据状态更新UI
            if status == "listening":
                self.update_voice_button_state("listening")
            elif status == "recording":
                self.update_voice_button_state("recording")
            elif status == "ai_speaking":
                self.update_voice_button_state("ai_speaking")
            elif status == "disconnected":
                # 检查是否是超时断开
                if not getattr(self, '_is_manual_stop', False):
                    self._is_timeout_disconnect = True
                    self.chat_tool.add_user_message("系统", "⚠️ 语音连接已断开（超时或网络问题）")
                
                self.voice_realtime_active = False
                self.update_voice_button_state("idle")
            elif status == "idle":
                self.update_voice_button_state("idle")
                
        except Exception as e:
            logger.error(f"处理语音状态失败: {e}")

    def on_voice_error(self, error: str):
        """处理语音错误"""
        try:
            logger.error(f"语音错误: {error}")
            self.chat_tool.add_user_message("系统", f"❌ 语音错误: {error}")
            
            # 错误时停止语音服务
            self.voice_realtime_active = False
            self.update_voice_button_state("idle")
        except Exception as e:
            logger.error(f"处理语音错误回调失败: {e}")

    def update_voice_button_state(self, state: str):
        """更新语音按钮状态"""
        try:
            # 更新状态
            self.voice_realtime_state = state
            
            # 如果window有对应的方法，调用它
            if hasattr(self.window, 'update_voice_button_state'):
                self.window.update_voice_button_state(state)
            else:
                # 简单的状态显示
                status_text = {
                    "idle": "空闲",
                    "listening": "监听中...",
                    "recording": "录音中...",
                    "ai_speaking": "AI说话中..."
                }.get(state, state)
                logger.info(f"语音按钮状态: {status_text}")
        except Exception as e:
            logger.error(f"更新语音按钮状态失败: {e}")

    # ========== Live2D嘴部同步辅助方法 ==========
    # 注意：Live2D嘴部同步现在由音频播放循环直接驱动
    # 相关实现在 voice/input/voice_realtime/adapters/qwen/client.py 中
    # 这里保留的变量仅用于兼容性


from ..utils.lazy import lazy
@lazy
def voice():
    return VoiceTool(config.window)
