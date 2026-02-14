# NagaAgent

[简体中文](README.md) | [繁體中文](README_tw.md) | [English](README_en.md)

![NagaAgent](https://img.shields.io/badge/NagaAgent-5.0.0-blue?style=for-the-badge&logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-green?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.11-blue?style=for-the-badge&logo=python)
![Status](https://img.shields.io/badge/Status-Active-brightgreen?style=for-the-badge)

![Star History](https://img.shields.io/github/stars/Xxiii8322766509/NagaAgent?style=social) ![Forks](https://img.shields.io/github/forks/Xxiii8322766509/NagaAgent?style=social) ![Issues](https://img.shields.io/github/issues/Xxiii8322766509/NagaAgent) ![Pull Requests](https://img.shields.io/github/issues-pr/Xxiii8322766509/NagaAgent)

![UI 预览](ui/img/README.jpg)

---

## 概述

NagaAgent 是一个多服务协同的智能对话助手，由四个独立微服务组成：API Server 负责对话与工具调用，Agent Server 负责意图分析与任务调度，MCP Server 管理可插拔工具集，Voice Service 处理语音输入输出。支持 GRAG 知识图谱长期记忆、Live2D 虚拟形象、流式对话、MCP 工具协议、Electron 桌面客户端，以及基于 OpenClaw 的自动化任务执行。

**[教程视频与一键运行整合包](https://www.pylindex.top/naga)** | **框架联动（QQ 机器人）：[Undefined QQbot](https://github.com/69gg/Undefined/)**

---

## 功能

### 对话与工具调用

- **流式对话**：基于 SSE 的实时流式输出，支持所有 OpenAI 兼容 API 的模型
- **流式工具提取**：LLM 输出中的工具调用在流式传输过程中被实时解析和执行，文本部分同步发送到前端和 TTS
- **多轮工具调用循环**：工具执行结果自动回传 LLM，支持链式调用，可配置最大循环次数
- **文档上传与解析**：支持上传文件并解析内容注入对话上下文
- **持久化上下文**：跨会话的对话日志持久化，支持按天数加载历史上下文

### 记忆系统（GRAG）

- **五元组知识图谱**：从对话中自动提取 `(主体, 主体类型, 谓词, 客体, 客体类型)` 五元组，存入 Neo4j 图数据库
- **RAG 检索**：对话时自动检索相关记忆，作为上下文注入 LLM
- **任务管理器**：后台并发处理五元组提取任务，支持队列管理、超时控制、自动清理
- **远程记忆服务**：登录用户自动连接云端 NagaMemory 服务，离线回退本地存储
- **意识海可视化**：前端 MindView 基于 D3.js 的 3D 力导向图，实时展示知识图谱节点与关系

### MCP 工具集

基于 [Model Context Protocol](https://modelcontextprotocol.io/) 的可插拔工具系统，每个工具作为独立 Agent 运行：

| 工具 | 说明 |
|------|------|
| **天气与时间** | 天气查询、天气预报、系统时间，自动识别城市和 IP |
| **应用启动器** | 扫描系统已安装应用，通过自然语言启动指定程序 |
| **游戏攻略** | 游戏策略问答、伤害计算、队伍推荐，支持自动截图注入 |
| **在线搜索** | 基于 SearXNG 的网络搜索 |
| **网页抓取** | 基于 Crawl4AI 的网页内容提取 |
| **浏览器自动化** | 基于 Playwright 的浏览器操控 |
| **视觉识别** | 截图分析与视觉问答 |
| **MQTT 物联网** | 通过 MQTT 协议控制物联网设备 |
| **Office 文档** | docx/xlsx 内容提取 |

通过 Skill Market 可一键安装社区 Skill（Agent Browser、Brainstorming、Context7、Firecrawl Search 等）。

### Agent Server 与任务调度

- **意图分析**：基于博弈论的后台分析器，异步分析用户意图并生成可执行的 agent_calls
- **OpenClaw 集成**：对接 OpenClaw Gateway，支持通过自然语言调度 AI 编程助手执行电脑任务
- **任务编排**：Task Scheduler 管理任务生命周期，支持步骤记录、会话关联、压缩记忆

### 语音交互

- **语音合成（TTS）**：基于 Edge-TTS，OpenAI 兼容接口 `/v1/audio/speech`，支持流式播放、智能分句、多种音频格式
- **语音识别（ASR）**：基于 FunASR，支持 VAD 端点检测、WebSocket 实时流、多语言
- **实时语音对话**：基于通义千问 Omni 模型的全双工语音交互，支持回声抑制和语音活动检测

### 前端与界面

两套前端可选：

- **Electron + Vue 3 桌面端**：Vite 构建，UnoCSS + PrimeVue 组件库，支持 Live2D 模型渲染（pixi-live2d-display）、视角追踪、启动动画、悬浮球模式、系统托盘
- **PyQt5 原生 GUI**：Live2D 集成、MVC 架构、系统托盘最小化

**Electron 前端功能**：
- 启动画面：品牌标题动画 + 粒子效果 + 进度条同步 + Live2D 渐入
- 对话视图：Markdown 渲染、工具调用状态展示、语音输入按钮、文件上传
- 意识海：知识图谱 3D 可视化与搜索
- 技能市场：MCP 服务状态、社区 Skill 安装
- Live2D 模型选择与配置
- 记忆管理：GRAG 参数配置、Neo4j 连接状态
- 系统配置：全部配置项热编辑，实时同步后端
- NagaCAS 登录认证 + 验证码 + Token 刷新 + 会话失效处理

---

## 架构

```
┌──────────────────────────────────────────────────────────┐
│                   Electron / PyQt5 前端                    │
│  Vue 3 + Vite + UnoCSS + PrimeVue + pixi-live2d-display  │
└────────────┬────────────┬────────────┬───────────────────┘
             │            │            │
     ┌───────▼──────┐ ┌──▼──────┐ ┌──▼──────┐
     │  API Server  │ │ Agent   │ │  Voice  │
     │   :8000      │ │ Server  │ │ Service │
     │              │ │  :8001  │ │  :5048  │
     │ - 对话/流式  │ │         │ │         │
     │ - 工具调用   │ │ - 意图  │ │ - TTS   │
     │ - 文档上传   │ │   分析  │ │ - ASR   │
     │ - 认证代理   │ │ - 任务  │ │ - 实时  │
     │ - 记忆API    │ │   调度  │ │   语音  │
     │ - Skill市场  │ │ - Open  │ │         │
     │ - 配置管理   │ │   Claw  │ │         │
     └──────┬───────┘ └────┬────┘ └─────────┘
            │              │
     ┌──────▼──────┐  ┌───▼──────────┐
     │ MCP Server  │  │   OpenClaw   │
     │   :8003     │  │   Gateway    │
     │             │  └──────────────┘
     │ - 工具注册  │
     │ - Agent发现 │
     │ - 并行调度  │
     └──────┬──────┘
            │
    ┌───────┴──────────────────────┐
    │   MCP Agents (可插拔工具)     │
    │ 天气 | 搜索 | 抓取 | 视觉    │
    │ 启动器 | 攻略 | MQTT | ...   │
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
├── apiserver/            # API Server - 对话、工具调用、认证、配置管理
├── agentserver/          # Agent Server - 意图分析、任务调度、OpenClaw
├── mcpserver/            # MCP Server - 工具注册与调度
│   ├── agent_weather_time/       # 天气与时间
│   ├── agent_open_launcher/      # 应用启动器
│   ├── agent_game_guide/         # 游戏攻略
│   ├── agent_online_search/      # 在线搜索
│   ├── agent_crawl4ai/           # 网页抓取
│   ├── agent_playwright_master/  # 浏览器自动化
│   ├── agent_vision/             # 视觉识别
│   └── agent_mqtt_tool/          # MQTT 物联网
├── summer_memory/        # GRAG 知识图谱 - 五元组提取、Neo4j、RAG 检索
├── voice/                # 语音服务 - TTS (Edge-TTS) + ASR (FunASR)
├── guide_engine/         # 游戏攻略引擎 - 云端 RAG 服务
├── frontend/             # Electron + Vue 3 前端
│   ├── electron/         # Electron 主进程
│   └── src/              # Vue 3 应用
├── ui/                   # PyQt5 GUI (MVC)
├── system/               # 配置加载、环境检测、系统提示词
├── nagaagent_core/       # 核心库
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
# 克隆仓库
git clone https://github.com/Xxiii8322766509/NagaAgent.git
cd NagaAgent

# 方式一：使用 setup 脚本（自动检测环境、创建虚拟环境、安装依赖）
python setup.py

# 方式二：使用 uv
uv sync

# 方式三：手动
python -m venv .venv
source .venv/bin/activate  # Windows: .\.venv\Scripts\activate
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
python main.py          # 完整启动（API + Agent + MCP + Voice + GUI）
uv run main.py          # 使用 uv
python main.py --headless  # 无 GUI 模式（配合 Electron 前端）
```

所有服务由 `main.py` 统一编排启动，也可独立运行：

```bash
# 单独启动各服务（开发调试用）
uvicorn apiserver.api_server:app --host 127.0.0.1 --port 8000 --reload
uvicorn agentserver.agent_server:app --host 0.0.0.0 --port 8001
```

### Electron 前端开发

```bash
cd frontend
npm install
npm run dev             # 开发模式（Vite + Electron）
npm run build           # 构建生产包
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
<summary><b>语音交互</b></summary>

```json
{
  "system": { "voice_enabled": true },
  "tts": { "port": 5048, "default_voice": "zh-CN-XiaoxiaoNeural" }
}
```

实时语音对话（需通义千问 DashScope API Key）：

```json
{
  "voice_realtime": {
    "enabled": true,
    "provider": "qwen",
    "api_key": "your-dashscope-key",
    "model": "qwen3-omni-flash-realtime"
  }
}
```
</details>

<details>
<summary><b>Live2D 虚拟形象（PyQt5 GUI）</b></summary>

```json
{
  "live2d": {
    "enabled": true,
    "model_path": "path/to/your/model.model3.json"
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
| API Server | 8000 | 主接口，对话、配置、认证、Skill 市场 |
| Agent Server | 8001 | 意图分析、任务调度、OpenClaw |
| MCP Server | 8003 | MCP 工具注册与调度 |
| Voice Service | 5048 | TTS / ASR |
| Neo4j | 7687 | 知识图谱（可选） |

---

## 更新

```bash
python update.py        # 自动 git pull + 依赖同步
```

---

## 故障排除

| 问题 | 解决方案 |
|------|----------|
| Python 版本不兼容 | 使用 Python 3.11；或使用 uv（自动管理 Python 版本） |
| 端口被占用 | 检查 8000、8001、8003、5048 是否可用 |
| Neo4j 连接失败 | 确认 Neo4j 服务已启动，检查 config.json 中的连接参数 |
| 启动卡在进度条 | 检查 API Key 是否配置正确；Electron 环境可尝试重启应用 |

```bash
# 环境诊断
python main.py --check-env --force-check
python main.py --quick-check
```

---

## 构建

```bash
python build.py         # 构建 Windows 一键运行整合包，输出到 dist/
```

---

## 贡献

欢迎提交 Issue 和 Pull Request。

---

## 许可证

[MIT License](LICENSE)

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=Xxiii8322766509/NagaAgent&type=date&legend=top-left)](https://www.star-history.com/#Xxiii8322766509/NagaAgent&type=date&legend=top-left)
