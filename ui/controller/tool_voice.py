from system.config import config, logger
from . import chat
class VoiceTool():
    def __init__(self, window):
        self.window = window

        # 实时语音相关
        self.voice_realtime_client = None  # 语音客户端（废弃，使用线程安全版本）
        self.voice_realtime_active = False  # 是否激活
        self.voice_realtime_state = "idle"  # idle/listening/recording/ai_speaking
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


from ..utils.lazy import lazy
@lazy
def voice():
    return VoiceTool(config.window)
