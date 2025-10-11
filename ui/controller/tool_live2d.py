from system.config import config
import os
from system.config import config
import logging

# 设置日志
logger = logging.getLogger(__name__)
class Live2DTool():
    def __init__(self, window):
        self.window = window
        self.side=self.window.side
        self.side.mousePressEvent=self.toggle_full_img # 侧栏点击切换聊天/设置
        
    def initialize_live2d(self):
        """初始化Live2D"""
        if self.live2d_enabled and self.live2d_model_path:
            if os.path.exists(self.live2d_model_path):
                self.side.set_live2d_model(self.live2d_model_path) # 调用已有输出逻辑
            else:
                logger.warning(f"⚠️ Live2D模型文件不存在: {self.live2d_model_path}")
        else:
            logger.info("📝 Live2D功能未启用或未配置模型路径")
    
    def on_live2d_model_loaded(self, success):
        """Live2D模型加载状态回调"""
        if success:
            logger.info("✅ Live2D模型已成功加载")
        else:
            logger.info("🔄 已回退到图片模式")
    
    def on_live2d_error(self, error_msg):
        """Live2D错误回调"""
        self.chat_tool.add_user_message("系统", f"❌ Live2D错误: {error_msg}")
    
    def set_live2d_model(self, model_path):
        """设置Live2D模型"""
        if not os.path.exists(model_path):
            self.chat_tool.add_user_message("系统", f"❌ Live2D模型文件不存在: {model_path}")
            return False
        
        self.live2d_model_path = model_path
        self.live2d_enabled = True
        
        self.chat_tool.add_user_message("系统", "🔄 正在切换Live2D模型...")
        success = self.side.set_live2d_model(model_path)
        
        if success:
            self.chat_tool.add_user_message("系统", "✅ Live2D模型切换成功")
        else:
            self.chat_tool.add_user_message("系统", "⚠️ Live2D模型切换失败，已回退到图片模式")
        
        return success
    
    def is_live2d_available(self):
        """检查Live2D是否可用"""
        return self.side.is_live2d_available()

from ..utils.lazy import lazy
@lazy
def live2d():
    return Live2DTool(config.window)