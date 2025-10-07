# NagaAgent API服务器

轻量级智能API服务器，专注于核心对话功能和文档处理。

## 🚀 功能特性

### 核心功能
- **智能对话**: 支持普通对话和流式对话
- **文档处理**: 支持文档上传、读取、分析和总结
- **会话管理**: 完整的会话生命周期管理
- **记忆系统**: 集成记忆管理功能
- **博弈论流程**: 支持基于博弈论的智能分析流程

### 工具调用循环
- **自动解析**: 自动解析LLM返回的`<<<[HANDOFF]>>>`格式工具调用
- **递归执行**: 支持多轮工具调用循环，最大循环次数可配置
- **错误处理**: 完善的错误处理和回退机制
- **流式支持**: 支持流式和非流式两种模式

### 流式工具调用提取 ✨
- **实时检测**: 实时检测AI输出中的工具调用，支持中英文括号
- **智能分离**: 自动分离普通文本和工具调用，不阻塞前端显示
- **异步执行**: 工具调用异步执行，不影响文本流式输出
- **嵌套支持**: 支持嵌套括号的复杂工具调用格式
- **错误恢复**: 工具调用失败时自动恢复文本输出

## 📋 API接口

### 基础接口

#### GET `/`
- **描述**: API根路径
- **返回**: 服务器基本信息

#### GET `/health`
- **描述**: 健康检查
- **返回**: 服务器状态信息

#### GET `/system/info`
- **描述**: 获取系统信息
- **返回**: 版本、状态、可用服务等


### 对话接口

#### POST `/chat`
- **描述**: 普通对话接口
- **请求体**:
  ```json
  {
    "message": "用户消息",
    "stream": false,
    "session_id": "会话ID（可选）"
  }
  ```
- **返回**:
  ```json
  {
    "response": "AI回复",
    "session_id": "会话ID",
    "status": "success"
  }
  ```

#### POST `/chat/stream`
- **描述**: 流式对话接口 - 支持流式工具调用提取
- **请求体**: 同普通对话
- **返回**: Server-Sent Events格式的流式响应
- **特殊标记**:
  - `[SENTENCE]`: 完整句子标记
  - `[TOOL_CALL]`: 工具调用开始标记
  - `[TOOL_RESULT]`: 工具执行结果标记
  - `[TOOL_ERROR]`: 工具执行错误标记

### 文档处理接口

#### POST `/upload/document`
- **描述**: 上传文档文件
- **支持格式**: .docx, .doc, .txt, .pdf, .md
- **返回**: 文件上传信息

#### POST `/document/process`
- **描述**: 处理上传的文档
- **支持操作**: read（读取）、analyze（分析）、summarize（总结）
- **请求体**:
  ```json
  {
    "file_path": "文件路径",
    "action": "read|analyze|summarize",
    "session_id": "会话ID（可选）"
  }
  ```

#### GET `/documents/list`
- **描述**: 获取已上传的文档列表
- **返回**: 文档列表和统计信息

### 系统管理接口

#### POST `/system/devmode`
- **描述**: 切换开发者模式

#### GET `/memory/stats`
- **描述**: 获取记忆系统统计信息

## ⚙️ 配置

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `API_SERVER_HOST` | `127.0.0.1` | API服务器主机地址 |
| `API_SERVER_PORT` | `8000` | API服务器端口 |
| `API_SERVER_RELOAD` | `False` | 是否开启自动重载 |
| `MaxhandoffLoopStream` | `5` | 流式模式最大工具调用循环次数 |
| `MaxhandoffLoopNonStream` | `5` | 非流式模式最大工具调用循环次数 |
| `Showhandoff` | `False` | 是否显示工具调用输出 |

### 工具调用格式

LLM返回的工具调用应使用以下格式：

```
<<<[HANDOFF]>>>
tool_name: 「始」服务名称「末」
param1: 「始」参数值1「末」
param2: 「始」参数值2「末」
<<<[END_HANDOFF]>>>
```

## 🚀 启动方式

### 统一启动脚本
```bash
# 启动API服务器
python apiserver/start_server.py api

# 启动LLM服务
python apiserver/start_server.py llm

# 启动所有服务（需要不同端口）
python apiserver/start_server.py both
```

### 环境变量配置
```bash
# API服务器配置
export API_SERVER_HOST=0.0.0.0
export API_SERVER_PORT=8000
export API_SERVER_RELOAD=True

# LLM服务配置
export LLM_SERVICE_HOST=127.0.0.1
export LLM_SERVICE_PORT=8001
export LLM_SERVICE_RELOAD=False

# 启动服务
python apiserver/start_server.py api
```

### 直接使用uvicorn
```bash
# API服务器
uvicorn apiserver.api_server:app --host 127.0.0.1 --port ${API_SERVER_PORT:-8000} --reload

# LLM服务
uvicorn apiserver.llm_service:llm_app --host 127.0.0.1 --port 8001 --reload
```

## 📖 使用示例

### Python客户端示例

```python
import requests
import json
import os

# 从环境变量获取端口，默认8000
api_port = os.getenv("API_SERVER_PORT", "8000")
api_host = os.getenv("API_SERVER_HOST", "127.0.0.1")
api_base = f"http://{api_host}:{api_port}"

# 普通对话
response = requests.post(f"{api_base}/chat", json={
    "message": "你好，请帮我查询今天的天气",
    "stream": False
})
print(response.json())

# 流式对话
response = requests.post(f"{api_base}/chat/stream", json={
    "message": "请帮我分析这张图片",
    "stream": True
}, stream=True)

for line in response.iter_lines():
    if line:
        data = line.decode('utf-8')
        if data.startswith('data: '):
            try:
                json_data = json.loads(data[6:])
                print(json_data)
            except:
                pass
```

### 文档处理示例

```python
import requests

# 上传文档
with open("document.docx", "rb") as f:
    files = {"file": f}
    response = requests.post(f"{api_base}/upload/document", files=files)
    print(response.json())

# 处理文档
response = requests.post(f"{api_base}/document/process", json={
    "file_path": "uploaded_documents/1234567890_document.docx",
    "action": "analyze"
})
print(response.json())
```

## 🏗️ 架构说明

### 核心模块

- **`api_server.py`**: 主API服务器，提供所有RESTful接口
- **`llm_service.py`**: LLM服务模块，提供独立的LLM调用服务
- **`message_manager.py`**: 消息管理器，统一管理会话和消息
- **`streaming_tool_extractor.py`**: 流式文本处理器（实时按句切割并发送给TTS）
- **`tool_call_utils.py`**: 工具调用工具函数

### 相关模块

- **`agentserver/`**: 任务调度和智能体管理（独立服务）
- **`mcpserver/`**: MCP服务管理（独立服务）

### 辅助模块

- **`start_server.py`**: 统一服务启动脚本（支持API服务器和LLM服务）

### 静态资源

- **`static/`**: 静态文件目录
  - `document_upload.html`: 文档上传页面

### 工作流程

1. **对话接收**: 用户发送消息到API服务器
2. **智能处理**: 支持普通对话和博弈论分析流程
3. **文档处理**: 支持文档上传、分析和总结
4. **会话管理**: 完整的会话生命周期管理

### 工具调用循环流程

1. **接收用户消息**
2. **调用LLM API**
3. **解析工具调用**
4. **执行工具调用**
5. **将结果返回给LLM**
6. **重复步骤2-5直到无工具调用或达到最大循环次数**

### 流式工具调用提取流程 ✨

1. **接收AI流式输出**
2. **实时字符级检测**
   - 检测 `{` 或 `｛` 开始工具调用
   - 检测 `}` 或 `｝` 结束工具调用
   - 支持嵌套括号计数
3. **智能分离处理**
   - 普通文本：直接发送到前端显示
   - 工具调用：异步执行，不阻塞文本流
4. **结果整合**
   - 工具执行结果返回给LLM继续处理
   - 错误处理：工具失败时继续文本输出

### 错误处理

- 工具调用失败时会记录错误信息
- 达到最大循环次数时会停止
- 支持回退到原始处理方式
- 任务执行失败时自动重试机制

### 扩展开发

如需添加新的功能模块，可以：

1. **新增API接口**: 在`api_server.py`中添加新的RESTful接口
2. **扩展文档处理**: 添加新的文档格式支持
3. **自定义对话流程**: 扩展对话处理逻辑

## 📝 注意事项

1. **系统要求**: 确保相关服务已正确配置和启动
2. **文档处理**: 支持的文件格式有限，请使用支持的格式
3. **流式处理**: 流式模式下工具调用循环会暂时关闭流式输出
4. **记忆系统**: 开发者模式下不会保存对话日志到GRAG记忆系统
5. **会话管理**: 会话会自动清理过期数据，避免内存泄漏

## 🔧 配置说明

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `API_SERVER_HOST` | `127.0.0.1` | API服务器主机地址 |
| `API_SERVER_PORT` | `8000` | API服务器端口 |
| `API_SERVER_RELOAD` | `False` | 是否开启自动重载 |
| `MaxhandoffLoopStream` | `5` | 流式模式最大工具调用循环次数 |
| `MaxhandoffLoopNonStream` | `5` | 非流式模式最大工具调用循环次数 |
| `Showhandoff` | `False` | 是否显示工具调用输出 |

### 文档处理配置

- **文件大小限制**: 可配置上传文件的最大大小
- **支持格式**: 可扩展支持的文件格式
- **处理超时**: 可配置文档处理的超时时间

## 代理问题

如果你使用了代理服务器，测试本地API时需要绕过代理：
```bash
NO_PROXY="127.0.0.1,localhost" curl -X GET "http://127.0.0.1:${API_SERVER_PORT:-8000}/health"
``` 