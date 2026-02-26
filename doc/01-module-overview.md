# 01 模块总览（Omni-Operator 开发预备版）

文档状态：开发预备（As-Is + Target-Aligned）
最后更新：2026-02-24

## 1. 目标

本文用于统一 NagaAgent 当前可运行架构与 Omni-Operator 目标架构之间的语义。

本文件只描述 **当前代码已实现** 与 **已确认的过渡态**，并将目标态映射到三层模型：

- Brainstem（控制与接入层）
- Brain（策略与推理层）
- Limbs（工具与执行层）

## 2. 顶层模块（当前状态）

- `main.py`：后端总入口，负责服务编排与生命周期管理。
- `system/`：配置、日志、系统检查、提示词、基础策略工具。
- `apiserver/`：统一 BFF（前后端唯一入口），提供 REST/SSE。
- `autonomous/`：System Agent 自治闭环（已实现，可配置启停）。
- `mcpserver/`：MCP Host + Tool Registry + 外部 mcporter 接入。
- `agentserver/`：兼容保留层（OpenClaw/Legacy Agent 执行链已弃用）。
- `summer_memory/`：GRAG 记忆、五元组抽取、Neo4j 检索。
- `guide_engine/`：游戏攻略 RAG 与计算服务。
- `voice/`：TTS/ASR/实时语音能力。
- `frontend/`：Electron + Vue 客户端。
- `scripts/`：构建与发布脚本。

状态标签约定：

- `已实现`：代码路径可直接运行。
- `过渡态`：功能存在但与目标态有语义漂移。
- `兼容保留`：为历史接口保留，不建议新增依赖。

## 3. 服务启动链路（As-Is）

当前 `main.py` 的 `start_all_servers` 行为：

1. 启动 API 服务（`apiserver`，默认端口 `8000`）。
2. 启动 MCP 服务（`mcpserver`，默认端口 `8003`）。
3. 启动 TTS 服务（`voice`，默认端口 `5048`）。
4. **不自动启动** AgentServer（状态标记为“已禁用自动启动”）。
5. 后台事件循环按 `config.autonomous.enabled` 条件启动 `autonomous/system_agent.py`。

端口默认值来源：`system/config.py`（`ServerPortsConfig`）。

- API: `8000`
- Agent: `8001`
- MCP: `8003`
- TTS: `5048`
- ASR: `5060`

## 4. 运行时调用链路（As-Is）

### 4.1 聊天主链路

1. 前端请求 `POST /chat/stream`（`apiserver`）。
2. `apiserver/api_server.py` 进入 `run_agentic_loop`。
3. `apiserver/agentic_tool_loop.py` 只接受结构化函数调用：
   - `native_call`
   - `mcp_call`
   - `live2d_action`
4. 工具执行分发：
   - Native -> `apiserver/native_tools.py` -> `system/native_executor.py`
   - MCP -> `mcpserver/mcp_manager.py`（本地注册优先，外部 mcporter 兜底）
5. SSE 回推事件到前端（`tool_calls` / `tool_results` / `tool_stage` / `round_start` / `round_end` 等）。

### 4.2 MCP 过渡态说明

当前存在文档与行为漂移，需要明确标注：

- `main.py` 仍会启动独立 `mcpserver`。
- `apiserver` 的 `/mcp/status`、`/mcp/tasks` 返回离线占位响应（兼容 UI，非真实 MCP 运行状态）。
- `apiserver` 的 `/mcp/services`、`/mcp/import` 仍提供可用的服务管理能力。

## 5. Omni-Operator 三层映射（开发预备语义）

### 5.1 Brainstem（控制与接入层）

当前落点：

- `main.py`（服务编排）
- `system/config.py`（统一配置）
- `apiserver/`（BFF 入口）
- `autonomous/system_agent.py`（单活自治控制）
  - 已支持可配置子代理桥接（`subagent_runtime.enabled`）用于 Phase 3 渐进接管。

说明：`agentserver/` 不再是主控制路径，仅作为兼容保留。

### 5.2 Brain（策略与推理层）

当前落点：

- `apiserver/llm_service.py`（LLM client 与路由）
- `apiserver/agentic_tool_loop.py`（工具循环编排）
- `summer_memory/`（记忆检索）
- `guide_engine/`（领域策略/计算）

### 5.3 Limbs（工具与执行层）

当前落点：

- `apiserver/native_tools.py` + `system/native_executor.py`
- `mcpserver/mcp_registry.py` + `mcpserver/mcp_manager.py`
- `autonomous/tools/subagent_runtime.py`（子代理依赖调度、契约协商前置与统一提交）
- `autonomous/scaffold_engine.py`（契约门禁 + verify pipeline + 多文件事务回滚）
- `voice/` 与前端交互执行动作

## 6. AgentServer 状态（已弃用）

**当前状态**：
- 代码保留但已禁用自动启动（2026-02-20）
- `main.py` 不再自动启动 AgentServer
- Legacy 执行接口（`/schedule`、`/analyze_and_execute`）返回 `deprecated`

**弃用原因**：
- OpenClaw 旧执行链路已被 `apiserver + agentic_tool_loop + native/mcp` 主链替代
- 架构简化：减少服务依赖，统一执行入口

**替代方案**：
- 工具调用：`apiserver/agentic_tool_loop.py` + `native_tools.py` / `mcp_manager.py`
- 自治执行：`autonomous/system_agent.py` + `autonomous/tools/execution_bridge.py`（内生执行桥）

**保留原因**：
- 兼容性考虑，避免破坏性删除
- 部分历史接口可能被外部依赖

**清理计划**：
- Phase 1：标记所有接口为 deprecated（✅ 已完成）
- Phase 2：完全移除代码与配置（🟡 规划中）

**注意**：
- 新增能力应走 `apiserver + agentic_tool_loop + native/mcp` 主链
- 不建议新增对 `agentserver/` 的依赖

## 7. 与目标态差距（简版）

- Tool Contract 仍以运行时约定为主，尚未在所有调用面强制结构化字段（如 `risk_level`、`trace_id`、`input_schema_version`）。
- BFF 内仍存在部分 MCP 状态占位接口，需统一真实状态语义。
- 多租户、完整治理策略（详见 10/11/12 与 `00-omni-operator-architecture.md`）尚未完整落地。
- Token 经济学控制仍偏“策略约束”，尚未在网关层形成 4 重硬门禁（缓存分层、模型分流、I/O 熔断、事件驱动休眠）。
- 多 Agent 并发安全墙已完成基础落地（乐观锁/全局互斥/仲裁熔断/事务回滚），但仍需 Phase 3 全量联调与长稳验证。

## 8. 系统落地最高原则（新增）

在 Omni-Operator 开发生命周期中，统一采用以下反直觉原则：

- `逻辑并发，执行串行（Logical Concurrency, Serial Execution）`

解释：

- 允许多个 Agent 并发“思考、读文档、只读分析”。
- 所有会改变物理宿主机状态的动作（写文件、装依赖、启停服务、Git 变更）必须经 Event Bus 串行排队执行。
- 该规则同时服务于稳定性与成本目标：避免主机状态雪崩与无效重试导致的 Token 放大。

## 9. 交叉引用

- 模块归档：`./02-module-archive.md`
- Qt 改造评估：`./03-qt-migration-assessment.md`
- 模型协议与代理：`./04-api-protocol-proxy-guide.md`
- 启动与开发环境：`./05-dev-startup-and-index.md`
- 工具调用管线：`./06-structured-tool-calls-and-local-first-native.md`
- 自治 SDLC 对齐：`./07-autonomous-agent-sdlc-architecture.md`
- 前后端分离：`./08-frontend-backend-separation-plan.md`
- 工具治理规范：`./09-tool-execution-specification.md`
- 目标架构蓝图（仅目标态参考）：`./00-omni-operator-architecture.md`、`./10-brainstem-layer-modules.md`、`./11-brain-layer-modules.md`、`./12-limbs-layer-modules.md`
- 安全盲区与加固基线：`./13-security-blindspots-and-hardening.md`
