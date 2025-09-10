"""voice 包初始化：请从 voice.input.* 与 voice.output.* 导入具体模块"""

# 移除全局导入，避免语音输入模块的onnxruntime依赖影响语音输出
# 用户需要时直接从具体模块导入：
# from voice.input.integration import get_voice_integration
# from voice.output.voice_integration import get_voice_integration

__all__ = [
    # 不再提供全局导入，避免依赖冲突
]


