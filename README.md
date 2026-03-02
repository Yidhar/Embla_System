<div align="center">

# NagaAgent

**双服务主链的 AI 运行平台 — 流式工具调用 · 知识图谱记忆 · 运维看板**

[简体中文](README.md)  | [English](README_en.md)

![NagaAgent](https://img.shields.io/badge/NagaAgent-5.0.0-blue?style=for-the-badge&logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-green?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.11-blue?style=for-the-badge&logo=python)

[![Stars](https://img.shields.io/github/stars/Xxiii8322766509/NagaAgent?style=social)](https://github.com/Xxiii8322766509/NagaAgent)
[![Forks](https://img.shields.io/github/forks/Xxiii8322766509/NagaAgent?style=social)](https://github.com/Xxiii8322766509/NagaAgent)
[![Issues](https://img.shields.io/github/issues/Xxiii8322766509/NagaAgent)](https://github.com/Xxiii8322766509/NagaAgent/issues)

 **[QQ 机器人联动：Undefined QQbot](https://github.com/69gg/Undefined/)**

</div>

---

## 概述

当前运行主链由两个后端服务组成（另有可选调试服务）：

| 服务 | 端口 | 职责 |
|------|------|------|
| **API Server** | 8000 | 对话、流式工具调用、文档上传、系统配置、运行态聚合 |
| **MCP Server** | 8003 | MCP 工具注册/发现/并行调度 |
| **LLM Service（可选调试）** | 8001 | `apiserver.llm_service` 独立调试入口（不在 `main.py` 默认启动链） |

`main.py` 默认编排 `API + MCP`，并按配置启停 `autonomous` 后台循环。当前前端主链为 `Embla_core`（Next.js 运维面板）。

---

## 更新日志

| 日期 | 内容 |
|------|------|
| **2026-02-27** | 退役 Live2D 运行时链路：移除 `live2d_action` 工具分发、`/live2d/actions` API 与相关配置项，统一收敛为 `native/mcp` 工具执行 |
| **2026-02-19** | 重构核心架构：引入基于 SDLC 的 Autonomous 自动化开发自治框架 (含 Lease/Fencing); 原生结构化 tool_calls 全面接管执行链路 |
| **2026-02-14** | 5.0.0 发布：远程记忆微服务（NagaMemory 云端 + 本地 GRAG 回退）、意识海 3D 重写、启动标题动画与粒子效果、进度条停滞检测与健康轮询、版本更新检查弹窗、用户使用协议 |
| **2026-02-14** | Captcha 验证码集成、注册流程（用户名 + 邮箱 + 验证码）、CAS 会话失效弹窗、语音输入按钮、文件解析按钮、IME 中文输入法回车误发修复 |
| **2026-02-14** | 移除 ChromaDB 本地依赖（-1119 行），游戏攻略全云端化，攻略功能增加登录态门控 |
| **2026-02-13** | 悬浮球模式（4 状态动画：classic / ball / compact / full）、截屏多模态视觉模型自动切换 |
| **2026-02-13** | 技能工坊重构 + Live2D 表情通道独立 + naga-config 技能 |
| **2026-02-12** | NagaCAS 认证 + NagaModel 网关路由 + 登录弹窗 + 用户菜单 |
| **2026-02-12** | Live2D 4 通道正交动画架构（体态/动作/表情/追踪），窗口级视觉追踪与校准 |
| **2026-02-12** | Agentic Tool Loop：流式工具提取 + 多轮自动执行 + 并行 MCP/Native/Live2D 调度 |
| **2026-02-12** | 明日方舟风格启动界面 + 进度跟踪 + 视图预加载 + 鼠标视差浮动效果 |
| **2026-02-12** | 游戏攻略 MCP 接通（自动截图 + 视觉模型 + Neo4j 导入 + 6 款游戏 RAG 处理器） |
| **2026-02-11** | 后端打包优化、启动时自动从模板生成配置文件 |
| **2026-02-10** | 后端打包优化、技能工坊 MCP 状态修复、前端 bug 修复 |
| **2026-02-09** | 前端重构、Live2D 禁用眼睛追踪、AgentServer 命名统一 |

---

## 核心模块

### 流式工具调用循环（结构化 tool_calls & Local-first Native）

NagaAgent 当前的主链路已经完全改造为 **结构化 `tool_calls` 通道**：
LLM 不再通过生成 ` ```tool ` 代码块来触发工具，而是通过流式事件传递结构化的目标调用列表。AgenticLoop 会独立于普通会话文本对其进行消费，极大降低了格式漂移和解析失败的概率。

**核心机制**：

```text
LLM 流式输出(content/reasoning) ──SSE──▶ 前端实时显示
            │
            ├─ delta.tool_calls 增量到达
            ▼
      LLMService 合并 tool_calls 增量，以 type=tool_calls 单独输出进入 Loop
            │
            ▼
AgenticLoop 将 calls 转换为 actionable execution 并行派发（受限并发调度）
    ├─ mcp      → MCPManager.unified_call()
    ├─ native   → Local-first NativeToolExecutor (拦截如 cd 为 get_cwd，严守项目沙盒级安全边界)
            │
            ▼
 工具结果并入 message 列表触发下一轮推理
```

源码：[`apiserver/llm_service.py`](apiserver/llm_service.py)、[`apiserver/agentic_tool_loop.py`](apiserver/agentic_tool_loop.py)、[`apiserver/native_tools.py`](apiserver/native_tools.py)

---

### GRAG 知识图谱记忆

GRAG（Graph-RAG）从对话中自动提取五元组 `(主体, 主体类型, 谓词, 客体, 客体类型)` 并存入 Neo4j，对话时自动检索相关记忆作为 LLM 上下文。

**提取流程**：

1. **结构化提取**（优先）：调用 `beta.chat.completions.parse()` + Pydantic 模型 `QuintupleResponse`，`temperature=0.3`，最多重试 3 次
2. **JSON 兜底**：Prompt 要求 LLM 返回 JSON 数组，解析失败则取首个 `[` 到末尾 `]` 之间的内容
3. **过滤规则**：只提取事实信息（行为、实体关系、状态、偏好），过滤隐喻、假设、纯情感、闲聊
4. **实体类型**：person / location / organization / item / concept / time / event / activity

**任务管理器**：

- 3 个 asyncio worker 协程消费 `asyncio.Queue(maxsize=100)`
- SHA-256 去重：相同文本的 PENDING/RUNNING 任务自动跳过
- 每小时自动清理超过 24h 的已完成任务
- 可配置超时（默认 12 秒）和重试次数（默认 2 次）

**双重存储**：

- 本地文件 `logs/knowledge_graph/quintuples.json`（JSON 数组，set 去重）
- Neo4j 图数据库：`Entity` 节点 + 类型化 `Relationship` 关系边，`graph.merge()` upsert

**RAG 检索**：

1. 提取用户问题关键词（LLM 生成）
2. Cypher 查询：`MATCH (e1:Entity)-[r]->(e2:Entity) WHERE e1.name CONTAINS '{kw}' ... LIMIT 5`
3. 格式化为 `主体(类型) —[谓词]→ 客体(类型)` 注入 LLM 上下文

**记忆访问现状**：

- `summer_memory/memory_client.py` 当前为 local-only shim（`get_remote_memory_client()` 恒为 `None`）
- 对话链路默认走本地 GRAG 回退
- API Server 暴露 `memory/stats`、`memory/quintuples`、`memory/quintuples/search` 等本地记忆查询端点

源码：[`summer_memory/`](summer_memory/)

---

### MCP 工具系统

基于 [Model Context Protocol](https://modelcontextprotocol.io/) 的可插拔工具架构，每个工具以独立 Agent 形式运行。

**内置 Agent**（仓库核验：2026-02-27）：

| Agent | 目录 | 功能 | 状态 |
|-------|------|------|------|
| `weather_time` | `mcpserver/agent_weather_time/` | 天气查询/预报、系统时间、自动城市/IP 检测 | `available` |
| `app_launcher` (`open_launcher` alias) | `mcpserver/agent_open_launcher/` | 扫描系统已安装应用，自然语言启动程序 | `available` |
| `online_search` | `mcpserver/agent_online_search/` | 基于 SearXNG 的网络搜索 | `available` |
| `crawl4ai` | `mcpserver/agent_crawl4ai/` | 网页抓取与正文提取 | `available` |
| `playwright_master` | `mcpserver/agent_playwright_master/` | 基于 Playwright 的浏览器自动化 | `available` |
| `vision` | `mcpserver/agent_vision/` | 截图分析与视觉问答 | `available` |
| `mqtt_tool` | `mcpserver/agent_mqtt_tool/` | MQTT 协议 IoT 设备控制 | `missing`（目录缺失） |
| `office_doc` | `mcpserver/agent_office_doc/` | docx/xlsx 内容提取 | `available` |

**注册与发现**：

```
mcpserver/
├── agent_weather_time/
│   ├── agent-manifest.json    ← 声明 name, entryPoint.module/class, capabilities
│   └── agent_weather_time.py
├── agent_open_launcher/
│   ├── agent-manifest.json
│   └── agent_app_launcher.py
├── agent_online_search/
│   ├── agent-manifest.json
│   └── agent_online_search.py
├── agent_crawl4ai/
│   ├── agent-manifest.json
│   └── agent_crawl4ai.py
├── agent_playwright_master/
│   ├── agent-manifest.json
│   └── agent_playwright_master.py
├── agent_vision/
│   ├── agent-manifest.json
│   └── agent_vision.py
├── agent_office_doc/
│   ├── agent-manifest.json
│   └── agent_office_doc.py
└── mcp_registry.py            ← scan_and_register_mcp_agents() glob 扫描 **/agent-manifest.json
                                   importlib.import_module(module).ClassName() 动态实例化
```

- `MCPManager.unified_call(service_name, tool_call)` 路由到对应 Agent 的 `handle_handoff()`
- MCP Server `POST /schedule` 支持批量调用，`asyncio.gather()` 并行执行
- **Skill Market**：前端技能工坊支持一键安装社区 Skill（Agent Browser、Brainstorming、Context7、Firecrawl Search 等），后端通过 `/skills/import` 导入自定义 Skill

源码：[`mcpserver/`](mcpserver/)

---

### Legacy Desktop Lane (Retired)

旧 Electron + Vue 客户端已从仓库移除，不再参与发布与回归门禁。

---

### 语音模块状态

历史 `voice/` 实现已从运行主链移除，当前仓库不再提供内建 TTS/ASR 服务。

---

### Autonomous（自治系统主链）

**现状**：
Legacy `agentserver` 执行管线已从仓库移除，任务执行与治理统一收敛到 `apiserver` + `autonomous` + `mcpserver` 主链。

**Autonomous 自治模块**（位于 `autonomous/` 目录）：
系统采用强一致、全自动化的自研 SDLC (Software Development Life Cycle) 架构，面向深度全栈工程执行：

- **Single Active Lease (选主协议)**：使用强一致 DB 锁(`workflow.db`)和 Fencing 时代纪元，确保全局有且仅有单个 Active Orchestrator 在操作仓库。
- **阶段流转状态机**：拥有极强事务原子性(Idempotency-key 机制)，保证代码变更任务从 `GoalAccepted` -> `PlanDrafted` -> `Implementing`（SubAgent + NativeExecutionBridge） -> `Verifying` 的顺滑无双写推演。
- **测评修复（Evaluator & Reworker）**：验证环节不过关时走内生治理闭环（contract gate / scaffold gate / risk gate / incident），而非外部黑盒代理降级重试。
- **发布灰度监控（Release Controller）**：变更完成后不是立即 commit 到生产，而是先注入灰度池（Canary Deploy），依据 P95 延迟与 Error Rate 监控，由大模型判定发布 / 晋升 (Promote) / 或者硬回滚 (Auto-Rollback)。

这使得 Naga 真正演变成了一台能在无人干预下持续运转多日的智能研发服务器。

源码：[`autonomous/`](autonomous/)

---

## 架构

```
┌──────────────────────────────────────────────────────┐
│                Embla_core (Next.js 前端)            │
└────────────┬─────────────────────────────────────────┘
             │
     ┌───────▼──────────┐      ┌─────────────────────┐
     │   API Server     │─────►│ Autonomous Subsystem│
     │      :8000       │      │       (SDLC)        │
     │ - 对话/SSE       │      └─────────────────────┘
     │ - Native调用     │
     │ - 认证代理       │      ┌─────────────────────┐
     │ - 配置管理       │─────►│     MCP Server      │
     └──────────────────┘      │        :8003        │
                                │ - 工具注册/调度     │
                                └─────────┬───────────┘
                                          │
                                ┌─────────▼───────────┐
                                │ MCP Agents (可插拔) │
                                └─────────┬───────────┘
                                          │
                                ┌─────────▼───────────┐
                                │   Neo4j :7687       │
                                │     知识图谱         │
                                └─────────────────────┘
```

### 目录结构

```
NagaAgent/
├── apiserver/            # API Server — 对话、流式工具调用、认证、配置管理
│   ├── api_server.py     #   FastAPI 主应用
│   ├── agentic_tool_loop.py  #   多轮工具(原生)调用循环
│   ├── native_tools.py   #   Local-First 拦截下放
│   └── llm_service.py    #   LiteLLM 统一 LLM 和 tool_calls
├── autonomous/           # 全新自治系统 (SDLC Agent)
│   ├── system_agent.py   #   Single Active 编排守护态
│   ├── planner.py        #   策略分解
│   └── release/          #   降级与金丝雀放量
├── mcpserver/            # MCP Server — 工具注册与调度
│   ├── mcp_server.py     #   FastAPI 主应用
│   ├── mcp_registry.py   #   manifest 扫描 + 动态注册
│   ├── mcp_manager.py    #   unified_call() 路由
│   ├── agent_weather_time/
│   ├── agent_open_launcher/
│   ├── agent_online_search/
│   ├── agent_crawl4ai/
│   ├── agent_playwright_master/
│   ├── agent_vision/
│   ├── agent_office_doc/
│   └── (其余 Agent 按需扩展)
├── summer_memory/        # GRAG 知识图谱
│   ├── quintuple_extractor.py  #   五元组提取（结构化输出 + JSON 兜底）
│   ├── quintuple_graph.py      #   Neo4j + 文件双重存储
│   ├── quintuple_rag_query.py  #   Cypher 关键词 RAG 检索
│   ├── task_manager.py         #   3 worker 异步任务管理器
│   ├── memory_manager.py       #   GRAG 总管理器
│   └── memory_client.py        #   NagaMemory 远程客户端
├── Embla_core/           # Next.js 运行态势面板（主链）
├── system/               # 配置加载、环境检测、系统提示词、后台分析器
├── main.py               # 统一入口，编排所有服务
├── config.json           # 运行时配置（从 config.json.example 复制）
└── pyproject.toml        # 项目元数据与依赖
```

---

## 快速开始

### 环境要求

- Python 3.11（`>=3.11, <3.12`）
- 可选：[uv](https://github.com/astral-sh/uv)（加速依赖安装）
- 可选：Neo4j（知识图谱记忆）

### 安装

```bash
git clone https://github.com/Xxiii8322766509/NagaAgent.git
cd NagaAgent

# 方式一：uv（推荐）
uv sync

# 方式二：手动 pip
python -m venv .venv
source .venv/bin/activate  # Windows: .\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 配置

复制 `config.json.example` 为 `config.json`，填入 LLM API 信息：

```json
{
  "api": {
    "api_key": "your-api-key",
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-v3.2"
  }
}
```

支持所有 OpenAI 兼容 API（DeepSeek、通义千问、OpenAI、Ollama 等）。

### 启动

```bash
python main.py             # 完整启动（API + MCP + 可选自治后台）
uv run main.py             # 使用 uv
python main.py --headless  # 无头模式（跳过交互提示，适配 Web/远程前端）
```

所有服务由 `main.py` 统一编排，也可单独启动：

```bash
uvicorn apiserver.api_server:app --host 127.0.0.1 --port 8000 --reload
uvicorn mcpserver.mcp_server:app --host 127.0.0.1 --port 8003 --reload
```

### Embla_core 前端开发（主链）

```bash
cd Embla_core
npm install
npm run dev    # Next.js 开发模式
npm run build  # Next.js 生产构建
```

## 可选配置

<details>
<summary><b>知识图谱记忆（Neo4j）</b></summary>

安装 Neo4j（[Docker](https://hub.docker.com/_/neo4j) 或 [Neo4j Desktop](https://neo4j.com/download/)），然后配置：

```json
{
  "grag": {
    "enabled": true,
    "neo4j_uri": "neo4j://127.0.0.1:7687",
    "neo4j_user": "neo4j",
    "neo4j_password": "your-password"
  }
}
```
</details>

<details>
<summary><b>Vision 多模态理解模型</b></summary>

`vision` MCP Agent 的 `image_qa` 会优先读取 `computer_control.model` 作为多模态理解模型：

```json
{
  "computer_control": {
    "enabled": true,
    "model": "gemini-2.5-flash"
  }
}
```

设置页对应路径：`Settings -> API & Model -> Multimodal Vision Model`。  
若该字段留空，运行时会回退到 `api.model`。
</details>

<details>
<summary><b>MQTT 物联网</b></summary>

```json
{
  "mqtt": {
    "enabled": true,
    "broker": "mqtt-broker-address",
    "port": 1883,
    "topic": "naga/agent/topic"
  }
}
```
</details>

---

## 端口一览

| 服务 | 端口 | 说明 |
|------|------|------|
| API Server | 8000 | 主接口：对话、配置、认证、Skill 市场 |
| MCP Server | 8003 | MCP 工具注册与调度 |
| LLM Service（可选调试） | 8001 | `apiserver.llm_service` 独立调试端口（默认不由 `main.py` 启动） |
| Neo4j | 7687 | 知识图谱（可选） |

---

## 更新

```bash
git pull --ff-only
uv sync
```

---

## 故障排除

| 问题 | 解决方案 |
|------|----------|
| Python 版本不兼容 | 使用 Python 3.11；或使用 uv（自动管理 Python 版本） |
| 端口被占用 | 检查 8000、8003 是否可用（若单独启 `llm_service` 再检查 8001） |
| Neo4j 连接失败 | 确认 Neo4j 服务已启动，检查 config.json 中的连接参数 |
| 启动卡在进度条 | 检查 API Key 是否配置正确；3 秒后出现重启提示；启动器会自动轮询后端健康状态 |

```bash
python main.py --check-env --force-check  # 环境诊断
python main.py --quick-check              # 快速检查
```

---

## 构建

```bash
python scripts/build-win.py  # 构建 Windows 一键运行整合包，输出到 dist/
```

---

## 贡献

欢迎提交 Issue 和 Pull Request。如有问题，可加入 QQ 频道 nagaagent1。

---

## 许可证

参见 [LICENSE](LICENSE)。如需商业部署或合作，请联系 contact@nagaagent.com，或 bilibili 私信【柏斯阔落】。

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=Xxiii8322766509/NagaAgent&type=date&legend=top-left)](https://www.star-history.com/#Xxiii8322766509/NagaAgent&type=date&legend=top-left)
