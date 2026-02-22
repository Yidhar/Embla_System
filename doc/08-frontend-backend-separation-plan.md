# 08 前后端分离改造方案（基于当前代码审阅）

## 1. 审阅结论（现状）

本结论基于当前仓库代码，不是泛化方案。

### 1.1 当前运行形态

- 桌面端主路径是 Electron 主进程拉起 Python 后端子进程，见 `frontend/electron/main.ts:45`、`frontend/electron/modules/backend.ts:178`。
- 后端由 `main.py` 统一编排多服务线程启动，见 `main.py:200`、`main.py:528`。
- 前端 API 客户端默认固定到本机 `localhost` 端口，见 `frontend/src/api/index.ts:27`、`frontend/src/api/core.ts:449`。

### 1.2 已识别的前后端耦合点

1. 启动耦合（Electron <-> Backend 强耦合）
- Electron 负责后端进程生命周期与端口引导，见 `frontend/electron/modules/backend.ts:34`、`frontend/electron/modules/backend.ts:142`、`frontend/electron/main.ts:124`。
- 前端在 `config.ts` 监听 Electron 进度事件并覆盖 API 端口，见 `frontend/src/utils/config.ts:331`、`frontend/src/utils/config.ts:336`、`frontend/src/utils/config.ts:357`。

2. 网络耦合（前端硬编码本地地址）
- API 基址固定 `http://localhost:${port}`，见 `frontend/src/api/index.ts:27`。
- TTS 直接打本地语音服务端口，绕过 API 层，见 `frontend/src/utils/tts.ts:13`。

3. 边界耦合（BFF 与业务编排混在 `apiserver`）
- `apiserver` 同时承载聊天、配置、上传、MCP 接入、AgentServer 转发等职责，路由规模较大（46 个）。
- 对 `agentserver` 采用本地 HTTP 转发，见 `apiserver/api_server.py:128`、`apiserver/api_server.py:140`。
- 存在 API 内部对自身 `localhost` 回环调用，见 `apiserver/api_server.py:2080`、`apiserver/api_server.py:2115`、`apiserver/api_server.py:2155`。

4. 架构漂移（服务状态描述与行为不一致）
- `main.py` 会启动 MCP 服务线程，见 `main.py:229`、`main.py:528`。
- `apiserver` 中 MCP 代理注释标注为“已移除”，并返回离线占位结果，见 `apiserver/api_server.py:1134`、`apiserver/api_server.py:1147`、`apiserver/api_server.py:1159`。

5. Agent 侧半解耦状态
- `main.py` 将 Agent(AgentServer) 标记为“已禁用自动启动”，见 `main.py:237`。
- 但前端仍保留 `agent.ts` 客户端与端口配置逻辑，见 `frontend/src/api/agent.ts:62`、`frontend/src/utils/config.ts:2`、`frontend/src/utils/config.ts:360`。
- `agent.ts` 里声明了 `/tools`、`/toolkits` 等接口，见 `frontend/src/api/agent.ts:15`、`frontend/src/api/agent.ts:23`；当前前端业务并未实际引用该客户端（仅 `config.ts` 调端口 setter）。

6. 配置模型与配置文件不完全同构
- `config.json` 含 `agentserver` / `mcpserver` 节点，但 `NagaConfig` 仅显式声明 `api_server`，未知字段按 `extra=ignore` 忽略，见 `system/config.py:857`、`system/config.py:862`、`system/config.py:890`。
- 目前主要通过 `_sync_server_ports_from_config_data` 抽取端口，见 `system/config.py:70`、`system/config.py:80`、`system/config.py:86`。

7. 安全与部署边界仍偏本地模式
- CORS 使用 `allow_origins=["*"]`，见 `apiserver/api_server.py:105`、`mcpserver/mcp_server.py:42`。
- 认证为 local-only 占位实现，远端 auth 入口返回 410，见 `apiserver/api_server.py:489`、`apiserver/api_server.py:492`、`apiserver/api_server.py:523`、`apiserver/naga_auth.py:1`。

## 2. 目标分离方案（推荐）

推荐采用：**单入口 BFF + 内部服务分层**，而不是一步到位全微服务公开化。

### 2.1 目标拓扑

- 前端层：`frontend`（Web/Electron 共用同一 API 协议）
- 入口层：`apiserver` 作为唯一外部入口（BFF）
- 领域层：
  - 对话与编排：`apiserver` + `agentic_tool_loop`
  - 工具执行：`mcpserver`（内部调用）
  - 任务调度与 AgentServer：`agentserver`（内部调用）
  - 记忆：`summer_memory`
  - 语音：`voice`
- 运维层：统一日志、指标、追踪、鉴权

### 2.2 边界原则

1. 前端只访问一个 `API_BASE_URL`
- 禁止前端直接请求 `agentserver`、`mcpserver`、`tts` 端口。
- 包括 TTS 也改为走 API 代理或统一媒体网关。

2. Electron 只做壳，不做业务编排
- Electron 可保留“本地开发便捷启动后端”能力。
- 生产协议上，前端不依赖 Electron 才能获取 API 地址。

3. API 契约先行
- 先冻结 `apiserver` 对前端契约（OpenAPI/JSON Schema）。
- 再做内部服务重排，避免前端频繁改动。

## 3. 分阶段实施路径

## Phase 0：契约基线与解耦准备（低风险）

目标：不改业务行为，先断开硬编码和壳依赖。

- 前端 API 基址参数化
  - 在前端引入 `VITE_API_BASE_URL`（默认 `http://localhost:8000`）。
  - `frontend/src/api/index.ts` 改为优先读取运行时 base URL，再回退端口模式。
- 移除前端对 `agentApiPort` 的依赖链
  - `frontend/src/utils/config.ts` 不再设置 `setAgentApiPort`。
  - 清理 `frontend/src/api/agent.ts`（若确认无使用）。
- TTS 改走 API 入口
  - 将 `frontend/src/utils/tts.ts:13` 的直连改为 `apiserver` 路由（如 `/tts/speech`）。
- 文档与配置一致性修复
  - 明确 `agentserver/mcpserver` 在配置模型中的地位（纳入 typed config 或移除冗余键）。

验收标准：
- `npm run dev:web` 可在无 Electron 情况下直连远端 API。
- 前端不再出现任何 `localhost:xxxx` 业务直连（静态资源除外）。

## Phase 1：BFF 契约稳定化

目标：把“前端需要的接口”收拢成稳定边界。

- 给外部接口统一前缀（建议 `/api/v1`），保留兼容别名一段时间。
- 统一响应结构与错误码（至少覆盖 chat/stream、session、config、skill/mcp）。
- 将 AgentServer / MCP 的前端查询接口固定为 BFF 聚合接口，前端不感知后端细分服务。
- 梳理并删除“离线占位”与“已移除但仍在运行”的冲突逻辑（MCP 相关）。

验收标准：
- 前端接口仅依赖 `apiserver`。
- 开发、测试、生产三套环境仅通过 base URL 切换，无代码条件分支。

## Phase 2：内部服务解耦与替换能力

目标：让 `agentserver` / `mcpserver` 成为可替换内部能力，而不是前端协议一部分。

- 在 `apiserver` 内定义 `AgentGateway`、`McpGateway` 适配层。
- 替换 API 内部 `localhost` 回环调用为函数调用或内网调用（避免自调用网络开销与故障面扩大）。
- 明确同步/异步边界：
  - 长任务走任务 ID + 状态查询
  - 实时流保持 SSE 单向

验收标准：
- `apiserver` 可在单体模式与分布式模式切换（配置驱动）。
- 关闭 `agentserver` / `mcpserver` 时，BFF 行为可预测（可降级、可观测）。

## Phase 3：部署与安全收口

目标：支持真正的“前后端独立部署”。

- 生产部署建议：
  - 前端静态资源（Nginx/CDN）
  - `apiserver` 独立容器
  - `agentserver` / `mcpserver` 作为内网服务
- CORS 从 `*` 收敛为白名单域名。
- 鉴权策略从 local-only 占位升级为可部署认证（JWT/Session + refresh）。
- 秘钥外置：禁止 `config.json` 明文密钥进入仓库或镜像。

验收标准：
- 前端可由任意域名访问 BFF（在白名单内）。
- 无需 Electron 也可完整使用主要功能。

## 4. 建议的接口边界（示例）

保持一个入口域名，例如 `https://api.naga.example.com`。

- `POST /api/v1/chat`
- `POST /api/v1/chat/stream`（SSE）
- `GET /api/v1/sessions`
- `GET /api/v1/sessions/{id}`
- `DELETE /api/v1/sessions/{id}`
- `GET /api/v1/system/config`
- `POST /api/v1/system/config`
- `GET /api/v1/tools/status`
- `GET /api/v1/integrations/mcp/services`
- `POST /api/v1/integrations/mcp/import`
- `POST /api/v1/tts/speech`

说明：
- 这不是要求你立刻重命名所有现有路由，而是建议通过兼容层逐步迁移。

## 5. 风险与回滚

主要风险：
- 聊天流（SSE）在反向代理链路被缓冲。
- 现有本地化假设较多（localhost、自启动、local-only auth）。
- AgentServer/MCP 当前处于过渡态，接口语义不完全稳定。

回滚策略：
- 路由级开关：新旧前缀并行一段时间。
- 保留旧前端 API 客户端一版作为 fallback（短期）。
- 关键链路先灰度（chat stream、session、tts）。

## 6. 本次审阅给出的优先改造清单（按性价比排序）

1. 前端 API 基址去 `localhost` 硬编码（最高优先）。
2. TTS 直连端口改为 BFF 代理。
3. 清理未使用的 `agent.ts` 客户端与 `agentPort` 透传链路。
4. 统一 MCP 真实运行策略（去掉“注释说移除、实际仍启动”的漂移）。
5. 让 `config` 模型与 `config.json` 字段同构，消除隐式端口同步黑箱。
6. 收敛 CORS 与认证策略，准备跨域部署。


