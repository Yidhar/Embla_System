# Agent Server

`agentserver/agent_server.py` is a lightweight FastAPI service for task-memory introspection.

## Scope

- Provides health check endpoint.
- Exposes task/session memory APIs backed by `agentserver/task_scheduler.py`.
- Keeps `/schedule` and `/analyze_and_execute` only as deprecated compatibility endpoints.

## Run

```bash
uvicorn agentserver.agent_server:app --host 127.0.0.1 --port 8001
```

## Main Endpoints

- `GET /health`
- `POST /schedule` (deprecated)
- `POST /analyze_and_execute` (deprecated)
- `GET /tasks`
- `GET /tasks/{task_id}`
- `GET /tasks/{task_id}/memory`
- `POST /tasks/{task_id}/steps`
- `DELETE /tasks/{task_id}/memory`
- `GET /memory/global`
- `DELETE /memory/global`
- `GET /sessions`
- `GET /sessions/{session_id}/memory`
- `GET /sessions/{session_id}/compressed_memories`
- `GET /sessions/{session_id}/key_facts`
- `GET /sessions/{session_id}/failed_attempts`
- `GET /sessions/{session_id}/tasks`
- `DELETE /sessions/{session_id}/memory`
