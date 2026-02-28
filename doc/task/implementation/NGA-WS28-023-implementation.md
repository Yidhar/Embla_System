> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS28-023 实施记录（Plugin Worker 隔离真实 MCP agent 联调）

最后更新：2026-02-27  
任务状态：`done`  
优先级：`P0`  
类型：`qa`

## 1. 目标

验证“真实 MCP manifest”可在 `isolated_worker` 路径注册并执行，不只停留在临时测试插件场景。

## 2. 代码改动

1. `scripts/run_ws28_plugin_worker_real_mcp_smoke_ws28_023.py`
- 新增 WS28-023 smoke 脚本：
  - 读取真实 MCP manifest（默认 `mcpserver/agent_weather_time/agent-manifest.json`）。
  - 衍生受信任 plugin manifest（签名 + allowlist + scope）。
  - 走 `scan_and_register_mcp_agents()` 隔离注册路径。
  - 执行一次 `handle_handoff` 并校验不是 plugin worker 运行时失败。
  - 输出标准报告：`scratch/reports/ws28_plugin_worker_real_mcp_smoke_ws28_023.json`。
- 兼容 worker stdout 前缀日志（自动提取 JSON 结果），避免“日志污染导致 parse 失败”。

2. `tests/test_run_ws28_plugin_worker_real_mcp_smoke_ws28_023.py`
- 新增 CLI smoke 回归：
  - 构造最小 fake MCP source manifest + fake agent module。
  - 运行脚本 `main()` 并断言 `passed=true` 与关键 checks。

## 3. 回归命令

```bash
.venv/bin/ruff check \
  scripts/run_ws28_plugin_worker_real_mcp_smoke_ws28_023.py \
  tests/test_run_ws28_plugin_worker_real_mcp_smoke_ws28_023.py

.venv/bin/pytest -q tests/test_run_ws28_plugin_worker_real_mcp_smoke_ws28_023.py

.venv/bin/python scripts/run_ws28_plugin_worker_real_mcp_smoke_ws28_023.py --strict
```

结果：通过。
