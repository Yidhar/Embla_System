# 02 模块归档明细（Embla_system 开发预备版）

文档状态：开发预备（As-Is + Target-Aligned）
最后更新：2026-02-22

## 1. 归档规则

本归档按“模块职责 + 当前状态 + Embla_system 对齐”统一表达。

状态标签：

- `已实现`：当前代码可直接运行。
- `过渡态`：行为可用但接口语义尚未收敛。
- `兼容保留`：仅为历史兼容存在，不建议新功能依赖。
- `目标态`：来自 Embla_system 蓝图，当前未完全落地。

## 2. Embla_system 集成层（新增）

Embla_system 在当前项目的集成层由三块组成：

1. BFF 入口：`apiserver/`
2. MCP Host + Tool Registry：`mcpserver/`
3. 自治控制代理：`autonomous/`

该集成层负责把前端请求、模型调用、工具执行与自治闭环收敛到统一控制面。

## 3. 模块归档清单

### 3.1 启动编排

模块：`main.py`（`已实现`）

- 职责：统一启动 API/MCP/TTS、后台循环、代理环境、可选自治循环。
- 关键事实：AgentServer 已标记“禁用自动启动”。
- Embla_system 对齐：承担 Brainstem 的运行时编排职责。

### 3.2 系统基础能力

模块：`system/`（`已实现`）

- 职责：配置模型、日志、提示词、系统检测、Native 执行安全边界。
- 关键文件：`system/config.py`、`system/native_executor.py`。
- Embla_system 对齐：作为 Brainstem 的配置与安全基座。

### 3.3 BFF 与对话编排

模块：`apiserver/`（`已实现`，部分 `过渡态`）

- 职责：对外 REST/SSE 入口，`/chat/stream` 工具循环编排。
- 关键文件：`apiserver/api_server.py`、`apiserver/agentic_tool_loop.py`、`apiserver/llm_service.py`。
- 过渡点：`/mcp/status`、`/mcp/tasks` 仍是离线占位语义。
- Embla_system 对齐：Brainstem 入口 + Brain 编排核心。

### 3.4 自治系统代理（新增归档）

模块：`autonomous/`（`已实现`，持续增强中）

- 职责：System Agent 循环、任务编排、事件日志、命令幂等、发布治理。
- 已有能力：
  - lease/fencing 单活控制
  - outbox/inbox 去重分发
  - canary 判定与自动回滚
  - Verifying 阶段统一结构化门禁与重试决策（legacy 外部降级已退役）
- 关键文件：
  - `autonomous/system_agent.py`
  - `autonomous/state/workflow_store.py`
  - `autonomous/event_log/event_store.py`
  - `autonomous/release/controller.py`
- Embla_system 对齐：Brainstem 控制器与治理执行枢纽。

### 3.5 MCP 主机与注册中心

模块：`mcpserver/`（`已实现`）

- 职责：manifest 扫描注册、统一调用入口、本地优先/外部兜底。
- 关键文件：`mcpserver/mcp_registry.py`、`mcpserver/mcp_manager.py`、`mcpserver/mcp_server.py`。
- Embla_system 对齐：Limbs 侧工具网关（Tool Registry）。

### 3.6 AgentServer（降级）

模块：`agentserver/`（`兼容保留`）

- 现状：
  - `/schedule` 与 `/analyze_and_execute` 已返回 `deprecated`。
  - 主要剩余价值是任务/会话内存查询与管理。
- 结论：OpenClaw 旧执行路径视为弃用，不再作为主执行链路。
- Embla_system 对齐：仅保留兼容接口，不纳入新架构主链。

### 3.7 记忆与图谱

模块：`summer_memory/`（`已实现`）

- 职责：五元组抽取、记忆检索、Neo4j 与文件存储。
- Embla_system 对齐：Brain 的知识与检索支撑层。

### 3.8 领域引擎

模块：`guide_engine/`（`已实现`）

- 职责：游戏问答路由、RAG、计算服务。
- Embla_system 对齐：Brain 的领域技能子系统。

### 3.9 语音能力

模块：`voice/`（`已实现`）

- 职责：TTS/ASR/实时语音输入输出。
- Embla_system 对齐：Limbs 侧多模态执行通道。

### 3.10 前端桌面层

模块：`frontend/`（`已实现`，持续解耦中）

- 职责：Electron 壳层 + Vue UI。
- 关键事实：聊天流已消费结构化 SSE 事件；API 基址支持 `VITE_API_BASE_URL`。
- Embla_system 对齐：作为 BFF 的事件消费者，逐步向事件总线语义靠拢。

### 3.11 构建与发布

模块：`scripts/`（`已实现`）

- 职责：Windows 构建与打包链路。
- Embla_system 对齐：工程交付层，不参与运行时编排。

## 4. 模块关系（统一语义）

1. `frontend` 仅面向 `apiserver`（BFF）进行调用。
2. `apiserver` 负责编排 `native tools`、`mcpserver`、`summer_memory`、`guide_engine`。
3. `autonomous` 在后台循环中执行自治任务与发布治理。
4. `mcpserver` 提供工具注册和统一分发能力。
5. `agentserver` 仅提供兼容查询接口，不承担主执行。

## 5. 开发预备差距

- 需将 Tool Contract 字段从“约定”升级为“强制校验”。
- 需收敛 MCP 相关占位接口与真实运行状态描述。
- 需持续将目标态模块（见 10/11/12）拆解为可交付增量。

## 6. 交叉引用

- 总览：`./01-module-overview.md`
- 启动与环境：`./05-dev-startup-and-index.md`
- 工具调用管线：`./06-structured-tool-calls-and-local-first-native.md`
- 自治 SDLC：`./07-autonomous-agent-sdlc-architecture.md`
