# 01 模块总览

## 1. 目标

本文件描述 NagaAgent 的运行时架构与模块边界，覆盖：

- 服务启动链路
- 模块间调用关系
- 端口分配与通信方式
- 打包与发布路径

## 2. 顶层结构

核心目录（按职责分层）：

- `main.py`
  - 后端总入口，统一启动 API/Agent/MCP/TTS 等服务线程。
- `system/`
  - 配置、日志、环境检查、背景意图分析、技能管理。
- `apiserver/`
  - 面向前端的主 API，包含聊天流、会话、上传、记忆、技能市场等接口。
- `agentserver/`
  - OpenClaw 与任务调度服务，承接需要执行工具/自动化的任务。
- `mcpserver/`
  - MCP 工具注册与统一调度服务，支持独立 HTTP 调用与进程内调用。
- `summer_memory/`
  - GRAG 记忆体系、五元组抽取、Neo4j/文件存储与检索。
- `guide_engine/`
  - 游戏攻略问答、RAG 上下文、计算服务、截图注入能力。
- `voice/`
  - 语音输入输出（TTS/ASR/实时语音）相关实现。
- `frontend/`
  - Electron + Vue 桌面端。
- `scripts/`
  - 构建与工具脚本（如 Windows 打包脚本）。

## 3. 运行时调用链

### 3.1 服务启动链路

1. `main.py` 创建 `ServiceManager` 并执行 `start_all_servers`。
2. 按配置与端口可用性启动：
   - API 服务（`apiserver`）
   - MCP 服务（`mcpserver`）
   - Agent 服务（`agentserver`）
   - TTS 服务（`voice`）
3. 后台异步循环维持记忆/任务等服务状态。

关键入口：

- `main.py:91` `class ServiceManager`
- `main.py:144` `def start_all_servers`
- `main.py:278` `def _start_api_server`
- `main.py:302` `def _start_mcp_server`
- `main.py:324` `def _start_agent_server`
- `main.py:346` `def _start_tts_server`

### 3.2 前端到后端链路

1. Electron 主进程启动后端子进程（开发态 Python、打包态 `naga-backend.exe`）。
2. 渲染进程通过本地 HTTP（默认 `http://localhost:8000`）访问 API。
3. API 根据任务类型转发到 Agent/MCP 或内存模块。

关键入口：

- `frontend/electron/main.ts:45` `startBackend()`
- `frontend/electron/modules/backend.ts:60` 打包态从 `process.resourcesPath/backend` 拉起后端
- `frontend/src/api/index.ts:27` 前端 API 基址 `http://localhost:${port}`
- `frontend/src/api/core.ts:396` 默认端口 `8000`

### 3.3 聊天与工具调用链路

1. 前端请求 `POST /chat/stream`。
2. `apiserver` 进行上下文拼装、记忆注入、模型调用。
3. 通过 `agentic_tool_loop` 执行多轮工具调用。
4. 工具调用可走：
   - `mcpserver`（MCP 工具）
   - `agentserver`（OpenClaw 执行）
5. 结果回流到 API 流式输出给前端。

关键入口：

- `apiserver/api_server.py:856` `@app.post("/chat/stream")`
- `apiserver/api_server.py:969` `run_agentic_loop`
- `mcpserver/mcp_server.py:65` `@app.post("/schedule")`
- `agentserver/agent_server.py:449` `@app.post("/schedule")`
- `agentserver/agent_server.py:855` `@app.post("/openclaw/send")`

## 4. 端口与通信

默认端口定义来自 `system/config.py`：

- API Server: `8000`
- Agent Server: `8001`
- MCP Server: `8003`
- TTS Server: `5048`
- ASR Server: `5060`

关键位置：

- `system/config.py:23`
- `system/config.py:26`
- `system/config.py:29`
- `system/config.py:32`
- `system/config.py:35`

## 5. 前端结构摘要

前端技术栈：Vue 3 + TypeScript + PrimeVue + Electron。

核心路由：

- `/` 面板页
- `/chat` 对话页
- `/model` 模型配置页
- `/memory` 记忆配置页
- `/mind` 可视化页
- `/skill` 技能工坊页
- `/config` 终端配置页

关键位置：

- `frontend/src/main.ts:13` `createWebHashHistory`
- `frontend/src/main.ts:16`
- `frontend/src/main.ts:17`
- `frontend/src/main.ts:18`
- `frontend/src/main.ts:19`
- `frontend/src/main.ts:20`
- `frontend/src/main.ts:21`

## 6. 打包与发布链路

1. `scripts/build-win.py` 先构建后端（PyInstaller）。
2. 再构建前端（`npm run dist:win`）。
3. Electron 打包时将 `dist` 和 `dist-electron` 打入安装包。

关键位置：

- `scripts/build-win.py:290` `build_backend`
- `scripts/build-win.py:324` `build_frontend`
- `frontend/package.json:15` `dist:win`
- `frontend/electron-builder.yml:10` `dist/**/*`
- `frontend/electron-builder.yml:11` `dist-electron/**/*`

## 7. 当前规模（快速量化）

- API 路由数（`apiserver/api_server.py`）：约 `48`
- Agent 路由数（`agentserver/agent_server.py`）：约 `45`
- MCP 路由数（`mcpserver/mcp_server.py`）：`4`

说明：该规模意味着前端改造时无需重写业务后端，优先做 UI 与通信层替换更稳妥。

## 8. 协议与代理（新增）

- 模型协议支持 OpenAI 兼容与 Google 原生双栈：
  - OpenAI 兼容：`openai_chat_completions`
  - Google 原生：`google_generate_content`
- Google 原生流式支持两种模式：
  - SSE：`streamGenerateContent`
  - Live API：`BidiGenerateContent`
- 系统代理支持“按配置启用 + Windows 注册表代理同步到进程环境”的组合策略，避免仅靠 `HTTP(S)_PROXY` 导致误判。

详细配置、日志解释与排障步骤参见：`doc/04-api-protocol-proxy-guide.md`。
