from nagaagent_core.vendors.PyQt5.QtWidgets import QApplication, QWidget, QTextEdit, QSizePolicy, QHBoxLayout, QLabel, QVBoxLayout, QStackedLayout, QPushButton, QStackedWidget, QDesktopWidget, QScrollArea, QSplitter, QFileDialog, QMessageBox, QFrame  # 统一入口 #
from nagaagent_core.vendors.PyQt5.QtCore import Qt, QRect, QParallelAnimationGroup, QPropertyAnimation, QEasingCurve, QTimer, QThread, pyqtSignal, QObject  # 统一入口 #
from nagaagent_core.vendors.PyQt5.QtGui import QColor, QPainter, QBrush, QFont, QPen  # 统一入口 #zv
from .styles.button_factory import ButtonFactory
from pathlib import Path
from system.config import config, AI_NAME
import os
import requests
import logging

logger = logging.getLogger(__name__)


class DocumentTool():
    def __init__(self, window):
        self.window = window
        self.progress_widget = window.progress_widget
        self.add_user_message = window.add_user_message
    def upload_document(self):
        """上传文档功能"""
        try:
            # 打开文件选择对话框
            file_path, _ = QFileDialog.getOpenFileName(
                self.window,
                "选择要上传的文档",
                "",
                "支持的文档格式 (*.docx *.txt *.md);;Word文档 (*.docx);;文本文件 (*.txt);;Markdown文件 (*.md);;所有文件 (*)"
            )
            
            if not file_path:
                return  # 用户取消选择
            
            # 检查文件格式
            file_ext = Path(file_path).suffix.lower()
            supported_formats = ['.docx', '.txt', '.md']
            
            if file_ext not in supported_formats:
                QMessageBox.warning(self.window, "格式不支持", 
                                   f"不支持的文件格式: {file_ext}\n\n支持的格式: {', '.join(supported_formats)}")
                return
            
            # 检查文件大小 (限制为10MB)
            file_size = os.path.getsize(file_path)
            if file_size > 10 * 1024 * 1024:  # 10MB
                QMessageBox.warning(self.window, "文件过大", "文件大小不能超过10MB")
                return
            
            # 上传文件到API服务器
            self.upload_file_to_server(file_path)
            
        except Exception as e:
            QMessageBox.critical(self.window, "上传错误", f"文档上传失败:\n{str(e)}")
    
    def upload_file_to_server(self, file_path):
        """将文件上传到API服务器"""
        try:
            # 显示上传进度
            self.add_user_message("系统", f"📤 正在上传文档: {Path(file_path).name}")
            self.progress_widget.set_thinking_mode()
            self.progress_widget.status_label.setText("上传文档中...")
            
            # 准备上传数据
            # 使用配置中的API服务器地址和端口
            api_url = f"http://{config.api_server.host}:{config.api_server.port}/upload/document"
            
            with open(file_path, 'rb') as f:
                files = {'file': (Path(file_path).name, f, 'application/octet-stream')}
                data = {'description': f'通过NAGA聊天界面上传的文档'}
                
                # 发送上传请求
                response = requests.post(api_url, files=files, data=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                self.progress_widget.stop_loading()
                self.add_user_message("系统", f"✅ 文档上传成功: {result['filename']}")
                
                # 询问用户想要进行什么操作
                self.show_document_options(result['file_path'], result['filename'])
            else:
                self.progress_widget.stop_loading()
                self.add_user_message("系统", f"❌ 上传失败: {response.text}")
                
        except requests.exceptions.ConnectionError:
            self.progress_widget.stop_loading()
            self.add_user_message("系统", "❌ 无法连接到API服务器，请确保服务器正在运行")
        except Exception as e:
            self.progress_widget.stop_loading()
            self.add_user_message("系统", f"❌ 上传失败: {str(e)}")
    
    def show_document_options(self, file_path, filename):
        """显示文档处理选项"""
        from nagaagent_core.vendors.PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QFrame, QPushButton  # 统一入口 #
        from nagaagent_core.vendors.PyQt5.QtCore import Qt  # 统一入口 #
        from nagaagent_core.vendors.PyQt5.QtGui import QFont  # 统一入口 #
        
        dialog = QDialog(self.window)
        dialog.setWindowTitle("文档处理选项")
        dialog.setFixedSize(650, 480)
        # 隐藏标题栏的图标按钮
        dialog.setWindowFlags(Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        dialog.setStyleSheet("""
            QDialog {
                background-color: white;
                border: 2px solid #ddd;
                border-radius: 10px;
            }
        """)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(20)
        
        # 标题
        title_label = QLabel("文档上传成功")
        title_font = QFont("Microsoft YaHei", 16, QFont.Bold)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #2c3e50; margin-bottom: 25px; padding: 15px; min-height: 40px;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # 文件信息
        info_label = QLabel(f"文件名: {filename}")
        info_label.setStyleSheet("color: #34495e; font-size: 14px; padding: 10px;")
        layout.addWidget(info_label)
        
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #bdc3c7;")
        layout.addWidget(line)
        
        # 操作按钮
        actions = [
            ("📖 读取内容", "read", "读取文档的完整内容"),
            ("🔍 分析文档", "analyze", "分析文档结构和内容"),
            ("📝 生成摘要", "summarize", "生成文档的简洁摘要")
        ]
        
        for btn_text, action, description in actions:
            btn = ButtonFactory.create_document_action_button(btn_text)
            
            # 添加描述标签
            desc_label = QLabel(description)
            desc_label.setStyleSheet("color: #7f8c8d; font-size: 12px; margin-bottom: 10px;")
            layout.addWidget(desc_label)
            layout.addWidget(btn)
            
            # 连接按钮事件
            btn.clicked.connect(lambda checked, f=file_path, a=action, d=dialog: self.process_document(f, a, d))
        
        # 取消按钮
        cancel_btn = ButtonFactory.create_cancel_button()
        cancel_btn.clicked.connect(dialog.close)
        layout.addWidget(cancel_btn)
        
        dialog.exec_()
    
    def process_document(self, file_path, action, dialog=None):
        """处理文档"""
        if dialog:
            dialog.close()
        
        try:
            self.add_user_message("系统", f"🔄 正在处理文档: {Path(file_path).name}")
            self.progress_widget.set_thinking_mode()
            self.progress_widget.status_label.setText("处理文档中...")
            
            # 调用API处理文档
            # 使用配置中的API服务器地址和端口
            api_url = f"http://{config.api_server.host}:{config.api_server.port}/document/process"
            data = {
                "file_path": file_path,
                "action": action
            }
            
            response = requests.post(api_url, json=data, timeout=60)
            
            if response.status_code == 200:
                result = response.json()
                self.progress_widget.stop_loading()
                
                
                if action == "read":
                    self.add_user_message(AI_NAME, f"📖 文档内容:\n\n{result['content']}")
                elif action == "analyze":
                    self.add_user_message(AI_NAME, f"🔍 文档分析:\n\n{result['analysis']}")
                elif action == "summarize":
                    self.add_user_message(AI_NAME, f"📝 文档摘要:\n\n{result['summary']}")
            else:
                self.progress_widget.stop_loading()
                self.add_user_message("系统", f"❌ 文档处理失败: {response.text}")
                
        except requests.exceptions.ConnectionError:
            self.progress_widget.stop_loading()
            self.add_user_message("系统", "❌ 无法连接到API服务器，请确保服务器正在运行")
        except Exception as e:
            self.progress_widget.stop_loading()
            self.add_user_message("系统", f"❌ 文档处理失败: {str(e)}")
    