# 08 前后端分离方案（Embla System 入口对齐版）

文档状态：开发预备（As-Is + Target-Aligned）
最后更新：2026-02-28

## 1. 现状结论（As-Is）

当前项目已经具备“单入口 BFF + 事件流”雏形，但仍存在过渡态漂移。

### 1.1 已落地能力

1. 前端 API 基址支持 `NEXT_PUBLIC_API_BASE`，默认回退同源路径。
2. 聊天主链路通过 `POST /chat/stream` 消费结构化 SSE 事件。
3. `Embla_core` 调试控制台通过 `POST /v1/chat/stream` 消费 SSE（`content/reasoning/route_decision`）。
4. 运维看板已通过 BFF 聚合接口消费运行态数据（`/v1/ops/*`）。

### 1.2 仍在过渡的点

1. 前端与后端仍同仓库协同开发，发布边界尚未完全独立。
2. `apiserver` 的 MCP 状态接口为“运行态快照语义”，仍与底层 `mcpserver` 状态并行存在。
3. 历史 `frontend/voice/agentserver` 目录已移除，但旧文档仍有残留引用。

## 2. Embla System 对齐目标

目标是把 `apiserver` 明确为 Embla System 入口层（BFF），并把前端与内部服务解耦：

- 前端只依赖 BFF 契约与事件流
- BFF 内部可自由替换 `mcpserver`、`autonomous`、`memory` 细节
- 事件流语义稳定，UI 不绑定具体执行器实现

## 3. 目标边界（统一语义）

### 3.1 外部边界

前端可见接口：

- 对话：`/chat`、`/chat/stream`
- 会话：`/sessions/*`
- 配置：`/config/*` 或对应系统配置接口
- 工具集成：`/mcp/services`、`/mcp/import`（经 BFF 暴露）
- 运行态：`/v1/ops/*`

### 3.2 内部边界

BFF 内部编排：

- 工具调用：`agentic_tool_loop -> native/mcp`
- 记忆检索：`summer_memory`
- 自治执行：`autonomous`

## 4. 分阶段实施路径

### Phase 0：契约冻结

1. 固化 `chat/stream` 事件 schema。
2. 固化 BFF 对前端的错误码与响应结构。
3. 在文档中标记兼容接口与弃用接口。

### Phase 1：入口收敛

1. 前端调用只走 BFF，不直连内部服务端口。
2. 清理前端遗留的 Agent 直连依赖（如仅剩配置透传的冗余链路）。
3. 收敛 MCP 状态接口语义，避免“运行快照”与“底层服务状态”混淆。

### Phase 2：事件总线化

1. 把 SSE 事件定义为稳定“前端事件总线协议”。
2. 对关键事件补齐版本号与 schema 校验。
3. 支持多前端（Electron/Qt/Web）复用同一协议。

### Phase 3：部署解耦

1. 前端静态部署与 BFF 独立部署。
2. 内部服务改为可替换组件，不影响外部 API。
3. CORS 和鉴权收敛到生产可部署策略。

## 5. 风险与控制

主要风险：

- SSE 在反向代理链路被缓冲。
- 兼容接口清理不彻底导致隐式回退。
- 文档与实际行为再次漂移。

控制措施：

1. 为 `chat/stream` 增加代理层回归测试。
2. 每次接口改动同步更新 `01/02/08/09`。
3. 对“兼容保留”接口标记下线里程碑。

## 6. 开发预备检查项

1. 前端是否仅依赖 `API_BASE_URL`。
2. 是否仍存在业务直连 `localhost:xxxx` 子服务。
3. SSE 事件是否可被独立解析并稳定渲染。
4. MCP/OPS 状态接口是否语义一致。

## 7. 并发落地黄金法则（新增）

前后端分离实施必须遵守：

- `逻辑并发，执行串行`

具体要求：

1. 允许 Router 并发派生“读文档、读代码、方案评审”子任务。
2. 所有会改变宿主机状态的动作，必须进入 Event Bus 串行执行队列。
3. 队列内动作至少包含：写文件、安装依赖、切换分支、启停服务。

该规则是防止系统崩溃与 Token 雪崩的最后防线。

## 8. 交叉引用

- 总览：`./01-module-overview.md`
- 模块归档：`./02-module-archive.md`
- Qt 改造：`./03-qt-migration-assessment.md`
- 工具管线：`./06-structured-tool-calls-and-local-first-native.md`
- 工具治理：`./09-tool-execution-specification.md`
