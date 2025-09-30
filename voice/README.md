# NagaAgent 语音服务 🗣️

基于Edge-TTS的OpenAI兼容语音合成服务，为NagaAgent 4.0提供高质量的文本转语音功能。支持流式TTS播放、智能分句、并发音频合成和内存直接播放。

## 🚀 核心功能特性

### 基础TTS功能
- **OpenAI兼容接口**：`/v1/audio/speech`，请求结构和行为与OpenAI类似
- **支持多种语音**：将OpenAI语音（alloy, echo, fable, onyx, nova, shimmer）映射到`edge-tts`语音
- **多音频格式**：支持多种音频格式（mp3, opus, aac, flac, wav, pcm）
- **可调节语速**：支持0.25x到4.0x的播放速度
- **可选直接指定edge-tts语音**：既可用OpenAI语音映射，也可直接指定任意edge-tts语音
- **HTTP和WebSocket双模式**：支持REST API和实时WebSocket连接

### 🎯 流式TTS播放（参考实现）
- **智能标点符号分割**：参考的标点符号分割算法，实时检测句子结束
- **括号计数**：智能处理嵌套括号，避免错误分割工具调用
- **内存直接播放**：使用pygame库直接在内存中播放音频数据，无需创建临时文件
- **并发音频合成**：支持多个音频片段并发申请API，提高处理速度
- **工具调用分流**：与apiserver的流式工具调用提取器完美集成，支持工具调用的特殊处理
- **异步处理**：语音处理不阻塞前端显示，提供更好的用户体验

### 🔄 架构优化
- **避免重复处理**：移除voice模块中的复杂标点符号分割算法
- **依赖apiserver**：使用apiserver的流式工具调用提取器进行预处理
- **简化voice模块**：voice只负责TTS音频生成和播放
- **完全移除旧方式**：删除所有旧的完整文本处理逻辑

## 📋 快速开始

### 前置条件

- **Python 3.8+**：确保Python环境已安装
- **依赖包**：安装项目依赖 `pip install -r requirements.txt`
- **pygame**：用于后台音频播放（已包含在requirements.txt中）
- **ffmpeg**（可选）：音频格式转换需要，只用mp3可不装

### 配置说明

语音服务配置在 `config.json` 文件的 `tts` 部分：

```json
{
  "system": {
    "voice_enabled": true  // 启用语音功能
  },
  "tts": {
    "api_key": "your_api_key_here",
    "port": 5050,
    "default_voice": "zh-CN-XiaoxiaoNeural",
    "default_format": "mp3",
    "default_speed": 1.0,
    "default_language": "zh-CN",
    "remove_filter": false,
    "expand_api": true,
    "require_api_key": true,
    "keep_audio_files": false  // 是否保留音频文件用于调试
  }
}
```

### 启动方式

#### 方式1：通过NagaAgent主程序自动启动
```bash
python main.py
```
主程序会自动启动语音服务。

#### 方式2：独立启动语音服务
```bash
# 启动HTTP服务器
python voice/start_voice_service.py --mode http

# 启动WebSocket服务器
python voice/start_voice_service.py --mode websocket

# 同时启动两种模式
python voice/start_voice_service.py --mode both

# 检查依赖
python voice/start_voice_service.py --check-deps

# 自定义端口
python voice/start_voice_service.py --port 8080
```

#### 方式3：直接启动服务器
```bash
# HTTP服务器
python voice/server.py

# WebSocket服务器
python voice/websocket_edge_tts.py
```

## 🎵 流式TTS播放功能

### 处理流程
1. **apiserver接收** → LLM流式输出
2. **工具调用提取** → `streaming_tool_extractor` 进行标点分割和工具调用检测
3. **文本分流** → 普通文本发送给voice模块，工具调用单独处理
4. **voice接收** → `receive_text_chunk()` 接收处理好的普通文本
5. **音频生成** → `_audio_processing_worker()` 并发生成音频
6. **内存播放** → `_audio_player_worker()` pygame直接播放
7. **完成处理** → `finish_processing()` 清理剩余内容

### 智能分句算法
```python
def _check_and_queue_sentences(self):
    """检查并加入句子队列 - 简化版本，依赖apiserver的预处理"""
    if not self.text_buffer:
        return
        
    # 简单的句子结束检测（apiserver已经处理过复杂的标点分割）
    sentence_endings = ["。", "！", "？", "；", ".", "!", "?", ";"]
    
    for ending in sentence_endings:
        if ending in self.text_buffer:
            # 找到句子结束位置
            end_pos = self.text_buffer.find(ending) + 1
            sentence = self.text_buffer[:end_pos]
            
            # 检查句子是否有效
            if sentence.strip():
                # 加入句子队列
                self.sentence_queue.put(sentence)
                # 启动音频合成线程...
```

### 使用方法

#### 基本使用
```python
from voice.output.voice_integration import get_voice_integration

# 获取语音集成实例
voice_integration = get_voice_integration()

# 播放完整文本
voice_integration.receive_final_text("你好，这是一个测试。")

# 播放文本片段（支持智能分句）
voice_integration.receive_text_chunk("这是一个很长的文本，")
voice_integration.receive_text_chunk("它会被自动分割成多个句子进行播放。")
```

#### 流式处理
```python
# 流式文本输入
voice_integration.receive_text_chunk("开始生成回复...")
voice_integration.receive_text_chunk("正在处理您的问题。")
voice_integration.receive_text_chunk("这是最终的答案。")

# 完成处理
voice_integration.finish_processing()
```

## 🔧 服务状态检查

### 检查服务状态
```bash
python voice/voice_status.py
```

### 测试TTS功能
```bash
curl -X POST http://127.0.0.1:5050/v1/audio/speech \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_api_key_here" \
  -d '{
    "input": "Hello, this is a test.",
    "voice": "alloy",
    "response_format": "mp3",
    "speed": 1.0
  }' \
  --output test_speech.mp3
```

### 测试流式TTS功能
```bash
# 测试新的流式TTS实现（参考）
python voice/test__tts.py

# 测试基础播放功能
python voice/test_audio_playback.py

# 测试句子分割功能
python voice/test_sentence_splitting.py
```

## 📁 文件存储结构

```
logs/audio_temp/
├── tts_audio_[时间戳]_[索引].mp3  # 音频文件命名格式
├── README.md                      # 目录说明文件
└── ...                           # 其他音频文件
```

## ⚙️ 配置参数说明

### 关键配置项
- `voice_enabled`: 是否启用语音功能
- `port`: TTS服务端口
- `default_voice`: 默认语音
- `default_format`: 音频格式（mp3, wav, opus等）
- `default_speed`: 播放速度（0.25-4.0）
- `remove_filter`: 是否移除文本过滤器
- `keep_audio_files`: 是否保留音频文件用于调试

### 分句配置
- **句子结束标点**：`[。？！；\.\?\!\;]`
- **最小句子长度**：5个字符
- **短句合并**：长度≤5且不包含引号的句子会被合并
- **最大缓冲区**：50个文本片段

### 并发配置
- **最大并发任务数**：3个
- **信号量控制**：防止过多并发请求
- **超时设置**：30秒

## 🚀 性能优势

### 实时响应
- apiserver实时处理LLM流式输出
- 工具调用检测和文本分流实时进行
- voice模块实时接收普通文本并生成音频
- 音频生成和播放并行处理

### 内存效率
- 直接播放内存中的音频数据
- 减少临时文件创建和删除
- 降低磁盘I/O开销

### 用户体验
- 语音播放与文本显示同步
- 工具调用不影响普通文本的语音播放
- 不阻塞前端界面响应

## 🔧 故障排除

### 常见问题
1. **TTS服务未启动**：运行`python voice/start_voice_service.py`
2. **语音功能被禁用**：检查`config.json`中的`voice_enabled`
3. **pygame不可用**：安装pygame `pip install pygame`
4. **音频文件未生成**：检查TTS服务状态和网络连接

### 调试模式
启用调试模式保留音频文件：
```json
{
  "tts": {
    "keep_audio_files": true
  }
}
```

### 音频播放失败排查
1. 检查TTS服务是否正常运行：
   ```bash
   python voice/voice_status.py
   ```

2. 检查音频文件目录：
   ```bash
   # 查看音频文件
   ls logs/audio_temp/
   
   # 检查文件权限
   ls -la logs/audio_temp/
   ```

3. 检查音频设备：
   - Windows：检查系统音量
   - macOS：检查音频输出设备
   - Linux：检查音频驱动

4. 查看日志：
   ```bash
   # 查看详细日志
   tail -f logs/nagaagent.log
   ```

## 📝 更新日志

### v3.1.0 - 流式TTS重构
- ✅ 参考的流式TTS实现
- ✅ 标点符号分割算法优化
- ✅ 括号计数避免错误分割
- ✅ 内存中直接播放音频数据
- ✅ 工具调用分流处理
- ✅ 与apiserver完美集成
- ✅ 异步处理不阻塞前端

### v3.0.2 - 并发音频合成
- ✅ 新增并发音频合成功能
- ✅ 本地文件存储管理
- ✅ 按顺序播放音频文件
- ✅ 自动文件清理机制
- ✅ 调试模式支持

### v3.0.1 - pygame播放
- ✅ 新增pygame后台直接播放
- ✅ 智能分句功能
- ✅ 并发播放支持
- ✅ 移除系统播放器依赖
- ✅ 简化播放逻辑

### v3.0.0 - 基础功能
- 🔄 系统播放器播放
- 🔄 临时文件创建
- 🔄 基础TTS功能

## 🎙️ 语音示例

[试听语音样例及全部Edge TTS语音](https://tts.travisvn.com/)

## 🎤 语音输入服务

### 概述
语音输入服务是 NagaAgent 的独立语音识别模块，基于 MoeChat 的 Silero VAD 技术和本地 FunASR 引擎，提供高质量的语音转文本功能。

### 核心特性
- **本地麦克风采集**：实时音频采集与处理
- **Silero VAD 端点检测**：准确的语音活动检测
- **本地 FunASR 识别**：基于 ModelScope 的离线语音识别
- **HTTP REST API**：OpenAI 兼容的转写接口
- **WebSocket 实时识别**：实时 VAD + ASR 推送
- **设备管理**：自动检测和选择音频设备

### 快速启动
```bash
# 安装依赖
pip install -r voice/input/requirements.txt

# 启动服务
python voice/input/start_input_service.py

# 检查依赖
python voice/input/start_input_service.py --check-deps
```

### 主要接口
- `POST /v1/audio/transcriptions` - 文件转写
- `POST /v1/audio/transcriptions_b64` - Base64 转写
- `GET /devices` - 音频设备列表
- `POST /control/listen/start|stop` - 本地监听控制
- `ws://127.0.0.1:5060/v1/audio/asr_ws` - 实时识别

### 详细文档
更多信息请参考：[voice/input/README.md](input/README.md)

## 📄 许可证

本项目采用GNU GPL v3.0协议，仅限个人用途。如需企业或非个人用途，请联系 tts@travisvn.com
