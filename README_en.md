<div align="center">

# NagaAgent

**Dual-Service Runtime Platform — Streaming Tool Calls · Knowledge Graph Memory · Ops Dashboard**

[简体中文](README.md) | [English](README_en.md)

![NagaAgent](https://img.shields.io/badge/NagaAgent-5.0.0-blue?style=for-the-badge&logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-green?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.11-blue?style=for-the-badge&logo=python)

[![Stars](https://img.shields.io/github/stars/Xxiii8322766509/NagaAgent?style=social)](https://github.com/Xxiii8322766509/NagaAgent)
[![Forks](https://img.shields.io/github/forks/Xxiii8322766509/NagaAgent?style=social)](https://github.com/Xxiii8322766509/NagaAgent)
[![Issues](https://img.shields.io/github/issues/Xxiii8322766509/NagaAgent)](https://github.com/Xxiii8322766509/NagaAgent/issues)

**[QQ Bot Integration: Undefined QQbot](https://github.com/69gg/Undefined/)**

</div>

---

## Overview

The active runtime pipeline consists of two backend services (plus one optional debug service):

| Service | Port | Responsibilities |
|---------|------|-----------------|
| **API Server** | 8000 | Chat, streaming tool calls, document upload, system config, runtime aggregation |
| **MCP Server** | 8003 | MCP tool registration / discovery / parallel dispatch |
| **LLM Service (Optional Debug)** | 8001 | Standalone `apiserver.llm_service` entry for debug (not started by default in `main.py`) |

`main.py` orchestrates `API + MCP` by default and conditionally starts the `autonomous` background loop. The active frontend is `Embla_core` (Next.js ops dashboard).

---

## Updates

| Date | Changes |
|------|---------|
| **2026-02-27** | Retired Live2D runtime path: removed `live2d_action` dispatch, `/live2d/actions` API, and related config fields; tool execution now converges on `native/mcp` only |
| **2026-02-19** | Core Architecture Refactoring: Introduced Autonomous SDLC framework (with Lease/Fencing); Native structured tool_calls fully take over the execution layer |
| **2026-02-14** | 5.0.0 Release: Remote memory microservice (NagaMemory Cloud + Local GRAG fallback), MindView 3D rewrite, startup title animation |
| **2026-02-14** | Captcha integration, registration flow (username + email + captcha), CAS session expiration dialog, voice input button, file parsing button |
| **2026-02-14** | Removed local ChromaDB dependency (-1119 lines), complete cloud migration of game guide, added login gating to guide function |
| **2026-02-13** | Floating ball mode (4 state animations: classic / ball / compact / full), automatic switching of multimodal visual model for screenshots |
| **2026-02-13** | Skill workshop refactor + Live2D emotion channel independent + naga-config skill |
| **2026-02-12** | NagaCAS authentication + NagaModel gateway routing + login dialog + user menu |
| **2026-02-12** | Live2D 4-channel orthogonal animation (body state / actions / emotions / tracking), window-level gaze tracking with calibration |
| **2026-02-12** | Agentic Tool Loop: streaming tool extraction + multi-round auto-execution + parallel MCP/Native/Live2D dispatch |
| **2026-02-12** | Arknights-style splash screen + progress tracking + view preloading + mouse parallax effect |
| **2026-02-12** | Game guide MCP integration (auto-screenshot + vision model + Neo4j import + 6 game RAG processors) |
| **2026-02-11** | Backend packaging optimization, auto-generate config from template on startup |
| **2026-02-10** | Backend packaging optimization, skill workshop MCP status fix, frontend bug fixes |
| **2026-02-09** | Frontend refactor, Live2D eye tracking disable, AgentServer naming alignment |

---

## Core Modules

### Streaming Tool Call Loop (Structured tool_calls & Local-first Native)

The primary pipeline of NagaAgent is now completely driven by **structured `tool_calls` channels**:
The LLM no longer triggers tools by emitting ` ```tool ` code blocks. Instead, it natively outputs a list of structured tool intent objects. AgenticLoop consumes these independently of standard conversation text, severely reducing formatting drift and parser failures.

**Core Mechanism:**

```text
LLM Stream Output (content/reasoning) ──SSE──▶ Real-time Frontend Display
            │
            ├─ delta.tool_calls increments
            ▼
      LLMService merges tool_calls, emitting type=tool_calls stream into Loop
            │
            ▼
AgenticLoop converts calls into actionable execution arrays (with concurrency limits)
    ├─ mcp      → MCPManager.unified_call()
    ├─ native   → Local-first NativeToolExecutor (Intercepts e.g., 'cd' to 'get_cwd', enforcing Sandbox rules)
            │
            ▼
 Tool results inject into the message list, triggering the next inference round
```

Source: [`apiserver/llm_service.py`](apiserver/llm_service.py), [`agents/tool_loop.py`](agents/tool_loop.py) (canonical; `apiserver/agentic_tool_loop.py` is a compatibility shim), [`apiserver/native_tools.py`](apiserver/native_tools.py)

---

### GRAG Knowledge Graph Memory

GRAG (Graph-RAG) automatically extracts quintuples `(subject, subject_type, predicate, object, object_type)` from conversations, stores them in Neo4j, and retrieves relevant memories as LLM context during chat.

**Extraction pipeline**:

1. **Structured output** (preferred): Calls `beta.chat.completions.parse()` with Pydantic model `QuintupleResponse`, `temperature=0.3`, up to 3 retries
2. **JSON fallback**: Prompts LLM to return a JSON array; on parse failure, extracts content between the first `[` and last `]`
3. **Filtering rules**: Only factual information (behaviors, entity relations, states, preferences); filters metaphors, hypotheticals, emotions, chitchat
4. **Entity types**: person / location / organization / item / concept / time / event / activity

**Task manager**:

- 3 asyncio worker coroutines consuming from `asyncio.Queue(maxsize=100)`
- SHA-256 deduplication: identical text with PENDING/RUNNING tasks is skipped
- Hourly auto-cleanup of tasks older than 24h
- Configurable timeout (default 12s) and retry count (default 2)

**Dual storage**:

- Local file `logs/knowledge_graph/quintuples.json` (JSON array, set-based dedup)
- Neo4j graph: `Entity` nodes + typed `Relationship` edges, `graph.merge()` upsert

**RAG retrieval**:

1. Extract keywords from user question (LLM-generated)
2. Cypher query: `MATCH (e1:Entity)-[r]->(e2:Entity) WHERE e1.name CONTAINS '{kw}' ... LIMIT 5`
3. Format as `subject(type) —[predicate]→ object(type)` and inject into LLM context

**Current memory access mode**:

- `summer_memory/memory_client.py` is currently a local-only shim (`get_remote_memory_client()` always returns `None`)
- Chat flow falls back to local GRAG by default
- API Server exposes local memory endpoints such as `memory/stats`, `memory/quintuples`, and `memory/quintuples/search`

Source: [`summer_memory/`](summer_memory/)

---

### MCP Tool System

A pluggable tool architecture based on the [Model Context Protocol](https://modelcontextprotocol.io/), with each tool running as an independent agent.

**Built-in agents** (repo verification: 2026-02-27):

| Agent | Directory | Function | Status |
|-------|-----------|----------|--------|
| `weather_time` | `mcpserver/agent_weather_time/` | Weather queries/forecasts, system time, auto city/IP detection | `available` |
| `app_launcher` (`open_launcher` alias) | `mcpserver/agent_open_launcher/` | Scan installed apps, launch programs via natural language | `available` |
| `online_search` | `mcpserver/agent_online_search/` | Web search via SearXNG | `available` |
| `crawl4ai` | `mcpserver/agent_crawl4ai/` | Web crawling and structured content extraction | `available` |
| `playwright_master` | `mcpserver/agent_playwright_master/` | Browser automation via Playwright | `available` |
| `vision` | `mcpserver/agent_vision/` | Screenshot analysis and visual Q&A | `available` |
| `mqtt_tool` | `mcpserver/agent_mqtt_tool/` | IoT device control via MQTT | `missing` (directory absent) |
| `office_doc` | `mcpserver/agent_office_doc/` | docx/xlsx content extraction | `available` |

**Registration & discovery**:

```
mcpserver/
├── agent_weather_time/
│   ├── agent-manifest.json    ← Declares name, entryPoint.module/class, capabilities
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
└── mcp_registry.py            ← scan_and_register_mcp_agents() globs **/agent-manifest.json
                                   importlib.import_module(module).ClassName() dynamic instantiation
```

- `MCPManager.unified_call(service_name, tool_call)` routes to the agent's `handle_handoff()`
- MCP Server `POST /schedule` supports batch calls via `asyncio.gather()` for parallel execution
- **Skill Market**: Frontend skill workshop supports one-click installation of community skills (Agent Browser, Brainstorming, Context7, Firecrawl Search, etc.), backend uses `/skills/import` for custom skill import

Source: [`mcpserver/`](mcpserver/)

---

### Legacy Desktop Lane (Retired)

The old Electron + Vue frontend has been removed from this repository and is no longer part of release gates.

---

### Voice Module Status

The historical `voice/` implementation has been removed from the active runtime path.  
The current repository no longer ships built-in TTS/ASR services.

---

### Autonomous (Primary Execution Path)

**Current state**:
The legacy `agentserver` pipeline has been removed from this repository. Runtime execution and governance are unified on `apiserver` + `autonomous` + `mcpserver`.

**Autonomous Module** (Located in `autonomous/`):
The system uses a robust, highly-automated SDLC (Software Development Life Cycle) architecture tailored for complex software engineering:

- **Single Active Lease**: Utilizes a highly consistent DB lock (`workflow.db`) and Fencing epochs, guaranteeing exactly one Active Orchestrator modifies the codebase at a time.
- **State Machine Engine**: Robust idempotency mechanisms drive tasks through `GoalAccepted` -> `PlanDrafted` -> `Implementing` (SubAgent + NativeExecutionBridge) -> `Verifying`.
- **Evaluator & Reworker**: Verification failures are handled by native governance loops (contract/scaffold/risk/incident) instead of black-box external fallback agents.
- **Release Controller (Gray Release)**: Updates aren't directly applied to prod. They enter a Canary execution pool. AI dictates if a release is Promoted or trigger Auto-Rollback based strictly on P95 latency and runtime Error Rate.

This transforms Naga from an assistant into a smart development server capable of unsupervised marathon execution.

Source: [`autonomous/`](autonomous/)

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                Embla_core (Next.js Frontend)        │
└────────────┬─────────────────────────────────────────┘
             │
     ┌───────▼──────────┐      ┌─────────────────────┐
     │    API Server    │─────►│ Autonomous Subsystem│
     │      :8000       │      │       (SDLC)        │
     │ - Chat / SSE     │      └─────────────────────┘
     │ - Native Ops     │
     │ - Auth Proxy     │      ┌─────────────────────┐
     │ - Config API     │─────►│     MCP Server      │
     └──────────────────┘      │        :8003        │
                                │ - Registry/Dispatch │
                                └─────────┬───────────┘
                                          │
                                ┌─────────▼───────────┐
                                │ MCP Agents          │
                                │ (Pluggable)         │
                                └─────────┬───────────┘
                                          │
                                ┌─────────▼───────────┐
                                │ Neo4j :7687         │
                                │ Knowledge Graph     │
                                └─────────────────────┘
```

### Directory Structure

```
NagaAgent/
├── apiserver/            # API Server — Dialogue, Native tools, Auth, Config
│   ├── api_server.py     #   FastAPI Main App (route entry + SSE adapter)
│   ├── agentic_tool_loop.py  #   Compatibility shim → agents/tool_loop.py
│   ├── native_tools.py   #   Local-First interception tools
│   └── llm_service.py    #   LiteLLM Unified Caller & tool_calls stream
├── agents/               # Brain layer — production multi-agent runtime
│   ├── pipeline.py       #   Unified Shell/Core pipeline entry
│   ├── tool_loop.py      #   Canonical structured tool loop
│   ├── shell_agent.py    #   Outer Shell routing + readonly tools
│   ├── core_agent.py     #   Core decomposition/orchestration
│   └── runtime/          #   TaskBoard / Session / Mailbox runtime
├── autonomous/           # All-new Autonomous SDLC Agent
│   ├── system_agent.py   #   Single Active Orchestrator
│   ├── planner.py        #   Strategy decomposition
│   └── release/          #   Fallback and Canary Releases
├── mcpserver/            # MCP Server — Tool reg & dispatchration & dispatch
│   ├── mcp_server.py     #   FastAPI main app
│   ├── mcp_registry.py   #   Manifest scanning + dynamic registration
│   ├── mcp_manager.py    #   unified_call() routing
│   ├── agent_weather_time/
│   ├── agent_open_launcher/
│   ├── agent_online_search/
│   ├── agent_crawl4ai/
│   ├── agent_playwright_master/
│   ├── agent_vision/
│   ├── agent_office_doc/
│   └── (other agents are extension slots)
├── summer_memory/        # GRAG knowledge graph
│   ├── quintuple_extractor.py  #   Quintuple extraction (structured output + JSON fallback)
│   ├── quintuple_graph.py      #   Neo4j + file dual storage
│   ├── quintuple_rag_query.py  #   Cypher keyword RAG retrieval
│   ├── task_manager.py         #   3-worker async task manager
│   ├── memory_manager.py       #   GRAG orchestrator
│   └── memory_client.py        #   NagaMemory remote client
├── Embla_core/           # Next.js runtime posture dashboard (active)
├── system/               # Config loader, env checker, system prompts, background analyzer
├── main.py               # Unified entry point, orchestrates all services
├── config.json           # Runtime config (copy from config.json.example)
└── pyproject.toml        # Project metadata & dependencies
```

---

## Quick Start

### Requirements

- Python 3.11 (`>=3.11, <3.12`)
- Optional: [uv](https://github.com/astral-sh/uv) (faster dependency installation)
- Optional: Neo4j (knowledge graph memory)

### Installation

```bash
git clone https://github.com/Xxiii8322766509/NagaAgent.git
cd NagaAgent

# Option 1: Using uv (recommended)
uv sync

# Option 2: Manual pip
python -m venv .venv
source .venv/bin/activate  # Windows: .\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Configuration

Copy `config.json.example` to `config.json` and fill in your LLM API credentials:

```json
{
  "api": {
    "api_key": "your-api-key",
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-v3.2"
  }
}
```

Works with any OpenAI-compatible API (DeepSeek, Qwen, OpenAI, Ollama, etc.).

### Launch

```bash
python main.py             # Full launch (API + MCP + optional autonomous backend)
uv run main.py             # Using uv
python main.py --headless  # Headless mode (skip interactive prompt; for web/remote frontend)
```

All services are orchestrated by `main.py`. For development, each can be started independently:

```bash
uvicorn apiserver.api_server:app --host 127.0.0.1 --port 8000 --reload
uvicorn mcpserver.mcp_server:app --host 127.0.0.1 --port 8003 --reload
```

### Embla_core Frontend Development (Active)

```bash
cd Embla_core
npm install
npm run dev    # Next.js dev mode
npm run build  # Next.js production build
```

## Optional Configuration

<details>
<summary><b>Knowledge Graph Memory (Neo4j)</b></summary>

Install Neo4j ([Docker](https://hub.docker.com/_/neo4j) or [Neo4j Desktop](https://neo4j.com/download/)), then configure:

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
<summary><b>MQTT IoT</b></summary>

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

## Ports

| Service | Port | Description |
|---------|------|-------------|
| API Server | 8000 | Main interface: chat, config, auth, Skill Market |
| MCP Server | 8003 | MCP tool registration & dispatch |
| LLM Service (Optional Debug) | 8001 | Standalone `apiserver.llm_service` port (not launched by `main.py` by default) |
| Neo4j | 7687 | Knowledge graph (optional) |

---

## Updating

```bash
git pull --ff-only
uv sync
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Python version mismatch | Use Python 3.11, or use uv (manages Python versions automatically) |
| Port in use | Check ports 8000 and 8003 first (check 8001 only when launching `llm_service` separately) |
| Neo4j connection failed | Ensure Neo4j is running, verify config.json connection parameters |
| Progress bar stuck | Check API key config; restart hint appears after 3s; the launcher auto-polls backend health |

```bash
python main.py --check-env --force-check  # Environment diagnostics
python main.py --quick-check              # Quick check
```

---

## Building

```bash
python scripts/build-win.py  # Build Windows one-click runner package, output to dist/
```

---

## Contributing

Issues and Pull Requests are welcome.

---

## License

[MIT License](LICENSE)

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=Xxiii8322766509/NagaAgent&type=date&legend=top-left)](https://www.star-history.com/#Xxiii8322766509/NagaAgent&type=date&legend=top-left)
