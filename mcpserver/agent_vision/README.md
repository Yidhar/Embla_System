# 视觉识别Agent

## 功能概述

视觉识别Agent提供屏幕截图、AI图像分析和OCR文字识别功能，支持分析屏幕内容、识别图像中的文字、理解图像内容。

## 功能特性

### 1. 屏幕截图
- 支持全屏截图和区域截图
- 自动保存为PNG格式
- 支持自定义保存路径

### 2. AI图像分析
- 使用qwen-vl-plus视觉理解模型
- 支持自然语言提问
- 可以分析图像内容、识别UI元素、理解场景

### 3. OCR文字识别
- 支持中英文识别
- 图像预处理提升准确率
- 自动检测Tesseract OCR路径

### 4. 截图并分析
- 一键完成截图和分析
- 适合快速分析屏幕内容

## 工具列表

| 工具名称 | 功能描述 | 参数 |
|---------|---------|------|
| `vision_pipeline` | 一键流水线：截图→视觉分析→(可选)OCR，返回结构化结果 | user_content(必需), with_ocr(可选), bbox(可选), filename(可选), lang(可选) |
| `screenshot` | 屏幕截图 | filename(可选), bbox(可选) |
| `analyze_image` | AI图像分析 | user_content(必需), image_path(可选) |
| `ocr_image` | OCR文字识别 | image_path(必需), lang(可选) |
| `screenshot_and_analyze` | 截图并分析 | user_content(必需), filename(可选) |

## 配置要求

### 环境变量

```env
# .env文件
ALIBABA_CLOUD_ACCESS_KEY_ID=your_dashscope_api_key
```

### 依赖安装

```bash
pip install -r requirements.txt
```

### Tesseract OCR安装（OCR功能需要）

**Windows:**
1. 从 https://github.com/UB-Mannheim/tesseract/wiki 下载安装包
2. 安装时选择中文语言包（如需中文识别）
3. 安装路径会自动检测

**Linux/Mac:**
```bash
# Ubuntu/Debian
sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim

# Mac
brew install tesseract tesseract-lang
```

## 使用示例

### 一键流水线（推荐）

```json
{
  "tool_name": "vision_pipeline",
  "user_content": "分析当前屏幕并提取文字",
  "with_ocr": true
}
```

## 返回格式

### 成功响应

```json
{
  "status": "success",
  "message": "操作成功",
  "data": {
    "result": "具体结果内容"
  }
}
```

### 错误响应

```json
{
  "status": "error",
  "message": "错误信息",
  "data": {}
}
```

## 注意事项

1. **图像路径**: 确保图像文件存在，相对路径基于项目根目录
2. **API密钥**: 需要配置阿里云DashScope API密钥才能使用AI分析功能
3. **OCR依赖**: OCR功能需要安装Tesseract OCR软件
4. **文件权限**: 确保有写入权限保存截图文件
5. **图像格式**: 支持常见图像格式（PNG、JPG、JPEG、BMP等）

## 集成流程

1. **意图识别**: BackgroundAnalyzer识别用户意图
2. **工具调用**: 创建独立的分析会话，分发到MCP服务器
3. **MCP调度**: MCPScheduler接收任务并调度执行
4. **工具执行**: VisionAgent处理工具调用请求
5. **结果返回**: 通过回调URL返回处理结果

## 相关文档

- `agent-manifest.json` - Agent元数据定义
- `vision_tools.py` - 视觉识别工具实现
- `agent_vision.py` - Agent主类实现

