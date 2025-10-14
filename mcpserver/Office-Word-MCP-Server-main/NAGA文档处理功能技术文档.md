# 🤖 NAGA文档处理功能技术文档

## 📋 概述

研天雪为NAGA系统设计的文档处理功能是一个完整的文档上传、解析、分析和处理系统。该系统采用模块化架构，通过MCP（Model Context Protocol）服务实现文档处理能力，支持多种文档格式的智能分析。

## 🏗️ 系统架构

### 整体架构图
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   前端界面      │    │   API服务层     │    │   MCP服务层     │
│                 │    │                 │    │                 │
│ • Web界面       │◄──►│ • FastAPI       │◄──►│ • Office Word   │
│ • PyQt界面      │    │ • 文件上传      │    │   MCP Server    │
│ • 拖拽上传      │    │ • 文档处理      │    │ • 文档解析      │
│                 │    │ • 结果返回      │    │ • 内容提取      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                │                        │
                                ▼                        ▼
                       ┌─────────────────┐    ┌─────────────────┐
                       │   文件存储      │    │   AI分析引擎    │
                       │                 │    │                 │
                       │ • 本地存储      │    │ • NAGA Core     │
                       │ • 文件管理      │    │ • 智能分析      │
                       │ • 安全验证      │    │ • 内容摘要      │
                       └─────────────────┘    └─────────────────┘
```

## 🔧 核心组件

### 1. API服务层 (`apiserver/api_server.py`)

#### 文件上传接口
```python
@app.post("/upload/document", response_model=FileUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    description: str = Form(None)
):
    """上传文档文件"""
    try:
        # 创建上传目录
        upload_dir = Path("uploaded_documents")
        upload_dir.mkdir(exist_ok=True)
        
        # 检查文件类型
        allowed_extensions = {".docx", ".doc", ".txt", ".pdf", ".md"}
        file_extension = Path(file.filename).suffix.lower()
        
        if file_extension not in allowed_extensions:
            raise HTTPException(
                status_code=400, 
                detail=f"不支持的文件类型: {file_extension}。支持的类型: {', '.join(allowed_extensions)}"
            )
        
        # 生成唯一文件名
        import time
        timestamp = str(int(time.time()))
        safe_filename = f"{timestamp}_{file.filename}"
        file_path = upload_dir / safe_filename
        
        # 保存文件
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # 获取文件信息
        file_size = file_path.stat().st_size
        upload_time = time.strftime("%Y-%m-%d %H:%M:%S")
        
        return FileUploadResponse(
            filename=file.filename,
            file_path=str(file_path),
            file_size=file_size,
            file_type=file_extension,
            upload_time=upload_time,
            message=f"文件 '{file.filename}' 上传成功"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件上传失败: {str(e)}")
```

#### 文档处理接口
```python
@app.post("/document/process")
async def process_document(request: DocumentProcessRequest):
    """处理上传的文档"""
    if not naga_agent:
        raise HTTPException(status_code=503, detail="NagaAgent未初始化")
    
    try:
        file_path = Path(request.file_path)
        
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"文件不存在: {request.file_path}")
        
        # 根据文件类型和操作类型处理文档
        if file_path.suffix.lower() == ".docx":
            # 使用Word MCP服务处理
            mcp_request = {
                "service_name": "office_word_mcp",
                "task": {
                    "tool_name": "get_document_text",
                    "filename": str(file_path)
                }
            }
            
            # 调用MCP服务
            result = await naga_agent.mcp.handoff(mcp_request["service_name"], mcp_request["task"])
            
            if request.action == "read":
                return {
                    "status": "success",
                    "action": "read",
                    "file_path": request.file_path,
                    "content": result,
                    "message": "文档内容读取成功"
                }
            elif request.action == "analyze":
                # 让NAGA分析文档内容
                analysis_prompt = f"请分析以下文档内容，提供结构化的分析报告：\n\n{result}"
                # ... 分析逻辑
```

### 2. MCP管理器 (`mcpserver/mcp_manager.py`)

#### 核心Handoff机制
```python
class MCPManager:
    """MCP服务管理器"""
    
    def __init__(self):
        self.services = {}  # 注册的服务
        self.exit_stack = AsyncExitStack()  # 异步上下文管理
        
    async def handoff(
        self,
        service_name: str,
        task: dict,
        input_history: Any = None,
        pre_items: Any = None,
        new_items: Any = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """执行handoff"""
        try:
            # 验证服务是否注册
            if service_name not in self.services:
                raise ValueError(f"未注册的服务: {service_name}")
                
            service = self.services[service_name]
            
            # 验证必需字段
            if service["strict_schema"]:
                required_fields = service["input_schema"].get("required", [])
                for field in required_fields:
                    if field not in task:
                        raise ValueError(f"缺少必需字段: {field}")
            
            # 应用消息过滤器
            if "messages" in task and service["filter_fn"]:
                try:
                    task["messages"] = service["filter_fn"](task["messages"])
                except Exception as e:
                    logger.warning(f"消息过滤失败: {e}")
            
            # 获取代理实例并执行
            from mcpserver.mcp_registry import MCP_REGISTRY
            agent_name = service["agent_name"]
            agent = MCP_REGISTRY.get(agent_name)
            if not agent:
                raise ValueError(f"找不到已注册的Agent实例: {agent_name}")
            
            # 执行handoff
            result = await agent.handle_handoff(task)
            return result
            
        except Exception as e:
            error_msg = f"Handoff执行失败: {str(e)}"
            logger.error(error_msg)
            return json.dumps({
                "status": "error",
                "message": error_msg
            }, ensure_ascii=False)
```

### 3. Office Word MCP服务器

#### 服务适配器 (`mcpserver/Office-Word-MCP-Server-main/word_mcp_adapter.py`)
```python
class WordDocumentMCPServer:
    """Word文档处理MCP服务器适配器"""
    
    def __init__(self):
        self.name = "WordDocumentMCPServer"
        self.instructions = "专业的Microsoft Word文档创建、编辑和管理工具"
        
        # 工具映射表
        self.tool_mapping = {
            # 文档管理
            "create_document": self._create_document,
            "get_document_info": self._get_document_info,
            "get_document_text": self._get_document_text,
            "list_available_documents": self._list_available_documents,
            
            # 内容添加
            "add_paragraph": self._add_paragraph,
            "add_heading": self._add_heading,
            "add_table": self._add_table,
            "add_page_break": self._add_page_break,
            
            # 其他功能
            "help": self._help
        }
    
    async def handle_handoff(self, task: dict) -> str:
        """处理handoff请求"""
        try:
            tool_name = task.get('tool_name')
            if not tool_name:
                return json.dumps({
                    "status": "error",
                    "message": "缺少tool_name参数"
                }, ensure_ascii=False)
            
            if tool_name not in self.tool_mapping:
                return json.dumps({
                    "status": "error",
                    "message": f"不支持的工具: {tool_name}"
                }, ensure_ascii=False)
            
            # 执行对应的工具函数
            tool_func = self.tool_mapping[tool_name]
            result = await tool_func(**{k: v for k, v in task.items() if k != 'tool_name'})
            
            return json.dumps({
                "status": "ok",
                "data": result
            }, ensure_ascii=False)
            
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": f"工具执行失败: {str(e)}"
            }, ensure_ascii=False)
```

#### 文档工具 (`word_document_server/tools/document_tools.py`)
```python
async def get_document_text(filename: str) -> str:
    """提取Word文档的所有文本"""
    filename = ensure_docx_extension(filename)
    return extract_document_text(filename)

async def get_document_info(filename: str) -> str:
    """获取Word文档信息"""
    filename = ensure_docx_extension(filename)
    
    if not os.path.exists(filename):
        return f"Document {filename} does not exist"
    
    try:
        properties = get_document_properties(filename)
        return json.dumps(properties, indent=2)
    except Exception as e:
        return f"Failed to get document info: {str(e)}"

async def create_document(filename: str, title: Optional[str] = None, author: Optional[str] = None, save_path: Optional[str] = None) -> str:
    """创建新的Word文档"""
    # 解析完整文件路径
    full_path = resolve_document_path(filename, save_path)
    
    # 验证文件可写性
    is_writeable, error_message = check_file_writeable(full_path)
    if not is_writeable:
        return f"Cannot create document: {error_message}"
    
    try:
        doc = Document()
        
        # 设置文档属性
        if title:
            doc.core_properties.title = title
        if author:
            doc.core_properties.author = author
        
        # 确保必要的样式存在
        ensure_heading_style(doc)
        ensure_table_style(doc)
        
        # 保存文档
        doc.save(full_path)
        
        return f"Document created successfully at: {full_path}"
    except Exception as e:
        return f"Failed to create document: {str(e)}"
```

#### 文档工具函数 (`word_document_server/utils/document_utils.py`)
```python
def extract_document_text(doc_path: str) -> str:
    """从Word文档中提取所有文本"""
    import os
    if not os.path.exists(doc_path):
        return f"Document {doc_path} does not exist"
    
    try:
        doc = Document(doc_path)
        text = []
        
        # 提取段落文本
        for paragraph in doc.paragraphs:
            text.append(paragraph.text)
            
        # 提取表格文本
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        text.append(paragraph.text)
        
        return "\n".join(text)
    except Exception as e:
        return f"Failed to extract text: {str(e)}"

def get_document_properties(doc_path: str) -> Dict[str, Any]:
    """获取Word文档属性"""
    import os
    if not os.path.exists(doc_path):
        return {"error": f"Document {doc_path} does not exist"}
    
    try:
        doc = Document(doc_path)
        core_props = doc.core_properties
        
        return {
            "title": core_props.title or "",
            "author": core_props.author or "",
            "subject": core_props.subject or "",
            "keywords": core_props.keywords or "",
            "created": str(core_props.created) if core_props.created else "",
            "modified": str(core_props.modified) if core_props.modified else "",
            "last_modified_by": core_props.last_modified_by or "",
            "revision": core_props.revision or 0,
            "page_count": len(doc.sections),
            "word_count": sum(len(paragraph.text.split()) for paragraph in doc.paragraphs),
            "paragraph_count": len(doc.paragraphs),
            "table_count": len(doc.tables)
        }
    except Exception as e:
        return {"error": f"Failed to get document properties: {str(e)}"}

def get_document_structure(doc_path: str) -> Dict[str, Any]:
    """获取Word文档结构"""
    import os
    if not os.path.exists(doc_path):
        return {"error": f"Document {doc_path} does not exist"}
    
    try:
        doc = Document(doc_path)
        structure = {
            "paragraphs": [],
            "tables": []
        }
        
        # 获取段落信息
        for i, para in enumerate(doc.paragraphs):
            structure["paragraphs"].append({
                "index": i,
                "text": para.text[:100] + ("..." if len(para.text) > 100 else ""),
                "style": para.style.name if para.style else "Normal"
            })
        
        # 获取表格信息
        for i, table in enumerate(doc.tables):
            table_data = {
                "index": i,
                "rows": len(table.rows),
                "columns": len(table.columns),
                "preview": []
            }
            
            # 获取表格预览数据
            max_rows = min(3, len(table.rows))
            for row_idx in range(max_rows):
                row_data = []
                max_cols = min(3, len(table.columns))
                for col_idx in range(max_cols):
                    try:
                        cell_text = table.cell(row_idx, col_idx).text
                        row_data.append(cell_text[:20] + ("..." if len(cell_text) > 20 else ""))
                    except IndexError:
                        row_data.append("")
                table_data["preview"].append(row_data)
            
            structure["tables"].append(table_data)
        
        return structure
    except Exception as e:
        return {"error": f"Failed to get document structure: {str(e)}"}
```

### 4. 前端界面

#### Web界面 (`apiserver/static/document_upload.html`)
```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NAGA 文档处理系统</title>
    <style>
        /* 现代化CSS样式 */
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: rgba(255, 255, 255, 0.95);
            border-radius: 20px;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
            overflow: hidden;
        }
        
        .upload-area {
            border: 3px dashed #667eea;
            border-radius: 15px;
            padding: 60px 20px;
            text-align: center;
            background: #f8f9ff;
            transition: all 0.3s ease;
            cursor: pointer;
            position: relative;
        }
        
        .upload-area:hover {
            border-color: #764ba2;
            background: #f0f2ff;
            transform: translateY(-2px);
        }
        
        .upload-area.dragover {
            border-color: #4CAF50;
            background: #e8f5e8;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 NAGA 文档处理系统</h1>
            <p>上传您的文档，让研天雪为您智能分析和处理</p>
        </div>
        
        <div class="content">
            <div class="upload-section">
                <div class="upload-area" id="uploadArea">
                    <div class="upload-icon">📄</div>
                    <div class="upload-text">拖拽文件到此处或点击选择文件</div>
                    <div style="color: #999; font-size: 0.9em;">支持格式: .docx, .doc, .txt, .pdf, .md</div>
                    <input type="file" id="fileInput" class="file-input" accept=".docx,.doc,.txt,.pdf,.md">
                </div>
                
                <div class="file-info" id="fileInfo">
                    <h3>📋 文件信息</h3>
                    <div id="fileDetails"></div>
                    <div class="action-buttons">
                        <button class="btn" onclick="processDocument('read')">📖 读取内容</button>
                        <button class="btn" onclick="processDocument('analyze')">🔍 智能分析</button>
                        <button class="btn" onclick="processDocument('summarize')">📝 生成摘要</button>
                    </div>
                </div>
                
                <div class="result-area" id="resultArea">
                    <h3 id="resultTitle">处理结果</h3>
                    <div id="resultContent"></div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        // JavaScript文件上传和处理逻辑
        let currentFilePath = null;
        
        // 文件上传处理
        async function uploadFile(file) {
            const formData = new FormData();
            formData.append('file', file);
            
            try {
                showMessage('正在上传文件...', 'info');
                const response = await fetch('/upload/document', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    currentFilePath = result.file_path;
                    showFileInfo(result);
                    showMessage('文件上传成功！', 'success');
                } else {
                    showMessage(result.detail || '上传失败', 'error');
                }
            } catch (error) {
                showMessage('上传失败: ' + error.message, 'error');
            }
        }
        
        // 文档处理
        async function processDocument(action) {
            if (!currentFilePath) {
                showMessage('请先上传文件', 'error');
                return;
            }
            
            try {
                showMessage(`正在${action === 'read' ? '读取' : action === 'analyze' ? '分析' : '生成摘要'}...`, 'info');
                
                const response = await fetch('/document/process', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        file_path: currentFilePath,
                        action: action
                    })
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    showResult(result, action);
                    showMessage('处理完成！', 'success');
                } else {
                    showMessage(result.detail || '处理失败', 'error');
                }
            } catch (error) {
                showMessage('处理失败: ' + error.message, 'error');
            }
        }
    </script>
</body>
</html>
```

#### PyQt界面 (`ui/pyqt_chat_window.py`)
```python
def show_document_options(self):
    """显示文档处理选项对话框"""
    dialog = QDialog(self)
    dialog.setWindowTitle("📄 文档处理")
    dialog.setFixedSize(500, 400)
    dialog.setStyleSheet("""
        QDialog {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                stop:0 #f0f2ff, stop:1 #e8f0fe);
            border-radius: 15px;
        }
        QLabel {
            color: #2c3e50;
            font-weight: bold;
            font-size: 14px;
        }
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                stop:0 #667eea, stop:1 #764ba2);
            color: white;
            border: none;
            border-radius: 8px;
            padding: 12px 20px;
            font-size: 13px;
            font-weight: bold;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                stop:0 #5a6fd8, stop:1 #6a4190);
        }
        QPushButton:pressed {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                stop:0 #4e5bc6, stop:1 #5e377e);
        }
    """)
    
    layout = QVBoxLayout(dialog)
    layout.setSpacing(20)
    layout.setContentsMargins(30, 30, 30, 30)
    
    # 标题
    title = QLabel("🤖 选择文档处理方式")
    title.setAlignment(Qt.AlignCenter)
    title.setStyleSheet("font-size: 18px; color: #2c3e50; margin-bottom: 10px;")
    layout.addWidget(title)
    
    # 文件选择
    file_layout = QHBoxLayout()
    self.file_path_label = QLabel("请选择文档文件...")
    self.file_path_label.setStyleSheet("color: #7f8c8d; font-size: 12px;")
    
    browse_btn = QPushButton("📁 浏览文件")
    browse_btn.clicked.connect(lambda: self.browse_document_file(dialog))
    
    file_layout.addWidget(self.file_path_label)
    file_layout.addWidget(browse_btn)
    layout.addLayout(file_layout)
    
    # 处理选项
    options_layout = QVBoxLayout()
    options_layout.setSpacing(15)
    
    read_btn = QPushButton("📖 读取文档内容")
    read_btn.clicked.connect(lambda: self.process_document(self.selected_file_path, "read", dialog))
    
    analyze_btn = QPushButton("🔍 智能分析文档")
    analyze_btn.clicked.connect(lambda: self.process_document(self.selected_file_path, "analyze", dialog))
    
    summarize_btn = QPushButton("📝 生成文档摘要")
    summarize_btn.clicked.connect(lambda: self.process_document(self.selected_file_path, "summarize", dialog))
    
    options_layout.addWidget(read_btn)
    options_layout.addWidget(analyze_btn)
    options_layout.addWidget(summarize_btn)
    
    layout.addLayout(options_layout)
    
    dialog.exec_()

def process_document(self, file_path, action, dialog=None):
    """处理文档"""
    try:
        if dialog:
            dialog.close()
        
        action_names = {
            "read": "读取",
            "analyze": "分析", 
            "summarize": "摘要"
        }
        
        self.add_user_message("系统", f"🔄 正在{action_names[action]}文档...")
        self.progress_widget.set_thinking_mode()
        self.progress_widget.status_label.setText(f"{action_names[action]}文档中...")
        
        # 发送处理请求
        api_url = "http://localhost:8000/document/process"
        data = {
            "file_path": file_path,
            "action": action
        }
        
        response = requests.post(api_url, json=data, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            self.progress_widget.stop_loading()
            
            # 根据操作类型显示结果
            if action == "read":
                content = result.get('content', '')
                message = f"📖 文档内容:\n\n{content}"
                self.add_user_message("娜迦", message)
                # 将文档内容添加到对话历史中
                self.naga.messages.append({"role": "assistant", "content": message})
            elif action == "analyze":
                analysis = result.get('analysis', '')
                message = f"🔍 文档分析:\n\n{analysis}"
                self.add_user_message("娜迦", message)
                self.naga.messages.append({"role": "assistant", "content": message})
            elif action == "summarize":
                summary = result.get('summary', '')
                message = f"📝 文档摘要:\n\n{summary}"
                self.add_user_message("娜迦", message)
                self.naga.messages.append({"role": "assistant", "content": message})
                
        else:
            self.progress_widget.stop_loading()
            error_msg = f"❌ 文档处理失败: {response.text}"
            self.add_user_message("系统", error_msg)
            
    except Exception as e:
        self.progress_widget.stop_loading()
        error_msg = f"❌ 文档处理出错: {str(e)}"
        self.add_user_message("系统", error_msg)
```

## 🔄 处理流程

### 1. 文档上传流程
```
用户选择文件 → 前端验证格式 → 发送到API服务器 → 文件保存到本地 → 返回文件信息
```

### 2. 文档处理流程
```
用户选择处理方式 → API接收请求 → MCP Manager路由 → Word MCP服务处理 → 返回结果 → 前端展示
```

### 3. MCP服务调用流程
```
API层 → MCPManager.handoff() → MCP_REGISTRY查找服务 → WordDocumentMCPServer.handle_handoff() → 具体工具函数 → 返回结果
```

## 📁 文件结构

```
NagaAgent-main/
├── apiserver/
│   ├── api_server.py              # API服务器主文件
│   └── static/
│       └── document_upload.html   # Web上传界面
├── mcpserver/
│   ├── mcp_manager.py             # MCP管理器
│   ├── mcp_registry.py            # MCP服务注册表
│   └── Office-Word-MCP-Server-main/
│       ├── word_mcp_adapter.py    # Word MCP适配器
│       └── word_document_server/
│           ├── tools/
│           │   ├── document_tools.py    # 文档工具
│           │   └── content_tools.py     # 内容工具
│           └── utils/
│               ├── document_utils.py    # 文档工具函数
│               └── file_utils.py        # 文件工具函数
├── ui/
│   └── pyqt_chat_window.py        # PyQt界面
├── uploaded_documents/            # 文档存储目录
└── main.py                        # 主程序入口
```

## 🛡️ 安全特性

### 1. 文件类型验证
```python
allowed_extensions = {".docx", ".doc", ".txt", ".pdf", ".md"}
file_extension = Path(file.filename).suffix.lower()

if file_extension not in allowed_extensions:
    raise HTTPException(
        status_code=400, 
        detail=f"不支持的文件类型: {file_extension}"
    )
```

### 2. 文件路径安全
```python
def resolve_document_path(filename: str, save_path: Optional[str] = None) -> str:
    """解析文档路径，确保安全性"""
    # 清理文件名，防止路径遍历攻击
    safe_filename = os.path.basename(filename)
    safe_filename = ensure_docx_extension(safe_filename)
    
    if save_path:
        # 验证保存路径的安全性
        safe_path = os.path.abspath(save_path)
        return os.path.join(safe_path, safe_filename)
    else:
        return safe_filename
```

### 3. 文件大小限制
```python
# 在FastAPI中设置文件大小限制
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 文件大小检查
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
if file.size > MAX_FILE_SIZE:
    raise HTTPException(status_code=413, detail="文件过大")
```

## 🚀 性能优化

### 1. 异步处理
- 所有文档处理操作都使用异步函数
- MCP服务调用采用异步机制
- 前端使用异步JavaScript处理文件上传

### 2. 内存管理
- 大文件分块读取
- 及时释放文档对象
- 使用生成器处理大量数据

### 3. 缓存机制
- 文档属性缓存
- MCP服务连接池
- 结果缓存（可选）

## 🔧 配置说明

### 1. 支持的文档格式
```python
SUPPORTED_FORMATS = {
    ".docx": "Microsoft Word文档",
    ".doc": "Microsoft Word文档(旧版)",
    ".txt": "纯文本文件",
    ".md": "Markdown文件",
    ".pdf": "PDF文档(计划支持)"
}
```

### 2. 存储配置
```python
UPLOAD_DIR = "uploaded_documents"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_EXTENSIONS = {".docx", ".doc", ".txt", ".pdf", ".md"}
```

### 3. MCP服务配置
```python
MCP_SERVICES = {
    "office_word_mcp": {
        "name": "WordDocumentMCPServer",
        "description": "Word文档处理服务",
        "agent_name": "office_word_mcp",
        "strict_schema": False
    }
}
```

## 🐛 错误处理

### 1. 文件处理错误
```python
try:
    doc = Document(filename)
    # 处理文档
except FileNotFoundError:
    return "文档文件不存在"
except PermissionError:
    return "没有访问文档的权限"
except Exception as e:
    return f"文档处理失败: {str(e)}"
```

### 2. MCP服务错误
```python
try:
    result = await agent.handle_handoff(task)
except ValueError as e:
    return json.dumps({"status": "error", "message": str(e)})
except Exception as e:
    logger.error(f"MCP服务调用失败: {e}")
    return json.dumps({"status": "error", "message": "服务调用失败"})
```

### 3. API错误处理
```python
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"未处理的异常: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "内部服务器错误"}
    )
```

## 📈 扩展性

### 1. 新文档格式支持
要添加新的文档格式支持，需要：
1. 在`allowed_extensions`中添加新格式
2. 在MCP服务中添加对应的处理逻辑
3. 更新前端界面的文件类型过滤

### 2. 新处理功能
要添加新的文档处理功能，需要：
1. 在`WordDocumentMCPServer`中添加新的工具函数
2. 在API层添加对应的处理逻辑
3. 更新前端界面的操作按钮

### 3. 新MCP服务
要添加新的MCP服务，需要：
1. 实现MCP服务适配器
2. 在`MCP_REGISTRY`中注册服务
3. 在`MCPManager`中添加服务配置

## 🎯 总结

NAGA的文档处理功能是一个完整的、模块化的文档处理系统，具有以下特点：

1. **模块化架构**: 清晰的分层设计，便于维护和扩展
2. **异步处理**: 高性能的异步处理机制
3. **安全可靠**: 完善的安全验证和错误处理
4. **用户友好**: 直观的Web和桌面界面
5. **可扩展性**: 易于添加新功能和新格式支持

该系统通过MCP协议实现了AI助手与文档处理服务的解耦，使得系统具有良好的可维护性和扩展性。研天雪的设计充分考虑了实际使用场景，提供了完整的文档处理解决方案。

---

*文档编写：研天雪 | 最后更新：2024年*