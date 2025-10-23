from system.config import config
import os
from system.config import config, logger
from . import chat

class Live2DTool():
    def __init__(self, window):
        self.window = window
        self.side = self.window.side

    def toggle_live2d(self):
        """切换Live2D/图片显示模式"""
        if not self.side.is_live2d_available():
            chat.add_system_message("Live2D模块未安装，无法启用")
            return False

        current_mode = self.side.get_display_mode()

        if current_mode == 'live2d':
            # 切换到图片模式
            self.side.fallback_to_image_mode()
            config.live2d.enabled = False
            chat.add_system_message("已切换到图片模式")
            logger.info("切换到图片模式")
            return False
        else:
            # 切换到Live2D模式
            self.side.live2d_enabled = True
            self.side.initialize_live2d()

            if self.side.get_display_mode() == 'live2d':
                config.live2d.enabled = True
                chat.add_system_message("已切换到Live2D模式")
                logger.debug("切换到Live2D模式")  # 改为DEBUG级别，减少启动时日志噪音
                return True
            else:
                chat.add_system_message("Live2D加载失败，请检查模型文件")
                logger.warning("Live2D加载失败")
                return False

    def reload_live2d(self):
        """重新加载Live2D模型"""
        if self.side.get_display_mode() != 'live2d':
            chat.add_system_message("请先切换到Live2D模式")
            return

        # 重新初始化
        self.side.initialize_live2d()
        chat.add_system_message("Live2D模型已重新加载")
        logger.debug("Live2D模型重新加载")  # 改为DEBUG级别，减少启动时日志噪音

    def set_live2d_scale(self, scale_factor):
        """设置Live2D缩放比例"""
        if not self.side.live2d_widget:
            chat.add_system_message("Live2D未加载")
            return

        scale_factor = max(0.5, min(3.0, scale_factor))
        self.side.live2d_widget.set_scale_factor(scale_factor)
        config.live2d.scale_factor = scale_factor
        chat.add_system_message(f"Live2D缩放设置为: {scale_factor:.1f}x")
        logger.debug(f"Live2D缩放: {scale_factor}")  # 改为DEBUG级别，减少启动时日志噪音

    def trigger_live2d_emotion(self, emotion):
        """触发Live2D情绪动画"""
        if self.side.live2d_widget and self.side.live2d_widget.is_model_loaded():
            self.side.live2d_widget.set_emotion(emotion)
            logger.debug(f"触发Live2D情绪: {emotion}")  # 改为DEBUG级别，减少启动时日志噪音

    def trigger_live2d_motion(self, motion_group='idle', index=0):
        """触发Live2D动作"""
        if self.side.live2d_widget and self.side.live2d_widget.is_model_loaded():
            self.side.live2d_widget.trigger_motion(motion_group, index)
            logger.debug(f"触发Live2D动作: {motion_group}[{index}]")  # 改为DEBUG级别，减少启动时日志噪音

    def on_live2d_model_loaded(self, success):
        """Live2D模型加载状态回调 - 增强版"""
        if success:
            logger.debug("Live2D模型已成功加载")  # 改为DEBUG级别，减少启动时日志噪音
            # 可以在这里添加一些初始化动作
            if self.side.live2d_widget:
                # 触发一个欢迎动作
                self.side.live2d_widget.trigger_motion("idle", 0)
        else:
            logger.info("已回退到图片模式")

    def on_live2d_error(self, error_msg):
        """Live2D错误回调 - 增强版"""
        chat.add_system_message(f"Live2D错误: {error_msg}")
        logger.error(f"Live2D错误: {error_msg}")
        # 自动回退到图片模式
        self.side.fallback_to_image_mode()

    def get_live2d_status(self):
        """获取Live2D状态信息"""
        status = {
            'available': self.side.is_live2d_available(),
            'mode': self.side.get_display_mode(),
            'model_loaded': False
        }

        if self.side.live2d_widget:
            status['model_loaded'] = self.side.live2d_widget.is_model_loaded()

        return status

from ..utils.lazy import lazy
@lazy
def live2d():
    return Live2DTool(config.window)