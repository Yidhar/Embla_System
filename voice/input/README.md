# NagaAgent 语音输入服务 🎤

基于 MoeChat 语音识别技术的独立输入服务，为 NagaAgent 4.0 提供高质量的语音转文本功能。支持本地麦克风采集、Silero VAD 端点检测、实时 WebSocket 推送和 HTTP API 调用。

## 🚀 核心功能特性

### 语音采集与处理
- **本地麦克风采集**：使用 `sounddevice` 实时采集音频，支持设备选择
- **Silero VAD 端点检测**：基于 ONNX 的语音活动检测，准确识别说话开始/结束
- **智能音频分段**：自动累积语音片段，静音阈值触发分段
- **降噪与重采样**：支持 `noisereduce` 降噪，自动重采样到 16kHz

### 识别引擎
- **远端 HTTP ASR**：默认调用 MoeChat 的 `/api/asr` 接口（推荐）
- **本地 FunASR**：可选，支持离线部署（需额外配置）
- **多语言支持**：支持中文、英文等多种语言识别

### 服务接口
- **HTTP REST API**：OpenAI 兼容的 `/v1/audio/transcriptions` 接口
- **WebSocket 实时**：`/v1/audio/asr_ws` 实时 VAD + ASR 推送
- **本地监听控制**：`/control/listen/*` 启动/停止本机麦克风监听
- **设备管理**：`/devices` 列出可用音频设备

## 📋 快速开始

### 前置条件
- **Python 3.8+**：确保 Python 环境已安装
- **依赖包**：安装项目依赖 `pip install -r voice/input/requirements.txt`
- **VAD 模型**：`silero_vad.onnx` 文件（已在项目根目录）
- **远端 ASR**：MoeChat 服务运行在 `http://127.0.0.1:8001`（可选）

### 配置说明
语音输入服务配置在 `config.json` 文件的 `asr` 部分：

```json
{
  "asr": {
    "port": 5060,
    "device_index": null,
    "sample_rate_in": 48000,
    "frame_ms": 30,
    "resample_to": 16000,
    "vad_threshold": 0.7,
    "silence_ms": 420,
    "noise_reduce": true,
    "engine": "local_funasr",
    "local_model_path": "./utilss/models/SenseVoiceSmall",
    "vad_model_path": "silero_vad.onnx",
    "api_key_required": false,
    "callback_url": null,
    "ws_broadcast": false
  }
}
```

### 启动方式

#### 方式1：通过 NagaAgent 主程序自动启动
```bash
python main.py
```
主程序会自动启动语音服务。

#### 方式2：独立启动语音输入服务
```bash
# 启动完整服务（HTTP + WebSocket）
python voice/input/start_input_service.py

# 仅启动 HTTP 服务
python voice/input/start_input_service.py --mode http

# 仅启动 WebSocket 服务
python voice/input/start_input_service.py --mode websocket

# 检查依赖
python voice/input/start_input_service.py --check-deps

# 自定义端口
python voice/input/start_input_service.py --port 8080
```

#### 方式3：直接启动服务器
```bash
# HTTP 服务器
python voice/input/server.py

# 或使用 uvicorn
uvicorn voice.input.server:app --host 0.0.0.0 --port 5060
```

## 🔧 API 接口说明

### HTTP 接口

#### 健康检查
```bash
GET /health
```
返回服务状态信息。

#### 音频转写（文件上传）
```bash
POST /v1/audio/transcriptions
Content-Type: multipart/form-data

file: [音频文件]
```
支持 WAV、MP3 等格式，返回识别文本。

#### 音频转写（Base64）
```bash
POST /v1/audio/transcriptions_b64
Content-Type: application/json

{
  "audio": "base64编码的音频数据"
}
```

#### 设备列表
```bash
GET /devices
```
返回可用的音频输入设备列表。

#### 本地监听控制
```bash
# 启动麦克风监听
POST /control/listen/start

# 停止麦克风监听
POST /control/listen/stop
```

### WebSocket 接口

#### 实时 VAD + ASR
```bash
ws://127.0.0.1:5060/v1/audio/asr_ws
```

**客户端发送消息格式：**
```json
{
  "type": "asr",
  "data": "base64编码的音频数据"
}
```

**服务端推送消息格式：**
```json
// VAD 开始
{"type": "vad_start"}

// 识别结果
{
  "type": "transcription",
  "text": "识别到的文本",
  "status": "final"
}

// 广播消息
{
  "type": "transcription_broadcast",
  "text": "识别到的文本"
}

// 错误信息
{
  "type": "error",
  "message": "错误描述"
}
```

## 🎯 使用示例

### 基本使用

#### 检查服务状态
```bash
curl http://127.0.0.1:5060/health
```

#### 列出音频设备
```bash
curl http://127.0.0.1:5060/devices
```

#### 文件转写
```bash
curl -F "file=@sample.wav" http://127.0.0.1:5060/v1/audio/transcriptions
```

#### Base64 转写
```bash
# PowerShell 示例
$bytes = [IO.File]::ReadAllBytes("sample.wav")
$base64 = [Convert]::ToBase64String($bytes)
curl -Method POST http://127.0.0.1:5060/v1/audio/transcriptions_b64 -ContentType "application/json" -Body (@{audio=$base64} | ConvertTo-Json)
```

#### 启动本地监听
```bash
curl -X POST http://127.0.0.1:5060/control/listen/start
```

### WebSocket 实时识别

#### JavaScript 客户端示例
```javascript
const ws = new WebSocket('ws://127.0.0.1:5060/v1/audio/asr_ws');

ws.onopen = () => {
    console.log('WebSocket 连接已建立');
};

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    switch (data.type) {
        case 'vad_start':
            console.log('检测到语音开始');
            break;
        case 'transcription':
            console.log('识别结果:', data.text);
            break;
        case 'error':
            console.error('错误:', data.message);
            break;
    }
};

// 发送音频数据
function sendAudio(audioData) {
    const base64 = btoa(String.fromCharCode(...new Uint8Array(audioData)));
    ws.send(JSON.stringify({
        type: 'asr',
        data: base64
    }));
}
```

## 🔧 高级配置

### VAD 参数调优
- **vad_threshold**：VAD 检测阈值（0.0-1.0），值越大越严格
- **silence_ms**：静音结束阈值（毫秒），值越大越不容易误分段
- **frame_ms**：音频分帧时长，影响实时性和准确性

### 音频处理参数
- **sample_rate_in**：输入采样率，建议 48kHz
- **resample_to**：重采样目标，ASR 通常需要 16kHz
- **noise_reduce**：是否启用降噪，可提高识别准确率

### 性能优化
- **device_index**：指定麦克风设备，避免自动选择延迟
- **frame_ms**：调整帧长，平衡实时性和 CPU 占用
- **vad_threshold**：根据环境噪音调整，安静环境可降低阈值

## 🚨 故障排除

### 常见问题

#### 1. 依赖缺失
```bash
# 检查依赖
python voice/input/start_input_service.py --check-deps

# 安装依赖
pip install -r voice/input/requirements.txt
```

#### 2. 麦克风权限
- Windows：检查麦克风隐私设置
- Linux：确保用户在 `audio` 组中
- macOS：检查系统偏好设置中的麦克风权限

#### 3. VAD 模型加载失败
- 确认 `silero_vad.onnx` 文件存在
- 检查 `config.asr.vad_model_path` 路径配置
- 验证 ONNX Runtime 版本兼容性

#### 4. 本地 FunASR 识别失败
- 确认已安装 FunASR：`pip install funasr modelscope`
- 检查模型路径配置：`config.asr.local_model_path`
- 首次运行会自动下载模型，需要网络连接
- 验证模型文件完整性：检查 `./utilss/models/SenseVoiceSmall` 目录
- 运行测试脚本：`python voice/input/test_local_asr.py`



### 调试模式
```bash
# 启用详细日志
export PYTHONPATH=.
python -u voice/input/start_input_service.py --port 5060
```

## 🔗 与 MoeChat 的集成

### 架构关系
```
NagaAgent 语音输入服务 (端口 5060)
    ↓
本地 FunASR 引擎
    ↓
ModelScope 模型识别
```

### 迁移说明
- **VAD 逻辑**：从 `client_cli.py` 和 `client_utils.py` 迁移
- **ASR 引擎**：使用本地 FunASR 替代远端调用
- **WebSocket**：基于 `chat_server.py` 的 `/api/asr_ws` 实现
- **配置管理**：统一使用 `config.asr.*` 配置项

### 兼容性
- 保持与 MoeChat 的音频格式兼容性
- 支持相同的 VAD 参数和分段逻辑
- 完全独立部署，无需外部 ASR 服务

## 📝 更新日志

### v1.0.0 (2025-01-XX)
- ✅ 基础语音输入服务框架
- ✅ Silero VAD 端点检测
- ✅ HTTP REST API 接口
- ✅ WebSocket 实时识别
- ✅ 本地麦克风监听
- ✅ 设备管理和配置
- ✅ 与 MoeChat 集成
- ✅ 完整的错误处理

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request 来改进语音输入服务！

### 开发环境设置
```bash
git clone <repository>
cd NagaAgent3.1
pip install -r voice/input/requirements.txt
python voice/input/start_input_service.py --check-deps
```

### 代码规范
- 遵循 PEP 8 编码规范
- 所有注释使用中文，放在行尾
- 变量统一通过 `config` 管理
- 保持与现有代码风格一致
