"""voice 包初始化：请从 voice.input.* 与 voice.output.* 导入具体模块"""

# 语音输入相关导入 #
from .input.integration import (
    get_voice_integration,
    start_voice_listening,
    stop_voice_listening,
    is_voice_active
)

# 语音输出相关导入 #
from .output.voice_integration import get_voice_integration as get_tts_integration

__all__ = [
    # 不再提供全局导入，避免依赖冲突
]


