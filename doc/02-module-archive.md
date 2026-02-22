# 02 模块归档明细

## 1. 归档原则

本文件按“职责 -> 关键文件 -> 输入输出 -> 依赖/风险”方式归档，便于：

- 新成员快速上手
- 改造前做影响面评估
- 排障时快速定位入口

## 2. 模块清单

### 2.1 启动与运行控制

模块：`main.py`

- 职责
  - 服务编排与启动（API、Agent、MCP、TTS）。
  - 环境检查与端口占用处理。
  - 后台异步服务生命周期管理。
- 关键文件
  - `main.py`
- 输入
  - CLI 参数（如 `--headless`）。
  - `system/config.py` 配置与端口映射。
- 输出
  - 多个服务线程与监听端口。
- 风险点
  - 多服务并发启动时的端口竞争与依赖顺序问题。

### 2.2 系统基础层

模块：`system/`

- 职责
  - 配置模型、热更新、提示词管理、日志配置、环境检测、技能目录管理、背景分析分发。
- 关键文件
  - `system/config.py`
  - `system/config_manager.py`
  - `system/logging_setup.py`
  - `system/system_checker.py`
  - `system/background_analyzer.py`
  - `system/skill_manager.py`
- 输入
  - `config.json` / `config.json.example`
  - 对话上下文（用于 background analyzer）
- 输出
  - 全局配置对象与监听器回调
  - 任务分发到 API/Agent/MCP
- 风险点
  - 配置热更新与运行时对象一致性
  - 后台分析失败后的降级路径

### 2.3 API 服务层

模块：`apiserver/`

- 职责
  - 对外统一 REST/SSE 接口。
  - 聊天流、会话管理、文档上传解析、记忆查询、技能安装与系统配置接口。
- 关键文件
  - `apiserver/api_server.py`
  - `apiserver/agentic_tool_loop.py`
  - `apiserver/streaming_tool_extractor.py`
  - `apiserver/message_manager.py`
  - `apiserver/llm_service.py`
- 输入
  - 前端 HTTP 请求（默认 `localhost:8000`）
  - LLM 配置、技能与记忆上下文
- 输出
  - 同步 JSON 响应或 SSE 流
  - 工具事件、会话持久化结果
- 风险点
  - 路由面较大，改动时易引发回归
  - 流式链路中工具事件与文本事件交错复杂

### 2.4 Agent 调度层

模块：`agentserver/`

- 职责
  - AgentServer 客户端治理与任务调度。
  - 管理任务步骤、压缩记忆、会话维度任务状态。
  - 提供 AgentServer 健康检查、安装、配置、历史查询等接口。
- 关键文件
  - `agentserver/agent_server.py`
  - `agentserver/task_scheduler.py`
  - `agentserver/AgentServer/AgentServer_client.py`
  - `agentserver/AgentServer/embedded_runtime.py`
  - `agentserver/AgentServer/installer.py`
- 输入
  - 来自 API/后台分析器的调度请求
- 输出
  - AgentServer 执行结果与任务状态
- 风险点
  - AgentServer 运行时来源（全局/内嵌）切换复杂
  - 外部网关不可用时的恢复逻辑复杂

### 2.5 MCP 工具层

模块：`mcpserver/`

- 职责
  - 扫描 `agent-manifest.json` 自动注册 MCP 工具。
  - 统一 `unified_call` 调度入口。
  - 暴露 MCP HTTP 服务（`/schedule`、`/call`、`/services`、`/status`）。
- 关键文件
  - `mcpserver/mcp_registry.py`
  - `mcpserver/mcp_manager.py`
  - `mcpserver/mcp_server.py`
- 当前已注册目录
  - `mcpserver/agent_weather_time/`
  - `mcpserver/agent_open_launcher/`
  - `mcpserver/agent_game_guide/`
- 风险点
  - 动态加载 manifest 对结构规范较敏感
  - 工具入参和输出标准化约束偏弱

### 2.6 记忆与知识图谱层

模块：`summer_memory/`

- 职责
  - 对话到五元组抽取、去重、存储（文件/Neo4j）与检索。
  - 任务队列化抽取（并发 worker）与统计。
- 关键文件
  - `summer_memory/memory_manager.py`
  - `summer_memory/task_manager.py`
  - `summer_memory/quintuple_extractor.py`
  - `summer_memory/quintuple_graph.py`
  - `summer_memory/memory_client.py`
- 输入
  - 对话内容或检索 query
- 输出
  - 五元组数据、检索结果、统计信息
- 风险点
  - Neo4j 可用性对在线能力影响显著
  - 抽取质量和召回质量受模型/Prompt 影响较大

### 2.7 游戏攻略引擎层

模块：`guide_engine/`

- 职责
  - 游戏问答路由、RAG 检索、图数据库上下文、特定游戏计算服务、自动截图注入。
- 关键文件
  - `guide_engine/guide_service.py`
  - `guide_engine/query_router.py`
  - `guide_engine/neo4j_service.py`
  - `guide_engine/calculation_service.py`
  - `guide_engine/kantai_calculation_service.py`
  - `guide_engine/screenshot_provider.py`
- 输入
  - 游戏问答文本、可选图片
- 输出
  - 攻略回答、引用来源、计算结果
- 风险点
  - 多游戏数据源一致性与更新策略
  - 依赖截图能力时的跨平台差异

### 2.8 语音能力层

模块：`voice/`

- 职责
  - TTS 合成、流式/文件式音频输出、实时语音输入适配。
- 关键文件
  - `voice/tts_wrapper.py`
  - `voice/output/server.py`
  - `voice/output/tts_handler.py`
  - `voice/input/*`
- 输入
  - 文本片段或音频输入
- 输出
  - 语音数据流、音频文件、实时识别文本
- 风险点
  - 语音链路依赖项较多（音频设备、格式、网络）
  - 不同平台音频驱动行为不一致

### 2.9 前端桌面层

模块：`frontend/`

- 职责
  - Electron 壳层（窗口/托盘/快捷键/更新）
  - Vue UI（聊天、设置、技能、记忆、可视化、悬浮球）
- 关键文件
  - `frontend/electron/main.ts`
  - `frontend/electron/modules/window.ts`
  - `frontend/electron/modules/backend.ts`
  - `frontend/src/main.ts`
  - `frontend/src/App.vue`
  - `frontend/src/views/*.vue`
- 路由页
  - `PanelView`、`MessageView`、`ModelView`、`MemoryView`、`MindView`、`SkillView`、`ConfigView`、`FloatingView`
- 风险点
  - 悬浮球和无边框窗口行为高度依赖 Electron API
  - UI 与后端耦合在本地 HTTP 接口协议上

### 2.10 构建与发布层

模块：`scripts/` + `frontend/electron-builder.yml`

- 职责
  - Windows 一键构建，集成 PyInstaller 与 Electron Builder。
  - 内嵌 AgentServer 运行时资源准备。
- 关键文件
  - `scripts/build-win.py`
  - `frontend/electron-builder.yml`
  - `naga-backend.spec`
- 风险点
  - 打包体积大，构建链条长，失败定位成本高
  - 内嵌依赖版本（Node/AgentServer）更新需要联动验证

### 2.11 模型协议与代理治理

模块：`apiserver/` + `system/` + `main.py`

- 职责
  - 根据 `protocol/provider/base_url` 进行模型协议路由（OpenAI 兼容 / Google 原生）。
  - 规范化 Google 请求 URL（自动纠正误填的 `chat/completions` 或完整 endpoint）。
  - 管理系统代理开关，保障 HTTP 与 WebSocket 链路行为一致。
- 关键文件
  - `apiserver/llm_service.py`
  - `system/background_analyzer.py`
  - `agentserver/task_scheduler.py`
  - `main.py`
  - `frontend/src/views/ModelView.vue`
- 输入
  - `config.json.api` 中的 `protocol`、`provider`、`google_live_api`、`applied_proxy`、`request_timeout`
- 输出
  - 规范化后的请求 URL 与路由方式
  - 带脱敏 URL 的排障日志（含代理启用状态）
- 风险点
  - 代理策略若与系统设置不一致，可能出现“请求格式正确但连接失败”
  - WebSocket（Live API）与 HTTP（SSE）对代理的连通性表现可能不同

## 3. 模块关系简图（文本）

1. `frontend` -> 调用 -> `apiserver`
2. `apiserver` -> 调用 -> `agentserver` / `mcpserver` / `summer_memory` / `guide_engine`
3. `agentserver` -> 调用 -> `AgentServer gateway`
4. `apiserver` 与 `agentserver` 均依赖 `system` 配置与工具能力
5. `voice` 既可被 API 层调用，也可独立作为语音服务

## 4. 归档更新建议

1. 新增一级目录时，同步补充本文件对应章节。
2. 新增对外路由时，在模块章节里补充入口文件与接口族。
3. 对重构项（特别是前端替换）在 `doc/03-qt-migration-assessment.md` 追加影响评估。

