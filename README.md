<div align="center">

# NagaAgent

**三服务协同的 AI 桌面助手 — 流式工具调用 · 知识图谱记忆 · Live2D**

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

NagaAgent 由三个独立微服务组成：

| 服务 | 端口 | 职责 |
|------|------|------|
| **API Server** | 8000 | 对话、流式工具调用、文档上传、认证代理、记忆 API、配置管理 |
| **Agent Server** | 8001 | 后台意图分析、任务调度与压缩记忆 |
| **MCP Server** | 8003 | MCP 工具注册/发现/并行调度 |

`main.py` 统一编排启动，所有服务以 daemon thread 运行。当前前端主链为 `Embla_core`（Next.js 运维面板）；`frontend/`（Electron + Vue 3）为 `archived` 历史兼容路径。

---

## 更新日志

| 日期 | 内容 |
|------|------|
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
    └─ live2d   → UI Fire-and-forget 通知
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

**远程记忆**（5.0.0 新增）：

- `summer_memory/memory_client.py` 对接 NagaMemory 云端服务
- 登录用户自动使用云端存储，退出登录或离线时自动回退本地 GRAG
- API Server 新增 `/api/memory/*` 代理端点，前端通过 API Server 中转

源码：[`summer_memory/`](summer_memory/)

---

### MCP 工具系统

基于 [Model Context Protocol](https://modelcontextprotocol.io/) 的可插拔工具架构，每个工具以独立 Agent 形式运行。

**内置 Agent**（仓库核验：2026-02-27）：

| Agent | 目录 | 功能 | 状态 |
|-------|------|------|------|
| `weather_time` | `mcpserver/agent_weather_time/` | 天气查询/预报、系统时间、自动城市/IP 检测 | `available` |
| `open_launcher` | `mcpserver/agent_open_launcher/` | 扫描系统已安装应用，自然语言启动程序 | `available` |
| `game_guide` | `mcpserver/agent_game_guide/` | 游戏策略问答、伤害计算、配队推荐、自动截图注入 | `available` |
| `online_search` | `mcpserver/agent_online_search/` | 基于 SearXNG 的网络搜索 | `missing`（目录缺失） |
| `crawl4ai` | `mcpserver/agent_crawl4ai/` | 基于 Crawl4AI 的网页内容提取 | `missing`（目录缺失） |
| `playwright_master` | `mcpserver/agent_playwright_master/` | 基于 Playwright 的浏览器自动化 | `missing`（目录缺失） |
| `vision` | `mcpserver/agent_vision/` | 截图分析与视觉问答 | `missing`（目录缺失） |
| `mqtt_tool` | `mcpserver/agent_mqtt_tool/` | MQTT 协议 IoT 设备控制 | `missing`（目录缺失） |
| `office_doc` | `mcpserver/agent_office_doc/` | docx/xlsx 内容提取 | `missing`（目录缺失） |

**注册与发现**：

```
mcpserver/
├── agent_weather_time/
│   ├── agent-manifest.json    ← 声明 name, entryPoint.module/class, capabilities
│   └── agent_weather_time.py
├── agent_open_launcher/
│   ├── agent-manifest.json
│   └── agent_app_launcher.py
├── agent_game_guide/
│   ├── agent-manifest.json
│   └── agent_game_guide.py
└── mcp_registry.py            ← scan_and_register_mcp_agents() glob 扫描 **/agent-manifest.json
                                   importlib.import_module(module).ClassName() 动态实例化
```

- `MCPManager.unified_call(service_name, tool_call)` 路由到对应 Agent 的 `handle_handoff()`
- MCP Server `POST /schedule` 支持批量调用，`asyncio.gather()` 并行执行
- **Skill Market**：前端技能工坊支持一键安装社区 Skill（Agent Browser、Brainstorming、Context7、Firecrawl Search 等），后端通过 `/skills/import` 导入自定义 Skill

源码：[`mcpserver/`](mcpserver/)

---

### Electron 桌面端

基于 Electron + Vue 3 + Vite + UnoCSS + PrimeVue 的桌面客户端。

#### Live2D 渲染与动画

使用 **pixi-live2d-display** + **PixiJS WebGL** 渲染 Cubism Live2D 模型。SSAA 超采样抗锯齿：Canvas 按 `width * ssaa` 渲染，CSS `transform: scale(1/ssaa)` 缩放。

**4 通道正交动画系统**（`live2dController.ts`）：

| 通道 | 说明 | 参数 |
|------|------|------|
| **体态 (State)** | 关键帧循环动画（idle/thinking/talking），hermite 平滑插值 | 从 `naga-actions.json` 加载 |
| **动作 (Action)** | 队列式头部动作（点头/摇头），FIFO 单一执行 | AngleX/Y, EyeBallX/Y |
| **表情 (Emotion)** | `.exp3.json` 表情文件，三种混合模式（Add/Multiply/Overwrite） | 指数衰减过渡 |
| **追踪 (Tracking)** | 鼠标指针跟随视线，可配延迟启动（`tracking_hold_delay_ms`） | Angle ±30, EyeBall ±1, BodyAngle ±10 |

合并顺序：体态 → 嘴形 → 动作 → 手动覆盖 → 表情混合 → 追踪混合。

#### 意识海可视化（MindView）

Canvas 2D + 手写 3D 投影（非 WebGL/SVG），球面坐标相机 `(theta, phi, distance)`，透视除法 `700 / depth`。

**7 层渲染**：背景渐变 → 地面网格 → 水面平面 → 体积光（3 束光柱） → 粒子系统（3 层 125 颗） → 生物荧光浮游生物（10 个带拖尾） → 知识图谱节点与边（深度排序 painter's algorithm）。

五元组到图的映射：`subject`/`object` → 节点，`predicate` → 有向边，度中心性 → 节点高度权重（高权节点上浮），100 节点上限。

交互：单击拖拽旋转、中键/Shift+拖拽平移、滚轮缩放、节点拖拽/点选、关键词搜索过滤、触屏手势。

#### 悬浮球模式

4 状态动画窗口系统：`classic`（正常）→ `ball`（100×100 圆球）→ `compact`（420×100 折叠）→ `full`（420×N 展开）。

easeOutCubic 缓动（`1 - (1 - t)^3`），160ms / 60FPS 过渡。智能定位：从球位置向右展开，自动贴合屏幕边界。

#### 启动动画

1. **标题阶段**：黑色遮罩 + 40 颗金色上升粒子 + 标题图片 2.4s CSS keyframe（渐入 → 停留 → 渐出）
2. **进度阶段**：Neural Network 粒子背景 + Live2D 透出框 + 金色进度条（`requestAnimationFrame` 插值，最低速度 0.5 兜底）
3. **停滞检测**：3 秒无进度变化显示重启提示，25% 后每秒轮询后端 `/health` 防止信号丢失
4. **唤醒**：进度 100% 后显示"点击唤醒"脉冲提示

源码（archived）：[`frontend/`](frontend/)

---

### 语音模块状态

历史 `voice/` 实现已从运行主链移除，当前仓库不再提供内建 TTS/ASR 服务。

---

### Agent Server 与 Autonomous (自治系统的崛起)

**背景分析**：
当前 Agent Server (`BackgroundAnalyzer`) 负责后台意图分析与任务调度。工具执行主链路已统一为结构化 `tool_calls` + `native`/MCP 调度。

**全新 Autonomous 自治模块**（位于 `autonomous/` 目录）：
取代它的是一套强一致、全自动化的自研 SDLC (Software Development Life Cycle) 架构，专门面向深度的全栈工程执行：

- **Single Active Lease (选主协议)**：使用强一致 DB 锁(`workflow.db`)和 Fencing 时代纪元，确保全局有且仅有单个 Active Orchestrator 在操作仓库。
- **阶段流转状态机**：拥有极强事务原子性(Idempotency-key 机制)，保证代码变更任务从 `GoalAccepted` -> `PlanDrafted` -> `Implementing`（利用 Claude/Codex 适配器） -> `Verifying` 的顺滑无双写推演。
- **测评修复（Evaluator & Reworker）**：验证环节不过关？如果 CLI Native 环境测试不通过，主动通过 Codex MCP(`ask-codex`) 发起结构化纠偏而非无规律重试。
- **发布灰度监控（Release Controller）**：变更完成后不是立即 commit 到生产，而是先注入灰度池（Canary Deploy），依据 P95 延迟与 Error Rate 监控，由大模型判定发布 / 晋升 (Promote) / 或者硬回滚 (Auto-Rollback)。

这使得 Naga 真正演变成了一台能在无人干预下持续运转多日的智能研发服务器。

源码：[`autonomous/`](autonomous/)

---

## 架构

```
┌──────────────────────────────────────────────────────┐
│                Embla_core (Next.js 前端)            │
└────────────┬────────────┬────────────────────────────┘
             │            │
     ┌───────▼──────┐ ┌──▼──────────┐
     │  API Server  │ │ AgentServer │
     │   :8000      │ │   :8001     │
     │ - 对话/SSE   │ │ - 任务编排  │
     │ - Native调用 │ │ - 记忆压缩  │
     │ - 认证代理   │ └──┬──────────┘
     │ - 配置管理   │    │
     └──────┬───────┘ ┌──▼──────────┐
            │         │ Autonomous  │
     ┌──────▼──────┐  │ Subsystem   │
     │ MCP Server  │  │   (SDLC)    │
     │   :8003     │  └─────────────┘
     │ - 工具注册  │
     │ - Agent发现 │
     │ - 并行调度  │
     └──────┬──────┘
            │
    ┌───────▼──────────────────────┐
    │   MCP Agents (可插拔工具)     │
    └──────────────────────────────┘
            │
     ┌──────▼──────┐
     │   Neo4j     │
     │   :7687     │
     │  知识图谱   │
     └─────────────┘
```

### 目录结构

```
NagaAgent/
├── apiserver/            # API Server — 对话、流式工具调用、认证、配置管理
│   ├── api_server.py     #   FastAPI 主应用
│   ├── agentic_tool_loop.py  #   多轮工具(原生)调用循环
│   ├── native_tools.py   #   Local-First 拦截下放
│   └── llm_service.py    #   LiteLLM 统一 LLM 和 tool_calls
├── agentserver/          # Agent Server — 旧管线兼容层
│   ├── agent_server.py   #   FastAPI 主应用
│   └── task_scheduler.py #   任务编排 + 压缩记忆
├── autonomous/           # 全新自治系统 (SDLC Agent)
│   ├── system_agent.py   #   Single Active 编排守护态
│   ├── planner.py        #   策略分解
│   ├── dispatcher.py     #   CLI 命令执行包裹
│   ├── evaluator.py      #   评测打分体系
│   └── release/          #   降级与金丝雀放量
├── mcpserver/            # MCP Server — 工具注册与调度
│   ├── mcp_server.py     #   FastAPI 主应用
│   ├── mcp_registry.py   #   manifest 扫描 + 动态注册
│   ├── mcp_manager.py    #   unified_call() 路由
│   ├── agent_weather_time/
│   ├── agent_open_launcher/
│   ├── agent_game_guide/
│   └── (其余 Agent 按需扩展)
├── summer_memory/        # GRAG 知识图谱
│   ├── quintuple_extractor.py  #   五元组提取（结构化输出 + JSON 兜底）
│   ├── quintuple_graph.py      #   Neo4j + 文件双重存储
│   ├── quintuple_rag_query.py  #   Cypher 关键词 RAG 检索
│   ├── task_manager.py         #   3 worker 异步任务管理器
│   ├── memory_manager.py       #   GRAG 总管理器
│   └── memory_client.py        #   NagaMemory 远程客户端
├── guide_engine/         # 游戏攻略引擎 — 云端 RAG 服务
├── Embla_core/           # Next.js 运行态势面板（主链）
├── frontend/             # Electron + Vue 3 前端（archived 历史兼容）
│   ├── electron/         #   主进程（窗口管理、悬浮球、后端管理、热键）
│   └── src/              #   Vue 3 应用
│       ├── views/        #     MessageView / MindView / SkillView / ModelView / MemoryView / ConfigView
│       ├── components/   #     Live2dModel / SplashScreen / LoginDialog / ...
│       ├── composables/  #     useAuth / useStartupProgress / useVersionCheck / useToolStatus
│       └── utils/        #     live2dController (4通道动画) / encoding / session
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
python main.py             # 完整启动（API + Agent + MCP + GUI）
uv run main.py             # 使用 uv
python main.py --headless  # 无 GUI 模式（配合 Web/远程前端）
```

所有服务由 `main.py` 统一编排，也可单独启动：

```bash
uvicorn apiserver.api_server:app --host 127.0.0.1 --port 8000 --reload
uvicorn agentserver.agent_server:app --host 0.0.0.0 --port 8001
```

### Embla_core 前端开发（主链）

```bash
cd Embla_core
npm install
npm run dev    # Next.js 开发模式
npm run build  # Next.js 生产构建
```

### Electron 前端开发（archived 历史兼容）

```bash
cd frontend
npm install
npm run dev    # 开发模式（Vite + Electron）
npm run build  # 构建生产包
```

---

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
<summary><b>Live2D 虚拟形象</b></summary>

```json
{
  "live2d": {
    "enabled": true,
    "model_path": "path/to/your/model.model3.json"
  }
}
```

Electron 前端 Live2D 配置：

```json
{
  "web_live2d": {
    "ssaa": 2,
    "model": {
      "source": "./models/your-model/model.model3.json",
      "x": 0.5,
      "y": 1.3,
      "size": 6800
    },
    "face_y_ratio": 0.13,
    "tracking_hold_delay_ms": 100
  }
}
```
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
| Agent Server | 8001 | 意图分析、任务调度 |
| MCP Server | 8003 | MCP 工具注册与调度 |
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
| 端口被占用 | 检查 8000、8001、8003 是否可用 |
| Neo4j 连接失败 | 确认 Neo4j 服务已启动，检查 config.json 中的连接参数 |
| 启动卡在进度条 | 检查 API Key 是否配置正确；3 秒后出现重启提示；Electron 会自动轮询后端健康状态 |

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

[![Star History Chart](https://api.star-history.com/svg?repos=RTGS2017/NagaAgent&type=date&legend=top-left)](https://www.star-history.com/#RTGS2017/NagaAgent&type=date&legend=top-left)
