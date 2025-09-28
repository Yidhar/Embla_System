"""
按钮工厂类
提供统一的按钮创建接口
"""

from PyQt5.QtWidgets import QPushButton  # 直接依赖 #
from .button_styles import BUTTON_CONFIGS, DOCUMENT_ACTION_BUTTON_STYLE, CANCEL_BUTTON_STYLE


class ButtonFactory:
    """按钮工厂类"""
    
    @staticmethod
    def create_action_button(button_type: str, parent=None) -> QPushButton:
        """
        创建操作按钮（上传文档、心智云图等）
        
        Args:
            button_type: 按钮类型 ("upload" 或 "mind_map")
            parent: 父组件
            
        Returns:
            QPushButton: 配置好的按钮
        """
        if button_type not in BUTTON_CONFIGS:
            raise ValueError(f"不支持的按钮类型: {button_type}")
            
        config = BUTTON_CONFIGS[button_type]
        
        # 创建按钮
        button = QPushButton(config["icon"], parent)
        
        # 设置大小
        width, height = config["size"]
        button.setFixedSize(width, height)
        
        # 设置样式
        button.setStyleSheet(config["style"])
        
        # 设置工具提示
        button.setToolTip(config["tooltip"])
        
        return button
    
    @staticmethod
    def create_document_action_button(text: str, parent=None) -> QPushButton:
        """
        创建文档操作按钮
        
        Args:
            text: 按钮文本
            parent: 父组件
            
        Returns:
            QPushButton: 配置好的按钮
        """
        button = QPushButton(text, parent)
        button.setFixedHeight(50)
        button.setStyleSheet(DOCUMENT_ACTION_BUTTON_STYLE)
        return button
    
    @staticmethod
    def create_cancel_button(text: str = "取消", parent=None) -> QPushButton:
        """
        创建取消按钮
        
        Args:
            text: 按钮文本
            parent: 父组件
            
        Returns:
            QPushButton: 配置好的按钮
        """
        button = QPushButton(text, parent)
        button.setFixedHeight(40)
        button.setStyleSheet(CANCEL_BUTTON_STYLE)
        return button 