# 02 模块归档明细（Embla_system 开发预备版）

文档状态：开发预备（As-Is + Target-Aligned）
最后更新：2026-02-28

## 1. 归档规则


> Migration Note (archived/legacy)
> 文中 `autonomous/*` 路径属于历史实现标识；当前实现请优先使用 `agents/*`、`core/*` 与 `config/autonomous_runtime.yaml`。

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
3. 自治控制代理（历史实现归档）：`autonomous/`（archived/legacy）

该集成层负责把前端请求、模型调用、工具执行与自治闭环收敛到统一控制面。

## 3. 模块归档清单

### 3.1 启动编排

模块：`main.py`（`已实现`）

- 职责：统一启动 API/MCP、后台循环、代理环境、可选自治循环。
- 关键事实：运行主链已收敛为 `apiserver + mcpserver + agents/core`。
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
- 过渡点：`/mcp/status`、`/mcp/tasks` 当前为快照语义，仍需与底层 `mcpserver` 状态口径持续对齐。
- Embla_system 对齐：Brainstem 入口 + Brain 编排核心。

### 3.4 自治系统代理（历史实现归档）

模块：`autonomous/`（archived/legacy，目录已退役）

- 职责（历史）：System Agent 循环、任务编排、事件日志、命令幂等、发布治理。
- 当前承接：
  - `agents/pipeline.py`
  - `agents/runtime/workflow_store.py`
  - `core/event_bus/event_store.py`
  - `agents/release/controller.py`
- Embla_system 对齐：上述承接模块构成当前 Brainstem 控制与治理主链；`autonomous/`（archived/legacy）仅保留历史语义。

### 3.5 MCP 主机与注册中心

模块：`mcpserver/`（`已实现`）

- 职责：manifest 扫描注册、统一调用入口、本地优先/外部兜底。
- 关键文件：`mcpserver/mcp_registry.py`、`mcpserver/mcp_manager.py`、`mcpserver/mcp_server.py`。
- Embla_system 对齐：Limbs 侧工具网关（Tool Registry）。

### 3.6 Legacy AgentServer（已移除）

模块：`agentserver/`（`历史归档`）

- 现状：
  - 当前仓库已无 `agentserver/` 目录。
  - 相关内容仅保留在任务实现文档/迁移 runbook 中，用于历史追溯。
- 结论：OpenClaw 旧执行路径已退出运行面，不再作为主执行链路。
- Embla_system 对齐：不纳入当前主链。

### 3.7 记忆与图谱

模块：`summer_memory/`（`已实现`）

- 职责：五元组抽取、记忆检索、Neo4j 与文件存储。
- Embla_system 对齐：Brain 的知识与检索支撑层。

### 3.8 领域引擎

模块：`guide_engine/`（`已实现`）

- 职责：游戏问答路由、RAG、计算服务。
- Embla_system 对齐：Brain 的领域技能子系统。

### 3.9 前端运行层

模块：`Embla_core/`（`已实现`）

- 职责：Next.js 运维与调试前端，消费 BFF 与 OPS 聚合接口。
- Embla_system 对齐：作为 Brainstem/BFF 的可视化消费端。

### 3.10 历史 UI 资产（归档说明）

模块：`frontend/`、`voice/`（`历史归档`）

- 现状：相关目录已不在当前仓库。
- 说明：文档中若出现上述路径，属于历史阶段记录，不代表当前可运行资产。

### 3.11 构建与发布

模块：`scripts/`（`已实现`）

- 职责：Windows 构建与打包链路。
- Embla_system 对齐：工程交付层，不参与运行时编排。

## 4. 模块关系（统一语义）

1. `Embla_core` 仅面向 `apiserver`（BFF）进行调用。
2. `apiserver` 负责编排 `native tools`、`mcpserver`、`summer_memory`、`guide_engine`。
3. `autonomous` 在后台循环中执行自治任务与发布治理。
4. `mcpserver` 提供工具注册和统一分发能力。
5. `agentserver/voice/frontend` 仅作为历史归档语义，不在当前运行面。

## 5. 开发预备差距

- 需将 Tool Contract 字段从“约定”升级为“强制校验”。
- 需持续收敛 MCP 快照语义与底层运行状态描述。
- 需持续将目标态模块（见 10/11/12）拆解为可交付增量。

## 6. 交叉引用

- 总览：`./01-module-overview.md`
- 启动与环境：`./05-dev-startup-and-index.md`
- 工具调用管线：`./06-structured-tool-calls-and-local-first-native.md`
- 自治 SDLC（历史归档）：`./07-archived-autonomous-agent-sdlc-architecture.md`
