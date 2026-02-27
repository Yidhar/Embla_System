# 05 开发启动与目录索引（Omni-Operator 开发预备版）

文档状态：开发预备（As-Is + Target-Aligned）
最后更新：2026-02-22

## 1. 目标

提供一份可直接执行的开发启动 runbook，覆盖：

- 标准启动路径
- Omni-Operator 对齐所需的最小环境
- 常见健康检查与排障入口

## 2. 快速启动

### 2.1 后端（推荐）

```powershell
cd E:\Programs\NagaAgent
uv sync
uv run main.py
```

行为说明：

- 启动 `apiserver`（默认 `8000`）
- 启动 `mcpserver`（默认 `8003`）
- 启动 `tts`（默认 `5048`）
- 后台循环尝试启动 `autonomous`（仅当 `config.autonomous.enabled=true`）
- `agentserver` 默认不自动启动

### 2.2 后端（前端调试常用）

```powershell
cd E:\Programs\NagaAgent
python main.py --headless
```

### 2.3 前端开发（主链：Embla_core）

```powershell
cd E:\Programs\NagaAgent\Embla_core
npm install
npm run dev
```

### 2.4 archived Electron 前端（历史兼容）

```powershell
cd E:\Programs\NagaAgent\frontend
npm install
npm run dev
```

## 3. 可选服务独立启动

### 3.1 API 单独启动

```powershell
uvicorn apiserver.api_server:app --host 127.0.0.1 --port 8000 --reload
```

### 3.2 AgentServer（仅兼容场景）

```powershell
uvicorn agentserver.agent_server:app --host 127.0.0.1 --port 8001
```

说明：`/schedule` 与 `/analyze_and_execute` 已是 deprecated 兼容接口。

### 3.3 MCP Server 单独启动

```powershell
uvicorn mcpserver.mcp_server:app --host 0.0.0.0 --port 8003
```

## 4. 端口基线（`system/config.py`）

- API: `8000`
- Agent: `8001`
- MCP: `8003`
- TTS: `5048`
- ASR: `5060`

## 5. 启用 Autonomous（新增）

在 `config.json` 中开启：

```json
{
  "autonomous": {
    "enabled": true,
    "cycle_interval_seconds": 3600,
    "cli_tools": {
      "preferred": "codex",
      "fallback_order": ["claude", "gemini"]
    }
  }
}
```

建议同时确认：

- `autonomous.release.gate_policy_path` 路径存在
- `autonomous.verification_fallback.enable_codex_mcp` 按实际环境配置

## 6. Omni-Operator 开发环境建议

最小建议：

1. Python 依赖：`uv sync`
2. Node 依赖（主链）：`cd Embla_core && npm install`
3. Git 可用（Native/Git 工具依赖）
4. 可选：安装 `mcporter` 与 Codex MCP 以测试降级链路

## 7. 健康检查

```powershell
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8003/status
curl http://127.0.0.1:8001/health
```

说明：

- `8001` 仅在手动启动 AgentServer 时可达。
- `apiserver` 的 `/mcp/status` 是前端兼容占位，不等价于 `mcpserver` 的真实 `/status`。

## 8. 目录索引（开发预备语义）

- `main.py`：服务编排、代理环境、启动入口。
- `apiserver/`：BFF 与工具循环。
- `autonomous/`：System Agent 自治闭环。
- `mcpserver/`：MCP Host 与 Tool Registry。
- `agentserver/`：兼容保留（任务/会话内存查询）。
- `summer_memory/`：记忆与图谱。
- `guide_engine/`：领域问答与计算。
- `voice/`：语音 I/O。
- `Embla_core/`：Next.js 运行态势面板（主链）。
- `frontend/`：Electron + Vue（archived 历史兼容）。
- `system/`：配置、日志与底层安全能力。

## 9. 常见排障清单

1. 端口被占用：检查启动日志中的端口提示。
2. 工具不执行：查看 `agentic_tool_loop` 校验错误与 `tool_stage` 事件。
3. 模型请求失败：按 `04` 文档检查 base_url/proxy/provider/protocol。
4. 自动化未启动：确认 `config.autonomous.enabled=true`。

## 10. 交叉引用

- 总览：`./01-module-overview.md`
- 协议与代理：`./04-api-protocol-proxy-guide.md`
- 工具调用：`./06-structured-tool-calls-and-local-first-native.md`
- 自治 SDLC：`./07-autonomous-agent-sdlc-architecture.md`
