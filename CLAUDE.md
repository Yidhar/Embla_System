# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Embla System is a dual-service AI runtime platform (v5.0.0) with streaming tool calls, knowledge-graph memory (GRAG), and an ops dashboard. The primary language is Chinese (zh-CN) for UI/logs/comments; code identifiers and docs are in English.

## Commands

### Backend (Python 3.11, uv-managed)

```bash
# Install dependencies
uv sync

# Start all services (API Server :8000 + MCP client pool + watchdog)
python main.py
python main.py --headless          # non-interactive / CI

# Start individual services
uvicorn apiserver.api_server:app --host 127.0.0.1 --port 8000 --reload

# Environment diagnostics
python main.py --check-env --force-check
python main.py --quick-check
```

### Frontend (Embla_core — Next.js 15 / React 19)

```bash
cd Embla_core
npm install
npm run dev        # dev server
npm run build      # production build
npm run lint       # ESLint
```

### Tests (pytest)

```bash
# Run all tests (testpaths = ["tests"])
uv run pytest

# Run a single test file
uv run pytest tests/test_agent_roles_ws30_005.py

# Run a single test function
uv run pytest tests/test_agent_roles_ws30_005.py::test_function_name -v

# pytest is configured with: -q -p no:cacheprovider
# norecursedirs: .git, .venv, __pycache__, tests/archived, build, dist, node_modules
```

### Linting

```bash
# Python — ruff (line-length = 120)
uv run ruff check .
uv run ruff format .
```

## Architecture

### Service Topology

```
Embla_core (Next.js dashboard :3000)
    │
    ▼
API Server (:8000)
    │
    ├─ LLM Service (litellm, streaming tool_calls)
    ├─ Native Tools (sandboxed OS execution)
    ├─ MCP Client Pool (stdio, embedded — agents/runtime/mcp_client.py)
    │   └─ Neo4j (:7687, optional, for GRAG)
    └─ Core Job Manager (async Shell→Core dispatch lifecycle)
```

`main.py` orchestrates startup: BoxLite runtime init → memory init → MCP client pool (embedded, not a separate service) → API server → watchdog supervision loop.

### Multi-Agent Pipeline

Hierarchical agent chain with locked prompt DNA at each tier:

```
ShellAgent (read-only tools, user-facing routing)
  └─► CoreAgent (goal decomposition, expert selection)
       └─► ExpertAgent (domain-specific planning, TaskBoard)
            └─► DevAgent (execution with mini tool-loop)
                 └─► ReviewAgent (quality gate)
```

- **`agents/pipeline.py`** — orchestration engine (Shell → Core → Expert → Dev → Review)
- **`agents/tool_loop.py`** — agentic loop core: tool call → result → next reasoning round
- **`agents/router_engine.py`** — deterministic routing with `RouterRequest`/`RouterDecision` Pydantic models
- **`agents/runtime/`** — session store (SQLite), mailbox, task board, tool profiles

### Key Backend Modules

| Module | Role |
|--------|------|
| `apiserver/api_server.py` | FastAPI main app — routes, SSE streaming, session state |
| `apiserver/llm_service.py` | LiteLLM unified inference, immutable DNA injection |
| `apiserver/routes_chat.py` | Chat session domain, model override, prompt hints |
| `apiserver/native_tools.py` | Sandboxed file/shell/git/python-repl execution |
| `apiserver/core_job_manager.py` | Core execution job queue and lifecycle |
| `system/config.py` | Pydantic config model, `build_system_prompt()`, hot-reload |
| `core/security/immutable_dna.py` | SHA-256 prompt integrity verification |
| `core/security/lease_fencing.py` | Single-active lease for autonomous orchestrator |
| `core/event_bus/topic_bus.py` | Pub/sub event routing (SQLite primary, optional JSONL mirror) |
| `core/event_bus/runtime_views.py` | Shared runtime posture aggregation from canonical event DB |
| `core/event_bus/consumers.py` | Optional materialized-view consumers (not auto-registered in production) |
| `core/security/killswitch.py` | Physical kill switch, used by native_tools + routes_ops |
| `core/security/budget_guard.py` | Cost/quota guard, used by tool_loop |
| `core/supervisor/watchdog_daemon.py` | Resource/cost/anomaly watchdog, started by main.py |
| `system/execution_backend/` | Three-tier execution backend router (native/os_sandbox/boxlite) |
| `system/sandbox_context.py` | Unified execution context (backend, worktree, project root) |
| `summer_memory/` | GRAG quintuple extraction, Neo4j + local file dual storage, RAG query |

### Prompt Governance

Canonical prompts live in `system/prompts/` (not the top-level `prompts/` staging dir):
- **DNA files** (`system/prompts/dna/`, `system/prompts/core/dna/`) are immutable — verified by SHA-256 manifest at `system/prompts/immutable_dna_manifest.spec`
- Prompt registry: `system/prompts/specs/prompt_registry.spec`
- Prompt ACL: `system/prompts/specs/prompt_acl.spec`
- `PromptAssembler` in `agents/prompt_engine.py` handles variable injection and DNA integrity checks

### Configuration

- **`config.json`** — runtime config (copy from `config.json.example`). Supports all OpenAI-compatible APIs. Has per-route API overrides (`api.routing.shell`, `api.routing.core`, `api.specialized.*`).
- **`embla_system.yaml`** — system-level config: security posture, audit, immutable DNA prompt lists, heartbeat intervals. Loaded by `system/config.py` with env override `EMBLA_SYSTEM_CONFIG_PATH`.
- **`config/retrieval_budget.yaml`** — RAG token/fact budget limits
- **`config/autonomous_runtime.yaml`** — autonomous loop, lease, subagent SLA
- **`policy/gate_policy.yaml`** — release gates (read_only → write_repo → deploy → secrets)

### Execution Backends

Three sandboxing tiers configured via `config.json` → `sandbox`:
1. **Native** — direct OS execution with project-root confinement
2. **OS Sandbox** — worktree-based with network guard, timeout profiles (`default`, `networked`, `heavy`)
3. **BoxLite** — Docker-based strong isolation (opt-in, not default)

### Frontend (Embla_core)

Next.js App Router with dashboard layout group `app/(dashboard)/`:
- Pages: `runtime-posture`, `chatops`, `mcp-fabric`, `memory-graph`, `workflow-events`, `incidents`, `evidence`, `settings`, `agent-config`
- i18n: `lib/i18n.ts` (~1500 translations, zh-CN default + en-US), cookie-based locale (`embla_locale`)
- API client: `lib/api/ops.ts` calls `/v1/*` endpoints
- Types: `lib/types.ts`; view transforms: `lib/view-models.ts`

## Conventions

- **Test naming**: `test_<feature>_ws<workshop_number>_<sequence>.py` — the `ws##` tag tracks the workstream/milestone that introduced the test
- **Script naming**: scripts in `scripts/` also carry `ws##` tags for traceability
- **Ruff**: line-length 120, enforced via `pyproject.toml`
- **Skills**: defined in `skills/<name>/SKILL.md` with YAML frontmatter (Level 1 metadata) + markdown body (Level 2 instructions)
- **MCP tools**: discovered via `agents/runtime/mcp_client.py` (stdio client pool); configured in `mcp_servers.json`. The former `mcpserver/` package was removed — MCP is now an embedded client, not a separate service
- **Agent sessions**: SQLite at `scratch/runtime/agent_sessions.db`; events at `logs/autonomous/events.jsonl`
- **Audit**: signed JSONL ledger at `scratch/runtime/audit_ledger.jsonl`
