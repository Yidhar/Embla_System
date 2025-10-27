# AgentServer会话管理升级说明

## 概述
将MCP服务器的独立会话线程和会话ID管理逻辑应用到agentserver，实现统一的会话管理机制。

## 修改内容

### 1. 背景分析器修改 (`system/background_analyzer.py`)

#### 修改的方法：`_send_to_agent_server`
- **原逻辑**：简单的消息传递，缺少会话管理
- **新逻辑**：应用与MCP服务器相同的会话管理机制

#### 主要改进：
```python
# 新的请求格式
agent_payload = {
    "query": f"批量Agent任务执行 ({len(agent_calls)} 个)",
    "agent_calls": agent_calls,  # 传递完整的agent_calls信息
    "session_id": session_id,
    "analysis_session_id": analysis_session_id,  # 传递独立分析会话ID
    "request_id": str(uuid.uuid4()),  # 生成独立请求ID
    "callback_url": f"http://localhost:{get_server_port('api_server')}/agent_result_callback"  # 添加回调URL
}
```

#### 关键特性：
- **独立分析会话ID**：`analysis_session_id`用于跟踪意图分析会话
- **请求ID**：`request_id`用于唯一标识每个请求
- **回调机制**：`callback_url`用于异步结果通知
- **统一端点**：使用`/schedule`端点替代`/analyze_and_execute`

### 2. AgentServer新增功能 (`agentserver/agent_server.py`)

#### 新增端点：`/schedule`
- **功能**：统一的任务调度端点，支持新的请求格式
- **特性**：
  - 支持独立会话ID管理
  - 异步任务执行（不阻塞响应）
  - 任务调度器集成
  - 回调通知机制

#### 新增函数：

##### `_execute_agent_tasks_async`
- **功能**：异步执行Agent任务
- **特性**：
  - 批量任务处理
  - 任务步骤记录
  - 错误处理和恢复
  - 回调通知

##### `_send_callback_notification`
- **功能**：发送回调通知
- **特性**：
  - 异步HTTP请求
  - 错误处理
  - 结果状态通知

### 3. 任务调度器增强 (`agentserver/task_scheduler.py`)

#### 新增方法：`create_task`
- **功能**：创建新任务，支持会话管理
- **参数**：
  - `task_id`：任务唯一标识
  - `purpose`：任务目的描述
  - `session_id`：原始会话ID
  - `analysis_session_id`：分析会话ID

#### 会话管理特性：
- 任务注册表管理
- 会话ID关联
- 任务状态跟踪
- 步骤计数

## 会话管理逻辑对比

### MCP服务器会话管理
```python
# 独立分析会话ID
analysis_session_id = f"analysis_{session_id}_{int(time.time())}"

# 请求载荷
mcp_payload = {
    "query": f"批量MCP工具调用 ({len(mcp_calls)} 个)",
    "tool_calls": mcp_calls,
    "session_id": session_id,
    "request_id": str(uuid.uuid4()),
    "callback_url": f"http://localhost:{get_server_port('api_server')}/tool_result_callback"
}
```

### AgentServer会话管理（新）
```python
# 独立分析会话ID（继承自背景分析器）
analysis_session_id = f"analysis_{session_id}_{int(time.time())}"

# 请求载荷
agent_payload = {
    "query": f"批量Agent任务执行 ({len(agent_calls)} 个)",
    "agent_calls": agent_calls,
    "session_id": session_id,
    "analysis_session_id": analysis_session_id,
    "request_id": str(uuid.uuid4()),
    "callback_url": f"http://localhost:{get_server_port('api_server')}/agent_result_callback"
}
```

## 向后兼容性

### 保留的端点
- `/analyze_and_execute`：保持原有功能，确保向后兼容
- 所有现有的任务管理API端点保持不变

### 新增的端点
- `/schedule`：新的统一调度端点，支持增强的会话管理

## 使用示例

### 新的调度请求格式
```python
# 背景分析器发送的请求
{
    "query": "批量Agent任务执行 (2 个)",
    "agent_calls": [
        {
            "tool_name": "computer_control",
            "service_name": "agent_server",
            "instruction": "打开记事本",
            "agentType": "agent"
        },
        {
            "tool_name": "computer_control", 
            "service_name": "agent_server",
            "instruction": "输入文本",
            "agentType": "agent"
        }
    ],
    "session_id": "user_session_123",
    "analysis_session_id": "analysis_user_session_123_1703123456",
    "request_id": "req_456789",
    "callback_url": "http://localhost:8000/agent_result_callback"
}
```

### 响应格式
```python
{
    "success": True,
    "status": "scheduled",
    "task_id": "req_456789",
    "message": "已调度 2 个Agent任务",
    "accepted_at": "2024-01-01T12:00:00",
    "session_id": "user_session_123",
    "analysis_session_id": "analysis_user_session_123_1703123456"
}
```

## 优势

1. **统一会话管理**：MCP服务器和AgentServer使用相同的会话管理逻辑
2. **独立会话跟踪**：每个意图分析会话都有独立的ID
3. **异步执行**：任务调度不阻塞响应，提高性能
4. **回调机制**：支持异步结果通知
5. **任务记忆**：集成任务调度器的记忆管理功能
6. **向后兼容**：保持现有API的兼容性

## 注意事项

1. **回调URL**：需要确保API服务器有对应的回调端点
2. **错误处理**：异步执行中的错误会通过回调通知
3. **资源管理**：长时间运行的任务需要适当的超时处理
4. **日志记录**：所有会话管理操作都有详细的日志记录

## 测试建议

1. 测试新的`/schedule`端点
2. 验证会话ID的正确传递和跟踪
3. 测试回调通知机制
4. 验证向后兼容性
5. 测试异步任务执行和错误处理
