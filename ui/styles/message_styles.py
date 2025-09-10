# message_styles.py # 消息渲染器样式配置

from system.config import config

# 使用统一配置系统
BG_ALPHA = config.ui.bg_alpha

class MessageStyles:
    """消息渲染器样式配置类"""
    
    # 基础对话框样式
    @staticmethod
    def get_dialog_style():
        """获取基础对话框样式"""
        return f"""
            QFrame {{
                background: rgba(17,17,17,{int(BG_ALPHA*255)});
                border-radius: 0px;
                border: 1px solid rgba(255, 255, 255, 50);
                padding: 10px;
                margin: 5px 0px;
            }}
        """
    
    # 用户名标签样式
    @staticmethod
    def get_name_label_style():
        """获取用户名标签样式"""
        return """
            QLabel {
                color: #fff;
                font-size: 12pt;
                font-family: 'Lucida Console';
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
        """
    
    # 内容容器样式
    @staticmethod
    def get_content_widget_style():
        """获取内容容器样式"""
        return """
            QWidget {
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
        """
    
    # 内容文本样式（QTextEdit）
    @staticmethod
    def get_content_text_style():
        """获取内容文本样式（支持Markdown）"""
        return """
            QTextEdit {
                color: #fff;
                font-size: 16pt;
                font-family: 'Lucida Console';
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
                line-height: 1.4;
            }
            QTextEdit QScrollBar:vertical {
                background: rgba(255, 255, 255, 20);
                width: 8px;
                border-radius: 4px;
            }
            QTextEdit QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 60);
                border-radius: 4px;
                min-height: 20px;
            }
            QTextEdit QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 80);
            }
        """
    
    # 工具调用标签样式
    @staticmethod
    def get_tool_call_label_style():
        """获取工具调用标签样式"""
        return """
            QLabel {
                color: #888;
                font-size: 14pt;
                font-family: 'Lucida Console';
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
        """
    
    # 工具调用内容标签样式
    @staticmethod
    def get_tool_call_content_style():
        """获取工具调用内容标签样式"""
        return """
            QLabel {
                color: #888;
                font-size: 16pt;
                font-family: 'Lucida Console';
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
                line-height: 1.4;
            }
        """
    
    # 展开按钮样式
    @staticmethod
    def get_expand_button_style():
        """获取展开按钮样式"""
        return """
            QPushButton {
                background: rgba(100, 100, 100, 100);
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 12px;
                color: #888;
                font-size: 10pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(120, 120, 120, 150);
                border: 1px solid rgba(255, 255, 255, 50);
            }
            QPushButton:pressed {
                background: rgba(80, 80, 80, 200);
            }
        """
    
    # 嵌套容器样式
    @staticmethod
    def get_nested_container_style():
        """获取嵌套容器样式"""
        return """
            QWidget {
                background: rgba(25, 25, 25, 150);
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 5px;
                margin-top: 5px;
            }
        """
    
    # 嵌套标题样式
    @staticmethod
    def get_nested_title_style():
        """获取嵌套标题样式"""
        return """
            QLabel {
                color: #aaa;
                font-size: 12pt;
                font-family: 'Lucida Console';
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
        """
    
    # 嵌套内容样式
    @staticmethod
    def get_nested_content_style():
        """获取嵌套内容样式"""
        return """
            QLabel {
                color: #888;
                font-size: 14pt;
                font-family: 'Lucida Console';
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
                line-height: 1.3;
            }
        """


class LayoutConfig:
    """布局配置类"""
    
    # 主布局配置
    MAIN_LAYOUT_MARGINS = (10, 10, 10, 10)
    MAIN_LAYOUT_SPACING = 5
    
    # 内容布局配置
    CONTENT_LAYOUT_MARGINS = (0, 0, 0, 0)
    CONTENT_LAYOUT_SPACING = 0
    
    # 水平布局配置（用于展开按钮）
    HORIZONTAL_LAYOUT_MARGINS = (0, 0, 0, 0)
    HORIZONTAL_LAYOUT_SPACING = 10
    
    # 嵌套布局配置
    NESTED_LAYOUT_MARGINS = (10, 10, 10, 10)
    NESTED_LAYOUT_SPACING = 5
    
    # 尺寸配置
    EXPAND_BUTTON_SIZE = (24, 24)
    NESTED_CONTAINER_INITIAL_HEIGHT = 0
    NESTED_CONTAINER_EXPANDED_HEIGHT = 200


class MarkdownStyles:
    """Markdown渲染样式配置类"""
    
    @staticmethod
    def get_pygments_css():
        """获取Pygments代码高亮CSS样式"""
        from pygments.formatters import HtmlFormatter
        
        formatter = HtmlFormatter(
            style='monokai',
            cssclass='highlight',
            noclasses=False,
            linenos=False,
            wrapcode=True
        )
        return formatter.get_style_defs('.highlight')
    
    @staticmethod
    def get_markdown_styles():
        """获取完整的Markdown样式"""
        pygments_css = MarkdownStyles.get_pygments_css()
        
        return f"""
            body {{
                font-family: 'Lucida Console', monospace;
                color: #fff;
                background: transparent;
                margin: 0;
                padding: 0;
                line-height: 1.4;
            }}
            
            /* Pygments代码高亮样式 */
            {pygments_css}
            
            /* 自定义代码块样式 */
            .highlight {{
                background: #272822 !important;
                border: 1px solid rgba(255,255,255,0.2);
                border-radius: 5px;
                margin: 5px 0;
                overflow-x: auto;
            }}
            
            .highlight pre {{
                background: transparent !important;
                padding: 10px;
                margin: 0;
                border: none;
                border-radius: 0;
            }}
            
            .highlight code {{
                background: transparent !important;
                padding: 0;
                border: none;
                font-family: 'Lucida Console', monospace;
                font-size: 22px;
            }}
            
            /* 普通代码块样式（非高亮） */
            pre:not(.highlight) {{
                background: rgba(0,0,0,0.3);
                padding: 10px;
                border-radius: 5px;
                overflow-x: auto;
                border: 1px solid rgba(255,255,255,0.2);
                margin: 5px 0;
            }}
            
            code:not(.highlight code) {{
                background: rgba(0,0,0,0.2);
                padding: 2px 4px;
                border-radius: 3px;
                font-family: 'Lucida Console', monospace;
                font-size: 22px;
            }}
            
            pre code:not(.highlight code) {{
                background: transparent;
                padding: 0;
            }}
            
            table {{
                border-collapse: collapse;
                width: 100%;
                margin: 10px 0;
            }}
            th, td {{
                border: 1px solid rgba(255,255,255,0.3);
                padding: 8px;
                text-align: left;
            }}
            th {{
                background: rgba(255,255,255,0.1);
            }}
            blockquote {{
                border-left: 4px solid rgba(255,255,255,0.5);
                margin: 10px 0;
                padding-left: 15px;
                color: rgba(255,255,255,0.8);
            }}
            h1, h2, h3, h4, h5, h6 {{
                color: #fff;
                margin: 10px 0 5px 0;
            }}
            a {{
                color: #4A9EFF;
                text-decoration: none;
            }}
            a:hover {{
                text-decoration: underline;
            }}
            ul, ol {{
                margin: 10px 0;
                padding-left: 20px;
            }}
            li {{
                margin: 3px 0;
            }}
        """
