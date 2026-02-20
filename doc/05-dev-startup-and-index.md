# NagaAgent Dev Startup And Directory Index

This document is a practical runbook for local development.
It focuses on two goals:

1. Start the full local toolchain quickly.
2. Find the right module directory fast when debugging.

## 1. Quick Start (Frontend path, all-in-one)

Run from `frontend`:

```powershell
cd E:\Programs\NagaAgent\frontend
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
npm run dev
```

Notes:

- `npm run dev` uses `frontend/scripts/dev.mjs`.
- It starts Vite and Electron-side dev build/watch.
- It also starts backend headless from project root (`main.py --headless`) via Electron main process.
- If `5173` is occupied, Vite will auto-switch to another port (for example `5174`).

Why clear `ELECTRON_RUN_AS_NODE`:

- If this env var is `1`, Electron may run as plain Node and fail with errors like:
  - `The requested module 'electron' does not provide an export named 'BrowserWindow'`

## 2. Alternative Start Modes

### 2.1 Backend only (root)

```powershell
cd E:\Programs\NagaAgent
uv run main.py
```

### 2.2 Backend headless only (root)

```powershell
cd E:\Programs\NagaAgent
python main.py --headless
```

### 2.3 API server only (root)

```powershell
cd E:\Programs\NagaAgent
uvicorn apiserver.api_server:app --host 127.0.0.1 --port 8000 --reload
```

### 2.4 Frontend web-only (no Electron)

```powershell
cd E:\Programs\NagaAgent\frontend
npm run dev:web
```

## 3. Directory Index (Top Level)

- `main.py`: backend orchestration entry.
- `apiserver/`: chat API, streaming, tool dispatch.
- `agentserver/`: intent analysis, task scheduling, OpenClaw integration.
- `mcpserver/`: MCP registry/manager and built-in MCP agents.
- `summer_memory/`: GRAG memory and Neo4j integration.
- `voice/`: TTS/ASR/realtime voice.
- `guide_engine/`: game-guide RAG and calculators.
- `frontend/`: Electron + Vue app.
- `system/`: config, prompts, logging, environment checks.
- `scripts/`: build and utility scripts.
- `logs/`: runtime logs.
- `sessions/`: session snapshots and conversation state files.

## 4. Frontend Directory Index

- `frontend/package.json`: scripts (`dev`, `dev:web`, `build`, `dist`).
- `frontend/scripts/dev.mjs`: dev launcher for Vite.
- `frontend/electron/`: Electron main/preload code.
- `frontend/src/`: Vue renderer code.
- `frontend/public/`: static assets.
- `frontend/release/`: packaged output.
- `frontend/backend-dist/`: backend bundle used by packaged app.

## 5. OpenClaw Auth/Troubleshooting (401/400)

### 5.1 Validate local OpenClaw config

Config path:

- `C:\Users\<your-user>\.openclaw\openclaw.json`

Required fields:

- `hooks.enabled = true`
- `hooks.token` is present
- `hooks.allowRequestSessionKey = true`
- `gateway.auth.token` is present

Important:

- `/hooks/*` endpoints use `hooks.token`
- `/tools/invoke` uses `gateway.auth.token`
- These two tokens are usually different. Mixing them will cause `401 Unauthorized`.

### 5.2 Gemini Provider Mode (Fix "400 status code (no body)")

If your Naga model is Gemini, OpenClaw should use the native Gemini API:

- `models.providers.naga.api = "google-generative-ai"`
- `models.providers.naga.baseUrl = "https://generativelanguage.googleapis.com/v1beta"`

If you configure Gemini via OpenAI-compat (`openai-completions` + `/openai`), OpenClaw may fail during tool calls with:

- `400 status code (no body)`

### 5.3 Quick checks

Check frontend dev env var:

```powershell
echo $env:ELECTRON_RUN_AS_NODE
```

Check backend health:

```powershell
curl http://127.0.0.1:8001/health
curl http://127.0.0.1:8001/openclaw/health
```

Run OpenClaw connectivity test (no hardcoded secrets):

```powershell
cd E:\Programs\NagaAgent
python agentserver/openclaw/test_connection.py
```

Expected:

- `GET /` returns `200` (HTML is fine).
- `/hooks/agent` returns `200/202`.
- The poll step prints a real assistant reply (not `400 status code (no body)`).

### 5.4 sessions_history Visibility (forbidden / empty history)

OpenClaw can enforce `tools.sessions.visibility=tree`.

In that mode, when calling `sessions_history`:

- `POST /tools/invoke` must include a **top-level** `sessionKey`
- and it must match `args.sessionKey`
- and it must be the full gateway session key: `agent:<agent_id>:<your_session_key>` (usually `agent:main:...`)

### 5.5 Where To Read OpenClaw Logs (API + Output)

Primary logs:

- `logs/details/openclaw.log`: OpenClaw dedicated file (recommended).
- `logs/details/naga-backend.log`: full backend debug log (noisier).

What you should see (after `agentserver/openclaw/openclaw_client.py` changes):

- Outbound API call: `POST /hooks/agent` (send message)
- Outbound API call: `POST /tools/invoke` with `tool=sessions_history` (poll)
- Response preview: `/hooks/agent response status=... body=...`
- Response preview: `/tools/invoke response status=... body=...`
- Parsed assistant meta: `sessions_history assistant_meta=...`
- Output preview: `sessions_history latest_reply=...`

Structured inspection (no log scraping):

- Agent Server: `GET /openclaw/tasks/{task_id}/detail?include_history=true`
- Returns local `events` (request/response summaries) and optionally the raw `sessions_history` result.
- Add `include_tools=true` if you need tool messages / command outputs in history.

## 6. Recommended Daily Workflow

1. Start from `frontend` with:
   - `Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue`
   - `npm run dev`
2. Confirm backend health endpoint returns `200`.
3. Reproduce and inspect logs in `logs/details/naga-backend.log`.
4. Stop and restart dev stack after config changes affecting OpenClaw tokens or hooks.

## 7. Local-First Tooling (Native Infrastructure)

`AgenticLoop` now supports a local-first execution path for basic tasks:

- `agentType: "native"` tools:
  - `read_file`
  - `write_file`
  - `run_cmd`
  - `search_keyword`
  - `query_docs`
  - `list_files`
- Compatibility mode:
  - If model still outputs `agentType: "openclaw"` for simple local tasks, dispatcher tries to intercept and reroute to native first.
  - Complex cross-app/web tasks still go to OpenClaw.

Key files:

- `apiserver/native_tools.py`: native tool router/executor and openclaw interception rules.
- `apiserver/agentic_tool_loop.py`: tool dispatch integration (`native` + local-first interception).
- `system/native_executor.py`: hardened local command/file executor with project-root sandbox.
