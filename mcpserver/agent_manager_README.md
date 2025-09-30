# AgentManager 使用说明

## 概述

AgentManager是NagaAgent 4.0中独立的Agent注册和调用系统，支持从配置文件动态加载Agent定义，提供统一的调用接口和完整的生命周期管理。参考了JavaScript版本的AgentAssistant机制，实现了类似的功能。

## 主要特性

- ✅ **动态配置加载**: 从JSON配置文件自动加载Agent定义
- ✅ **会话管理**: 支持多会话历史记录和上下文管理
- ✅ **智能占位符替换**: 支持Agent配置、环境变量、时间信息等多种占位符
- ✅ **定期清理**: 自动清理过期的会话上下文（TTL管理）
- ✅ **错误处理**: 完善的错误处理和日志记录
- ✅ **中文友好**: 完全支持中文界面和提示词
- ✅ **多模型支持**: 支持OpenAI、DeepSeek、Anthropic等多种LLM提供商
- ✅ **热重载**: 支持运行时重新加载配置，无需重启系统
- ✅ **会话隔离**: 多用户会话完全隔离，支持独立上下文

## 文件结构

```
├── agent_manager.py          # Agent管理器主文件
├── agent_configs/            # Agent配置文件目录
│   └── agents.json          # Agent定义配置文件
├── test_agent_manager.py     # 测试脚本
└── agent_manager_README.md   # 使用说明
```

## 快速开始

### 1. 创建Agent配置文件

在`agent_configs/agents.json`中定义你的Agent：

```json
{
  "小助手": {
    "model_id": "deepseek-chat",
    "name": "小助手",
    "base_name": "assistant",
    "system_prompt": "你是一个友好、专业的AI助手，名叫{{AgentName}}。你擅长回答各种问题，提供有用的建议和帮助。请用中文回复，保持礼貌和耐心。",
    "max_output_tokens": 40000,
    "temperature": 0.7,
    "description": "通用AI助手，擅长回答各种问题",
    "model_provider": "openai",
    "api_base_url": "https://api.deepseek.com/v1",
    "api_key": "your-api-key-here"
  }
}
```

### 2. 基本使用

```python
import asyncio
from agent_manager import call_agent, list_agents

# 列出所有可用的Agent
agents = list_agents()
print("可用Agent:", [agent['name'] for agent in agents])

# 调用Agent
async def main():
    result = await call_agent("小助手", "你好，请介绍一下你自己")
    if result['status'] == 'success':
        print("回复:", result['result'])
    else:
        print("错误:", result['error'])

asyncio.run(main())
```

### 3. 高级使用

```python
from agent_manager import get_agent_manager

# 获取管理器实例
manager = get_agent_manager()

# 获取Agent详细信息
info = manager.get_agent_info("小助手")
print("Agent信息:", info)

# 重新加载配置
manager.reload_configs()

# 使用自定义会话ID
result = await manager.call_agent("小助手", "你好", session_id="my_session")
```

## 配置字段说明

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `model_id` | string | ✅ | 模型ID（如deepseek-chat） |
| `name` | string | ✅ | Agent显示名称（中文） |
| `base_name` | string | ❌ | 基础名称（英文，用于会话ID） |
| `system_prompt` | string | ❌ | 系统提示词，支持`{{AgentName}}`占位符 |
| `max_output_tokens` | int | ❌ | 最大输出token数（默认40000） |
| `temperature` | float | ❌ | 温度参数（默认0.7） |
| `description` | string | ❌ | Agent描述信息 |
| `model_provider` | string | ❌ | 模型提供商（默认openai） |
| `api_base_url` | string | ❌ | API基础URL |
| `api_key` | string | ❌ | API密钥 |

## 会话管理

### 会话历史

Agent管理器自动维护会话历史，支持多轮对话：

```python
# 连续调用同一个Agent，会自动维护历史
result1 = await call_agent("小助手", "我叫张三")
result2 = await call_agent("小助手", "你还记得我的名字吗？")  # 会记住之前的对话
```

### 会话ID

可以为不同的用户或场景创建独立的会话：

```python
# 用户A的会话
result1 = await call_agent("小助手", "你好", session_id="user_a")

# 用户B的会话（独立的历史）
result2 = await call_agent("小助手", "你好", session_id="user_b")
```

### 会话清理

- 会话历史超过`max_history_rounds * 2`条消息时自动截断
- 会话超过`context_ttl_hours`小时自动过期
- 每小时自动清理过期的会话

## 智能占位符支持

在系统提示词中可以使用以下占位符：

### Agent配置占位符
- `{{AgentName}}`: Agent名称
- `{{Description}}`: 描述信息
- `{{ModelId}}`: 模型ID
- `{{Temperature}}`: 温度参数
- `{{MaxTokens}}`: 最大输出token数
- `{{ModelProvider}}`: 模型提供商

### 环境变量占位符
- `{{ENV_VAR_NAME}}`: 系统环境变量

### 时间占位符
- `{{CurrentTime}}`: 当前时间 (HH:MM:SS)
- `{{CurrentDate}}`: 当前日期 (YYYY-MM-DD)
- `{{CurrentDateTime}}`: 完整时间 (YYYY-MM-DD HH:MM:SS)

### 示例配置
```json
{
  "system_prompt": "你是{{AgentName}}，一个专业的{{Description}}。\n\n当前时间：{{CurrentDateTime}}\n模型：{{ModelId}}\n温度：{{Temperature}}\n\n请用中文回答，保持专业和友好的态度。"
}
```

## 错误处理

Agent管理器提供完善的错误处理：

```python
result = await call_agent("不存在的Agent", "测试")
if result['status'] == 'error':
    print("错误:", result['error'])
    # 错误信息会包含可用的Agent列表
```

常见错误：
- Agent不存在：会列出所有可用的Agent
- API调用失败：会显示具体的错误信息
- 配置错误：会提示缺少的配置字段

## 测试

运行测试脚本验证功能：

```bash
python test_agent_manager.py
```

测试内容包括：
- Agent配置加载
- Agent信息获取
- Agent调用
- 会话历史管理
- 错误情况处理

## 集成到现有系统

### 1. 与MCP系统集成

可以将Agent管理器集成到现有的MCP系统中：

```python
# 在mcp_manager.py中添加Agent调用支持
from agent_manager import call_agent

async def call_agent_service(agent_name: str, prompt: str):
    return await call_agent(agent_name, prompt)
```

### 2. 与对话系统集成

在`conversation_core.py`中集成Agent调用：

```python
# 在工具调用循环中添加Agent调用
if tool_name == "agent":
    result = await call_agent(service_name, args.get("prompt", ""))
    return result.get("result", "调用失败")
```

## 配置示例

### 多Agent配置

```json
{
  "小助手": {
    "model_id": "deepseek-chat",
    "name": "小助手",
    "system_prompt": "你是一个友好的AI助手，名叫{{AgentName}}。",
    "temperature": 0.7
  },
  "代码专家": {
    "model_id": "deepseek-chat", 
    "name": "代码专家",
    "system_prompt": "你是一个专业的编程专家，名叫{{AgentName}}。",
    "temperature": 0.3
  },
  "创意写作": {
    "model_id": "deepseek-chat",
    "name": "创意写作", 
    "system_prompt": "你是一个富有创意的写作专家，名叫{{AgentName}}。",
    "temperature": 0.8
  }
}
```

### 不同模型配置

```json
{
  "GPT助手": {
    "model_id": "gpt-4",
    "name": "GPT助手",
    "model_provider": "openai",
    "api_base_url": "https://api.openai.com/v1"
  },
  "本地模型": {
    "model_id": "qwen2.5-7b",
    "name": "本地助手",
    "model_provider": "ollama",
    "api_base_url": "http://localhost:11434"
  }
}
```

## 注意事项

1. **API密钥安全**: 不要在代码中硬编码API密钥，建议使用环境变量
2. **模型兼容性**: 确保使用的模型ID与API提供商兼容
3. **会话管理**: 大量并发用户时注意内存使用
4. **错误处理**: 在生产环境中添加更详细的错误日志
5. **配置验证**: 定期验证Agent配置的正确性

## 扩展功能

可以根据需要扩展以下功能：

- 支持更多模型提供商
- 添加Agent性能监控
- 实现Agent调用统计
- 支持Agent配置热重载
- 添加Agent调用限流
- 实现Agent调用缓存 