# 01 模块总览（Embla System 开发预备版）

文档状态：开发预备（As-Is + Target-Aligned）
最后更新：2026-02-28

## 1. 目标

注：文中出现 `autonomous/*` 仅表示归档实现，不进入当前运行时主链。

本文用于统一 Embla System 当前可运行架构与目标架构的语义映射。

本文件只描述 **当前代码已实现** 的运行链路，并将目标态映射到三层模型：

- Brainstem（控制与接入层）
- Brain（策略与推理层）
- Limbs（工具与执行层）

## 2. 顶层模块（当前状态）

- `main.py`：后端总入口，负责服务编排与生命周期管理。
- `system/`：配置、日志、系统检查、提示词、基础策略工具。
- `apiserver/`：统一 BFF（前后端唯一入口），提供 REST/SSE。
- `autonomous/`（archived/legacy）：历史 System Agent 自治闭环实现（已退役，保留文档追溯）。
- `mcpserver/`：MCP Host + Tool Registry + 外部 mcporter 接入。
- `summer_memory/`：GRAG 记忆、五元组抽取、Neo4j 检索。
- `Embla_core/`：Next.js 运维与调试前端（当前主链前端）。
- `scripts/`：构建与发布脚本。

状态标签约定：

- `已实现`：代码路径可直接运行。
- `归档态`：历史实现仅用于追溯，不进入运行时主链。

## 3. 服务启动链路（As-Is）

当前 `main.py` 的 `start_all_servers` 行为：

1. 启动 API 服务（`apiserver`，默认端口 `8000`）。
2. 启动 MCP 服务（`mcpserver`，默认端口 `8003`）。
3. 后台事件循环按 `config.autonomous.enabled` 条件启动 `agents/pipeline.py`。

端口默认值来源：`system/config.py`（`ServerPortsConfig`）。

- API: `8000`
- MCP: `8003`
- LLM 调试服务（可选）: `8001`（`apiserver/start_server.py llm`，不在 `main.py` 默认启动链）

## 4. 运行时调用链路（As-Is）

### 4.1 聊天主链路

1. 前端请求 `POST /chat/stream`（`apiserver`）。
2. `apiserver/api_server.py` 先执行聊天路由治理（route quality / arbiter / session state），随后进入 `agents/pipeline.py::run_multi_agent_pipeline`。
3. Pipeline 先由 `ShellAgent` 进行语义路由（`route_semantic`）：
   - `shell_readonly`：Shell 直接回答（只读链路）。
   - `shell_clarify`：Shell 发起澄清并保持只读链路。
   - `core_execution`：通过 `dispatch_to_core` 进入 Core/Expert 执行编排并生成 `execution_receipt`。
4. 执行态工具循环的规范实现位于 `agents/tool_loop.py`（canonical）。
5. SSE 回推统一结构化事件到前端（`route_decision` / `tool_stage` / `execution_receipt` / `content` / `pipeline_end` 等）。

其中 `execution_receipt` 是 `core_execution` 路径的最终结构化回执，当前 canonical 口径为：

- `submitted_completion`：所有 Dev 已合法提交 `completed`，且每个 Expert 的最终 Review 结论均为 `approve`。
- `completion_not_submitted`：至少一个 Dev 没有提交合法完成态。
- `review_missing`：预期应有 Review，但未收到最终生效结论。
- `review_requested_changes`：流程停留在返修态，最终未收敛到通过。
- `review_rejected`：最终审查未通过，或已被 Expert 升级为 `blocked`。

中间态审查结果会通过 `review_result` / `review_rework_requested` / `review_reject_respawn` / `expert_blocked` 等事件暴露；`execution_receipt` 只汇总每个 Expert **最终生效**的审查结论，不把中间 `request_changes` 或可恢复 `reject` 视为最终通过结果。

### 4.2 MCP 运行态说明

当前链路状态：

- `main.py` 会启动独立 `mcpserver`。
- `apiserver` 的 `/mcp/status`、`/mcp/tasks` 输出运行态快照（对齐前端 status/tasks 展示口径）。
- `apiserver` 的 `/mcp/services`、`/mcp/import` 提供服务发现与导入管理能力。

## 5. Embla System 三层映射（开发预备语义）

### 5.1 Brainstem（控制与接入层）

当前落点：

- `main.py`（服务编排）
- `system/config.py`（统一配置）
- `apiserver/`（BFF 入口）
- `agents/pipeline.py`（单活自治控制）
  - 已支持可配置子代理运行控制（`subagent_runtime.enabled`）。

说明：Legacy `agentserver` 旧执行链已移出仓库，不再作为控制面路径。

### 5.2 Brain（策略与推理层）

当前落点：

- `apiserver/llm_service.py`（LLM client 与路由）
- `agents/pipeline.py`（Shell/Core 多代理编排主入口）
- `agents/tool_loop.py`（canonical 工具循环）
- `summer_memory/`（记忆检索）

### 5.3 Limbs（工具与执行层）

当前落点：

- `apiserver/native_tools.py` + `system/native_executor.py`
- `mcpserver/mcp_registry.py` + `mcpserver/mcp_manager.py`
- `agents/runtime/mini_loop.py`（子代理依赖调度、契约协商前置与统一提交）
- `autonomous/scaffold_engine.py`（archived/legacy）（契约门禁 + verify pipeline + 多文件事务回滚）

## 6. Legacy AgentServer 状态（已移除）

**当前状态**：
- `agentserver/` 目录已不在当前仓库
- 运行主链不再包含 AgentServer 启动与调用面
- 相关语义仅保留在历史任务文档与归档记录中

**弃用原因**：
- OpenClaw 旧执行链路已被 `apiserver + agents/pipeline + agents/tool_loop + native/mcp` 主链替代
- 架构简化：减少服务依赖，统一执行入口

**替代方案**：
- 工具调用：`agents/tool_loop.py`（canonical） + `native_tools.py` / `mcp_manager.py`
- 自治执行：`agents/pipeline.py` + `agents/tool_loop.py`（内生执行桥）

**注意**：
- 新增能力应走 `apiserver + agents/pipeline + agents/tool_loop + native/mcp` 主链
- 历史文档若仍出现 `agentserver/` 路径，按“归档语义”理解，不代表当前可运行模块

## 7. 与目标态差距（简版）

- Tool Contract 仍以运行时约定为主，尚未在所有调用面强制结构化字段（如 `risk_level`、`trace_id`、`input_schema_version`）。
- BFF 内 MCP 快照语义与底层 `mcpserver` 状态仍需持续做口径对齐。
- 多租户、完整治理策略（详见 10/11/12 与 `00-omni-operator-architecture.md`）尚未完整落地。
- Token 经济学控制仍偏“策略约束”，尚未在网关层形成 4 重硬门禁（缓存分层、模型分流、I/O 熔断、事件驱动休眠）。
- 多 Agent 并发安全墙已完成基础落地（乐观锁/全局互斥/仲裁熔断/事务回滚），但仍需 Phase 3 全量联调与长稳验证。

## 8. 系统落地最高原则（新增）

在 Embla System 开发生命周期中，统一采用以下反直觉原则：

- `逻辑并发，执行串行（Logical Concurrency, Serial Execution）`

解释：

- 允许多个 Agent 并发“思考、读文档、只读分析”。
- 所有会改变物理宿主机状态的动作（写文件、装依赖、启停服务、Git 变更）必须经 Event Bus 串行排队执行。
- 该规则同时服务于稳定性与成本目标：避免主机状态雪崩与无效重试导致的 Token 放大。

## 9. 交叉引用

- 模块归档：`./02-module-archive.md`
- 模型协议与代理：`./04-api-protocol-proxy-guide.md`
- 启动与开发环境：`./05-dev-startup-and-index.md`
- 工具调用管线：`./06-structured-tool-calls-and-local-first-native.md`
- 自治 SDLC（历史归档）：`./07-archived-autonomous-agent-sdlc-architecture.md`
- 前后端分离：`./08-frontend-backend-separation-plan.md`
- 工具治理规范：`./09-tool-execution-specification.md`
- 目标架构蓝图（仅目标态参考）：`./00-omni-operator-architecture.md`、`./10-brainstem-layer-modules.md`、`./11-brain-layer-modules.md`、`./12-limbs-layer-modules.md`
- 安全盲区与加固基线：`./13-security-blindspots-and-hardening.md`
