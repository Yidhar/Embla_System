# 06 - Structured tool_calls 主链路与 Local-first Native 工具（含 get_cwd 修复）

本文档用于固化两件已经落地且会影响后续重构/排障的重要事实：

1. **工具调用主链路已改造为结构化 `tool_calls` 通道**：LLM 不再通过输出 ```tool 代码块触发工具，而是通过流式事件传递结构化工具调用列表，AgenticLoop 直接消费。
2. **Local-first 已接入 OpenClaw 调用入口**：对于“可本地完成”的 openclaw message，会被拦截改写为 native 工具执行。

同时记录一次关键修复：将 `cwd/pwd` 的拦截从 `run_cmd: cd`（必被安全层拦截）改为新增 native 工具 `get_cwd`。

---

## 1. 结论摘要（给未来的自己/协作者）

- **不要再实现/依赖 ```tool 文本解析**。当前主链路已经是结构化 `tool_calls`，文本解析属于历史兼容思路（若仓库未来仍保留，仅应作为降级兜底，不应作为主路径）。
- AgenticLoop 的责任是：
  - 收集 LLM 的 `content/reasoning`（流式）
  - 收集结构化 `tool_calls`
  - 统一执行工具并把工具结果回注消息历史
- Local-first 的责任是：
  - 在 OpenClaw 的 message 任务进入执行前，尝试改写为 `native`（文件/命令/检索/文档等）
  - 安全边界由 `system/native_executor.py` 强制（项目根目录 confinement + 高危 token արգել）

---

## 2. 结构化 tool_calls 主链路（已完成）

### 2.1 LLM -> SSE（tool_calls 事件）
实现位置：`apiserver/llm_service.py`

- OpenAI-compatible streaming 会从 provider chunk 中提取 `delta.tool_calls`
- 通过内部 merge/finalize 逻辑，将增量的 arguments 拼接成完整的工具调用对象
- 最终以 SSE chunk 形式 `type = "tool_calls"` 输出（payload 为 JSON 序列化后的列表）

要点：
- tool_calls **不属于 content 文本**，不应混入可见回复。
- 这样可以避免模型输出格式漂移、截断、全角符号、代码块闭合等导致的解析失败。

### 2.2 SSE -> AgenticLoop（structured_tool_calls 收集与执行）
实现位置：`apiserver/agentic_tool_loop.py`

- `run_agentic_loop()` 在流式消费 `llm_service.stream_chat_with_context(...)` 时：
  - 对 `type=content`：累积到 `complete_text`
  - 对 `type=reasoning`：累积到 `complete_reasoning`
  - 对 `type=tool_calls`：解析 JSON 并累积到 `structured_tool_calls`
- 一轮结束后：
  - 将 `structured_tool_calls` 转换为可执行调用集合
  - 调用 `execute_tool_calls(...)` 并行执行
  - 将工具结果格式化回注到 messages

**重要约束**：AgenticLoop 作为主路径不应再依赖 ```tool 文本解析。

---

## 3. Local-first：OpenClaw -> Native 的拦截（已接入）

实现位置：`apiserver/agentic_tool_loop.py::_execute_openclaw_call()` + `apiserver/native_tools.py::NativeToolExecutor.maybe_intercept_openclaw_call()`

执行顺序：
1. 收到 `agentType=openclaw` 的调用（通常是 message/cron/reminder）
2. 调用 `maybe_intercept_openclaw_call(...)`
3. 若返回 intercepted_call：
   - 直接走 `native_executor.execute(...)`
   - 并保留原始 openclaw call 到结果的 `tool_call` 字段（便于诊断）
4. 若不命中拦截：才真正转发到 `agent_server` 的 `/openclaw/send`

拦截原则：
- 有明显“联网/浏览器/网址”等 remote marker 时：**不拦截**（保持 openclaw）
- 能在项目沙盒内完成的：尽量拦截为 native

---

## 4. 修复记录：cwd/pwd 拦截必失败 -> get_cwd

### 4.1 问题
在 `maybe_intercept_openclaw_call()` 中，`cwd/pwd/当前工作目录` 曾被映射为：

- `agentType: native`
- `tool_name: run_cmd`
- `command: cd`

但 `system/native_executor.py` 明确禁止 `cd/chdir/pushd/popd` 这类流程控制 token（安全策略的一部分），因此该拦截 **理论上必然失败**。

### 4.2 修复
新增 native 工具：`get_cwd`

- 语义：返回 native 沙盒的“工作目录”（当前设计下等同项目根目录 `project_root`）
- 实现：纯 Python 返回路径字符串，不走 shell

并将拦截改为：
- `tool_name: get_cwd`

### 4.3 验收方式
1. 触发 openclaw message："pwd" / "当前工作目录"
2. 期望日志出现：`local-first拦截OpenClaw调用，改为native执行: get_cwd`
3. 返回结果应为项目根目录路径（形如 `E:/Programs/NagaAgent`）
4. 不应再出现 `Blocked shell token: cd`

---

## 5. 风险与约束

- `get_cwd` 返回的是沙盒语义下的 cwd（项目根）。如果未来引入“可变工作目录”，应优先在 native executor 内部维护 state，而不是开放 `cd`。
- Local-first 的拦截应始终服从 `NativeExecutor` 的安全边界：
  - 目录 confinement
  - 高危命令拦截
  - 对删除/清空/递归类操作要求更严格确认

---

## 6. 相关文件索引

- 结构化 tool_calls 产出：`apiserver/llm_service.py`
- tool loop 执行与回注：`apiserver/agentic_tool_loop.py`
- local-first 拦截与 native 执行：`apiserver/native_tools.py`
- native 安全边界：`system/native_executor.py`
- 文档索引：`doc/README.md`
