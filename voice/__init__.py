"""voice 包初始化：请从 voice.input.* 与 voice.output.* 导入具体模块"""

# 移除全局导入，避免语音输入模块的onnxruntime依赖影响语音输出
# 用户需要时直接从具体模块导入：
# from voice.input.integration import get_voice_integration
# from voice.output.voice_integration import get_voice_integration

# 导出线程安全的语音集成组件
from .voice_thread_safe_simple import ThreadSafeVoiceIntegration

__all__ = [
    'ThreadSafeVoiceIntegration',
    # 不再提供其他全局导入，避免依赖冲突
]


