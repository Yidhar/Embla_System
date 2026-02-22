# 03 C++/Qt UI 改造评估（对齐 Omni-Operator）

文档状态：开发预备（As-Is + Target-Aligned）
最后更新：2026-02-22

## 1. 结论

推荐路线保持不变：

1. 保留当前 Python 后端（`apiserver` + `mcpserver` + `autonomous` 等）。
2. 用 Qt 重写前端壳层与 UI。
3. 通过 BFF 事件流（SSE）对接，而不是重写后端执行链。

不建议在同一阶段推进“前端 Qt + 后端全量 C++重写”。

## 2. 与 Omni-Operator 的对齐视角

### 2.1 当前可复用的无头后端

现有后端已经具备 Omni 入口能力：

- 单入口 BFF：`apiserver`
- 结构化事件流：`/chat/stream` 返回 `tool_calls/tool_results/tool_stage/round_*` 事件
- 工具执行治理：`agentic_tool_loop + native/mcp`
- 可选自治循环：`autonomous/system_agent.py`

这意味着 Qt 前端可以作为“纯事件消费者”接入，不必理解内部微服务拓扑。

### 2.2 Qt 对接 Event Bus 语义

当前前端在 `MessageView.vue` 已按事件类型消费流式数据。Qt 迁移时可按同样契约实现本地 Event Bus：

- 输入：SSE chunk（JSON）
- 总线事件：`content`、`reasoning`、`tool_calls`、`tool_results`、`tool_stage`、`round_start`、`round_end`
- UI 映射：消息正文、推理区、工具状态区、轮次分隔

建议在 Qt 客户端定义统一事件结构体，避免页面直接解析原始 SSE 文本。

## 3. 现状基线（需要复刻的能力）

除聊天 UI 外，当前 Electron 还承担以下桌面能力：

1. 无边框窗口控制、托盘、全局快捷键。
2. 悬浮球多状态与窗口动画。
3. 启动后端并透传启动进度。
4. 自动更新与异常恢复。
5. 截图与媒体相关交互。

这部分不在 Omni 后端内，需要 Qt 壳层自行实现或阶段性降级。

## 4. 分阶段实施建议（与 Omni 对齐）

### Phase 0：契约冻结

- 冻结 `/chat/stream` 事件协议与字段含义。
- 冻结 BFF 请求入口（`/chat`、`/sessions`、`/config`、`/tts/speech`）。
- 明确“兼容保留接口”不作为 Qt 首期依赖（例如 Agent legacy 接口）。

### Phase 1：Qt MVP（业务可用）

- 完成登录/对话/配置三条主流程。
- 完成 SSE 事件解析与工具状态展示。
- 优先保证与现有 BFF 对齐，不增加后端分支逻辑。

### Phase 2：桌面能力补齐

- 托盘、快捷键、截图、开机自启。
- 后端启动器与健康检查 UI。
- 悬浮窗能力分层接入。

### Phase 3：高级能力与体验拉齐

- 意识海、技能工坊等复杂页面。
- Live2D（若纳入本期）采用独立风险评估。

## 5. 风险矩阵（更新）

高风险：

- 悬浮球与无边框窗口行为复刻。
- Live2D 渲染链迁移。
- 自动更新链路替换。

中风险：

- SSE 事件与断线重连策略。
- 多环境 API 地址切换（本地/Electron/远端）。

低风险：

- 普通配置页、列表页、表单页迁移。

## 6. 开发预备建议

1. 将前端事件协议整理为独立契约文档（建议在 `frontend/src/utils/encoding.ts` 的类型基础上抽出 schema）。
2. 在后端保持“BFF 单入口 + 内部服务替换自由”，避免 Qt 直接绑定内部端口。
3. 把 Qt 改造纳入 `08` 文档的前后端分离里程碑，按阶段验收。

## 7. 交叉引用

- 总览：`./01-module-overview.md`
- 模块归档：`./02-module-archive.md`
- 启动与调试：`./05-dev-startup-and-index.md`
- 前后端分离：`./08-frontend-backend-separation-plan.md`
