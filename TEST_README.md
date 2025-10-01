# NagaAgent 测试脚本使用指南

本目录包含了NagaAgent系统的完整测试脚本，用于验证各个组件的功能和完整工作流程。

## 📋 测试脚本说明

### 1. `test_services.py` - 服务状态检查
**用途**: 快速检查各个服务的运行状态
```bash
python test_services.py
```

**功能**:
- 检查API服务器 (http://localhost:8000)
- 检查Agent服务器 (http://localhost:8001)
- 检查MCP服务器 (http://localhost:8003)
- 提供启动建议

### 2. `test_full_flow.py` - 全流程测试
**用途**: 测试完整的系统功能
```bash
python test_full_flow.py
```

**测试内容**:
- ✅ 普通对话流程
- ✅ 流式对话流程
- ✅ LLM服务调用
- ✅ 意图分析功能
- ✅ MCP任务调度
- ✅ 完整工作流程

### 3. `test_mcp_flow.py` - MCP流程测试
**用途**: 专门测试MCP服务调用流程
```bash
python test_mcp_flow.py
```

**测试内容**:
- 🔧 直接MCP服务调用
- 🧠 Agent服务器分析
- 🔄 MCP回调处理
- 🔄 完整意图识别到MCP调用流程

## 🚀 快速开始

### 步骤1: 检查服务状态
```bash
python test_services.py
```

### 步骤2: 启动所需服务
如果服务未运行，请按以下顺序启动：

```bash
# 启动API服务器
python apiserver/start_server.py api

# 启动Agent服务器
python agentserver/start_server.py

# 启动MCP服务器
python mcpserver/start_server.py
```

### 步骤3: 运行测试
```bash
# 运行完整测试
python test_full_flow.py

# 或运行MCP专项测试
python test_mcp_flow.py
```

## 📊 测试报告

测试完成后会生成以下报告文件：

- `test_report.json` - 完整测试报告
- `mcp_test_report.json` - MCP流程测试报告

## 🔧 测试场景说明

### 普通对话测试
- **输入**: "你好，请介绍一下你自己"
- **验证**: 响应是否正常，会话管理是否工作

### 流式对话测试
- **输入**: "请详细解释一下人工智能的发展历史"
- **验证**: 流式输出是否正常，文本累积是否正确

### 意图分析测试
- **输入**: 包含工具调用需求的消息
- **验证**: 后台意图分析是否触发，工具调用是否被识别

### MCP服务调用测试
- **输入**: "请帮我创建一个新的文档"
- **验证**: MCP任务是否被正确调度和执行

### 完整工作流程测试
- **输入**: 可能触发工具调用的复杂消息
- **验证**: 从对话到意图识别到MCP调用的完整链路

## 🐛 故障排除

### 常见问题

1. **连接被拒绝**
   - 检查服务是否正在运行
   - 确认端口配置是否正确

2. **超时错误**
   - 检查网络连接
   - 确认服务响应时间

3. **测试失败**
   - 查看详细错误信息
   - 检查服务日志

### 调试模式

启用详细日志输出：
```bash
# 设置环境变量
export DEBUG=1
python test_full_flow.py
```

## 📈 性能测试

### 并发测试
```bash
# 运行多个并发测试
python -c "
import asyncio
from test_full_flow import NagaAgentTester

async def run_concurrent():
    tasks = []
    for i in range(5):
        tester = NagaAgentTester()
        tasks.append(tester.test_ordinary_chat())
    
    results = await asyncio.gather(*tasks)
    print(f'并发测试完成，成功: {sum(1 for r in results if r.get(\"success\"))}/5')

asyncio.run(run_concurrent())
"
```

### 压力测试
```bash
# 连续发送多个请求
for i in {1..10}; do
    echo "测试 $i"
    python test_services.py
    sleep 1
done
```

## 🔍 监控和日志

### 查看服务日志
```bash
# API服务器日志
tail -f logs/api_server.log

# Agent服务器日志  
tail -f logs/agent_server.log

# MCP服务器日志
tail -f logs/mcp_server.log
```

### 实时监控
```bash
# 监控服务状态
watch -n 5 'python test_services.py'
```

## 📝 自定义测试

### 添加新的测试用例
```python
# 在 test_full_flow.py 中添加新方法
async def test_custom_feature(self) -> Dict[str, Any]:
    """测试自定义功能"""
    # 实现测试逻辑
    pass
```

### 修改测试参数
```python
# 修改测试消息
test_message = "你的自定义测试消息"

# 修改超时时间
timeout=60.0  # 秒

# 修改重试次数
max_retries = 3
```

## 🎯 最佳实践

1. **测试前检查**: 始终先运行 `test_services.py` 确认服务状态
2. **逐步测试**: 先运行单项测试，再运行完整测试
3. **查看报告**: 仔细阅读测试报告，关注失败项目
4. **日志分析**: 结合服务日志分析问题原因
5. **环境隔离**: 在测试环境中运行，避免影响生产环境

## 📞 支持

如果遇到问题，请：
1. 查看测试报告中的错误信息
2. 检查服务日志
3. 确认所有服务都在运行
4. 验证网络连接和端口配置
