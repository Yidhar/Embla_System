from system.config import config
import os
from system.config import config, logger
from . import chat
class Live2DTool():
    def __init__(self, window):
        self.window = window
        self.side=self.window.side

    def on_live2d_model_loaded(self, success):
        """Live2D模型加载状态回调"""
        if success:
            logger.info("✅ Live2D模型已成功加载")
        else:
            logger.info("🔄 已回退到图片模式")
    
    def on_live2d_error(self, error_msg):
        """Live2D错误回调"""
        chat.add_user_message("系统", f"❌ Live2D错误: {error_msg}")

from ..utils.lazy import lazy
@lazy
def live2d():
    return Live2DTool(config.window)