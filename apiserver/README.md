# NagaAgent API Server

文档状态：As-Is（运行主链）
最后更新：2026-02-28

## 1. 角色定位

`apiserver/` 是当前系统的 BFF 入口，负责：

- 对话与流式 SSE（`/chat`、`/chat/stream`）
- Agentic 工具循环编排（`native_call` / `mcp_call`）
- 配置读写与系统信息接口
- MCP 服务发现与导入管理接口
- OPS 聚合查询接口（供 `Embla_core` 消费）

## 2. 关键模块

- `api_server.py`：FastAPI 主应用与路由聚合
- `agentic_tool_loop.py`：结构化工具循环（多轮执行、事件回推）
- `native_tools.py`：本地工具适配层
- `llm_service.py`：LLM 请求与流式输出封装
- `start_server.py`：API/LLM 调试服务启动脚本

## 3. 启动方式

推荐通过仓库根目录统一启动（主链）：

```bash
python main.py
```

独立启动 API：

```bash
uvicorn apiserver.api_server:app --host 127.0.0.1 --port 8000 --reload
```

独立启动 LLM 调试服务（非主链）：

```bash
python apiserver/start_server.py llm
# 或
uvicorn apiserver.llm_service:llm_app --host 127.0.0.1 --port 8001 --reload
```

## 4. 主接口（当前可用）

### 4.1 基础与系统

- `GET /health`、`GET /v1/health`
- `GET /system/info`、`GET /v1/system/info`
- `GET /system/config`
- `POST /system/config`
- `GET /system/api-contract`

### 4.2 对话

- `POST /chat`、`POST /v1/chat`
- `POST /chat/stream`、`POST /v1/chat/stream`
- `GET /chat/route_bridge/{session_id}`、`GET /v1/chat/route_bridge/{session_id}`

### 4.3 会话

- `GET /sessions`
- `GET /sessions/{session_id}`
- `DELETE /sessions/{session_id}`
- `DELETE /sessions`

### 4.4 记忆

- `GET /memory/stats`
- `GET /memory/quintuples`
- `GET /memory/quintuples/search`

说明：`summer_memory/memory_client.py` 当前为 local-only shim，远程 client 默认不启用。

### 4.5 MCP 管理

- `GET /mcp/status`
- `GET /mcp/tasks`
- `GET /mcp/services`
- `POST /mcp/import`

说明：`/mcp/status` 与 `/mcp/tasks` 当前返回运行态快照语义；底层 `mcpserver` 仍可独立健康检查。

### 4.6 OPS 聚合（Embla_core 消费）

- `GET /v1/ops/runtime/posture`
- `GET /v1/ops/mcp/fabric`
- `GET /v1/ops/memory/graph`
- `GET /v1/ops/workflow/events`
- `GET /v1/ops/incidents/latest`
- `GET /v1/ops/evidence/index`

### 4.7 文件上传

- `POST /upload/document`
- `POST /upload/parse`

## 5. 流式协议要点

`/chat/stream` 返回 `text/event-stream`。

- 默认协议：结构化 JSON SSE（`data: <json-object>`，`stream_protocol=sse_json_v1`）
- Legacy Base64 协议已下线：请求 `stream_protocol="sse_base64"` / `legacy` 会返回 `410`.
- 未知 `stream_protocol` 会返回 `400`（不再自动回落兼容）。

常见事件类型包括：

- `content`
- `reasoning`
- `route_decision`
- `tool_stage`
- `round_end`
- `error`

## 6. 当前口径说明

- 已弃用的旧 HANDOFF 文本协议不再作为主链文档口径。
- Legacy `agentserver` 不在当前仓库，禁止新增依赖描述。
- 文档若出现 `frontend/voice/agentserver` 路径，应视作历史归档信息。
