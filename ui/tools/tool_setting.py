from system.config import config
import os
from system.config import config
import logging

# 设置日志
logger = logging.getLogger(__name__)
class SettingTool():
    def __init__(self, window):
        self.window = window
        
    
    def on_settings_changed(self, setting_key, value):
        """处理设置变化"""
        logger.debug(f"设置变化: {setting_key} = {value}")
        
        # 透明度设置将在保存时统一应用，避免动画卡顿
        if setting_key in ("all", "ui.bg_alpha", "ui.window_bg_alpha"):  # UI透明度变化 #
            # 保存时应用透明度设置
            self.apply_opacity_from_config()
            return
        if setting_key in ("system.stream_mode", "STREAM_MODE"):
            self.streaming_mode = value if setting_key == "system.stream_mode" else value  # 兼容新旧键名 #
            self.chat_tool.add_user_message("系统", f"● 流式模式已{'启用' if self.streaming_mode else '禁用'}")
        elif setting_key in ("system.debug", "DEBUG"):
            self.chat_tool.add_user_message("系统", f"● 调试模式已{'启用' if value else '禁用'}")
        
        # 发送设置变化信号给其他组件
        # 这里可以根据需要添加更多处理逻辑

    def apply_opacity_from_config(self):
        """从配置中应用UI透明度(聊天区/输入框/侧栏/窗口)"""
        # 更新全局变量，保持其它逻辑一致 #
        global BG_ALPHA, WINDOW_BG_ALPHA
        # 直接读取配置值，避免函数调用开销
        BG_ALPHA = config.ui.bg_alpha
        WINDOW_BG_ALPHA = config.ui.window_bg_alpha

        # 计算alpha #
        alpha_px = int(BG_ALPHA * 255)

        # 更新聊天区域背景 - 现在使用透明背景，对话框有自己的背景
        self.chat_content.setStyleSheet(f"""
            QWidget {{
                background: transparent;
                border: none;
            }}
        """)

        # 更新输入框背景 #
        fontfam, fontsize = 'Lucida Console', 16
        self.input.setStyleSheet(f"""
            QTextEdit {{
                background: rgba(17,17,17,{alpha_px});
                color: #fff;
                border-radius: 15px;
                border: 1px solid rgba(255, 255, 255, 50);
                font: {fontsize}pt '{fontfam}';
                padding: 8px;
            }}
        """)

        # 更新侧栏背景 #
        if hasattr(self, 'side') and isinstance(self.side, QWidget):
            try:
                self.side.set_background_alpha(alpha_px)
            except Exception:
                pass

        # 更新主窗口背景 #
        self.set_window_background_alpha(WINDOW_BG_ALPHA)


    def set_window_background_alpha(self, alpha):
        """设置整个窗口的背景透明度
        Args:
            alpha: 透明度值，可以是:
                   - 0-255的整数 (PyQt原生格式)
                   - 0.0-1.0的浮点数 (百分比格式)
        """
        global WINDOW_BG_ALPHA
        
        # 处理不同格式的输入
        if isinstance(alpha, float) and 0.0 <= alpha <= 1.0:
            # 浮点数格式：0.0-1.0 转换为 0-255
            WINDOW_BG_ALPHA = int(alpha * 255)
        elif isinstance(alpha, int) and 0 <= alpha <= 255:
            # 整数格式：0-255
            WINDOW_BG_ALPHA = alpha
        else:
            logger.warning(f"警告：无效的透明度值 {alpha}，应为0-255的整数或0.0-1.0的浮点数")
            return
        
        # 更新CSS样式表
        self.setStyleSheet(f"""
            ChatWindow {{
                background: rgba(25, 25, 25, {WINDOW_BG_ALPHA});
                border-radius: 20px;
                border: 1px solid rgba(255, 255, 255, 30);
            }}
        """)
    
        # 触发重绘
        self.update()

        logger.info(f"✅ 窗口背景透明度已设置为: {WINDOW_BG_ALPHA}/255 ({WINDOW_BG_ALPHA/255*100:.1f}%不透明度)")


    

from ..utils.lazy import lazy
tool = None
@lazy
def setting():
    if tool is None:
        tool = SettingTool(config.window)
    return tool