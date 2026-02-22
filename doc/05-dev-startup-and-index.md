# NagaAgent Dev Startup And Directory Index

This runbook is a practical, up-to-date guide for local development.

## 1. Goals

- Start backend and frontend quickly in dev mode.
- Know where core modules live and how to troubleshoot common failures.

## 2. Quick Start

### 2.1 Backend (recommended)

```powershell
cd E:\Programs\NagaAgent
uv sync
uv run main.py
```

### 2.2 Backend (headless mode for frontend work)

```powershell
cd E:\Programs\NagaAgent
python main.py --headless
```

### 2.3 Frontend

```powershell
cd E:\Programs\NagaAgent\frontend
npm install
npm run dev
```

## 3. Service Ports

- `API Server`: `8000`
- `Agent Server`: `8001`
- `MCP Server`: `8003`
- `Voice Service`: `5048`

## 4. Module Index

- `main.py`: backend bootstrap and orchestration.
- `apiserver/`: chat API, streaming responses, tool-loop integration, config APIs.
- `agentserver/`: background intent analysis, scheduling, session/task state.
- `mcpserver/`: MCP registry, tool dispatch, service integration.
- `summer_memory/`: memory graph and persistence integration.
- `voice/`: TTS/ASR/realtime voice components.
- `frontend/`: Electron + Vue app.
- `system/`: config, logging, prompt loading, parsing utilities.

## 5. LLM Routing Notes

Current architecture uses OpenAI-compatible chat completions as the unified path.

For Gemini models, configure OpenAI-compatible base URL (example):

- `https://generativelanguage.googleapis.com/v1beta/openai/`

Recommended checks:

- `config.json` has valid `api.base_url`, `api.api_key`, `api.model`.
- selected model supports tool/function calling if your workflow depends on tools.

## 6. Health Checks

```powershell
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8001/health
```

If either endpoint fails:

- verify process is running
- verify port is not occupied
- check logs under `logs/details/`

## 7. Tooling Execution Chain (Current)

- LLM emits structured `tool_calls`.
- `apiserver/agentic_tool_loop.py` parses and validates calls.
- Native local tools are handled by `apiserver/native_tools.py`.
- MCP tools are dispatched through `mcpserver/`.

## 8. Troubleshooting Checklist

1. Confirm Python and Node dependencies are installed (`uv sync`, `npm install`).
2. Confirm backend starts without import/config errors.
3. Confirm health endpoints return `200`.
4. Reproduce with minimal prompt and inspect `logs/details/naga-backend.log`.
5. Run static checks when making large edits:

```powershell
python -m py_compile apiserver\llm_service.py apiserver\api_server.py apiserver\native_tools.py
cd frontend; npx vue-tsc -b --pretty false
```