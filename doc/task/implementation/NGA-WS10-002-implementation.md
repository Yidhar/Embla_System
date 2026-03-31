> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS10-002 实施记录

## 任务信息
- **任务ID**: NGA-WS10-002
- **标题**: 注入调用上下文元数据
- **优先级**: P0
- **阶段**: M0
- **依赖**: NGA-WS10-001
- **状态**: ✅ 已完成

## 实施内容

### 1. 修改 `_convert_structured_tool_calls()` 函数

**文件**: `apiserver/agentic_tool_loop.py`

#### 1.1 函数签名更新

添加了 `session_id` 和 `trace_id` 参数：

```python
def _convert_structured_tool_calls(
    structured_calls: List[Dict[str, Any]],
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
```

#### 1.2 自动生成 trace_id

如果未提供 trace_id，自动生成：

```python
# 生成 trace_id（如果未提供）
if not trace_id:
    trace_id = f"trace_{uuid.uuid4().hex[:16]}"
```

#### 1.3 注入上下文元数据到所有调用

为每个工具调用注入元数据：

```python
# 注入上下文元数据（NGA-WS10-002）
call["_tool_call_id"] = call_id
call["_trace_id"] = trace_id
if session_id:
    call["_session_id"] = session_id
```

#### 1.4 更新 native_call 构建

```python
native_call = {
    "agentType": "native",
    **args,
    "_tool_call_id": call_id,
    "_trace_id": trace_id,
}
if session_id:
    native_call["_session_id"] = session_id
```

#### 1.5 更新 mcp_call 构建

```python
merged_call: Dict[str, Any] = {
    "agentType": "mcp",
    "tool_name": mcp_tool_name,
    "_tool_call_id": call_id,
    "_trace_id": trace_id,
}
if session_id:
    merged_call["_session_id"] = session_id
```

#### 1.6 更新 live2d_action 构建

```python
live2d_call = {
    "agentType": "live2d",
    "tool_name": "live2d_action",
    "action": action,
}
_inject_call_context_metadata(live2d_call, ...)
```

#### 1.7 注入风险与执行元数据

新增 `_inject_call_context_metadata()`，在 native/mcp/live2d 分发对象上统一补齐：

- `_risk_level`
- `_execution_scope`
- `_requires_global_mutex`
- `_fencing_epoch`（占位透传；实际 fencing lease 在执行阶段写入）

### 2. 更新调用点

**位置**: `apiserver/agentic_tool_loop.py:1256`

```python
actionable_calls, live2d_calls, validation_errors = _convert_structured_tool_calls(
    structured_tool_calls,
    session_id=session_id,
    trace_id=None,  # 自动生成
)
```

## 验收结果

### ✅ 验收标准达成

1. **call_id 注入**:
   - ✅ 所有工具调用都包含 `_tool_call_id`
   - ✅ 格式：`call_{idx}` 或从原始调用继承

2. **trace_id 注入**:
   - ✅ 所有工具调用都包含 `_trace_id`
   - ✅ 同一批次调用共享相同的 trace_id
   - ✅ 格式：`trace_{16位hex}`

3. **session_id 注入**:
   - ✅ 当 session_id 可用时注入到所有调用
   - ✅ 支持可选注入（session_id 可为 None）

4. **调用类型覆盖**:
    - ✅ native_call 包含完整元数据
    - ✅ mcp_call 包含完整元数据
    - ✅ live2d_action 包含完整元数据（含 session）

5. **治理字段透传**:
   - ✅ 风险等级、执行范围、全局互斥信号已在调度层注入
   - ✅ fencing epoch 槽位已预留并兼容执行阶段写入

6. **日志可回溯性**:
    - ✅ 任意工具调用日志可通过 call_id 定位
    - ✅ 同一请求的所有调用可通过 trace_id 关联
    - ✅ 同一会话的所有调用可通过 session_id 关联

## 元数据字段说明

| 字段 | 类型 | 必填 | 说明 | 格式示例 |
|---|---|---|---|---|
| `_tool_call_id` | string | ✅ | 单次调用唯一标识 | `call_abc123` |
| `_trace_id` | string | ✅ | 请求追踪标识（同批次共享） | `trace_1234567890abcdef` |
| `_session_id` | string | ❌ | 会话标识（可选） | `session_xyz789` |

## 后续增强（待实施）

以下字段在 NGA-WS10-001 中定义，尚未在调度层完整闭环：

1. **idempotency_key**: 幂等键（需在重试逻辑中实现）
2. **caller_role**: 调用方角色（需身份认证集成）
3. **queue_ticket**: 队列票据（需与全局互斥队列协同）

这些字段将在后续任务中逐步补齐。

## 回滚方案

保留向后兼容：
- 旧代码不传 `session_id` 和 `trace_id` 参数时，函数自动生成 trace_id
- 元数据字段以 `_` 前缀标记，不影响现有参数解析逻辑
- 可通过配置开关控制是否记录元数据到日志

## 代码质量

- ✅ Python 语法验证通过
- ✅ 类型注解完整
- ✅ 向后兼容性保持

## 完成时间

2026-02-24

## 负责人

AI Agent (Autonomous Execution)
