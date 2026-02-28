> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS28-022~025 可执行任务单（#4/#6/#7/#9）

最后更新：2026-02-27  
状态：`active`  
范围：将待办 `#4/#6/#7/#9` 拆分为可直接执行/回归/验收的任务卡，并按优先级推进。

## 1. 优先级顺序

1. `NGA-WS28-022`（对应 #7）：Immutable DNA 运行时注入（P0）
2. `NGA-WS28-023`（对应 #9）：Plugin Worker 隔离真实 MCP agent 联调（P0）
3. `NGA-WS28-024`（对应 #4）：Brainstem Supervisor 接入主启动链（P1）
4. `NGA-WS28-025`（对应 #6）：Watchdog Daemon 常驻化（P1）

---

## 2. NGA-WS28-022（#7）Immutable DNA 运行时注入

- priority: `P0`
- type: `hardening`
- status: `done`（2026-02-27）
- depends_on: `NGA-WS23-003`
- implementation: `doc/task/implementation/NGA-WS28-022-implementation.md`

### 2.1 代码点

1. `apiserver/llm_service.py`
- 在 LLM 调用前统一执行 immutable DNA 运行时注入（非流式 + 流式）。
- 新增环境开关与路径配置：
  - `NAGA_IMMUTABLE_DNA_RUNTIME_INJECTION`
  - `NAGA_IMMUTABLE_DNA_PROMPTS_ROOT`
  - `NAGA_IMMUTABLE_DNA_MANIFEST_PATH`
  - `NAGA_IMMUTABLE_DNA_AUDIT_PATH`
- 注入失败时 fail-closed（阻断 chat 调用并返回错误说明）。

### 2.2 测试点

1. `tests/test_llm_service_immutable_dna_runtime_injection.py`
- 注入成功场景：验证请求首条 system message 包含 DNA header/hash。
- manifest 篡改场景：验证请求被阻断且不触发下游 `acompletion()`。

### 2.3 验收命令

```bash
.venv/bin/ruff check \
  apiserver/llm_service.py \
  tests/test_llm_service_immutable_dna_runtime_injection.py

.venv/bin/pytest -q tests/test_llm_service_immutable_dna_runtime_injection.py
```

---

## 3. NGA-WS28-023（#9）Plugin Worker 隔离真实 MCP agent 联调

- priority: `P0`
- type: `qa`
- status: `done`（2026-02-27）
- depends_on: `NGA-WS24-006`
- implementation: `doc/task/implementation/NGA-WS28-023-implementation.md`

### 3.1 代码点

1. `scripts/run_ws28_plugin_worker_real_mcp_smoke_ws28_023.py`
- 使用仓库内真实 MCP manifest 衍生出受信任 plugin manifest（签名 + allowlist + scopes）。
- 强制走 `isolated_worker` 注册路径并执行一次 `handle_handoff`。
- 产出标准报告到 `scratch/reports/`，可用于收口链引用。

2. `tests/test_run_ws28_plugin_worker_real_mcp_smoke_ws28_023.py`
- 覆盖 CLI main 成功路径，校验报告落盘与关键 checks。

### 3.2 验收命令

```bash
.venv/bin/ruff check \
  scripts/run_ws28_plugin_worker_real_mcp_smoke_ws28_023.py \
  tests/test_run_ws28_plugin_worker_real_mcp_smoke_ws28_023.py

.venv/bin/pytest -q tests/test_run_ws28_plugin_worker_real_mcp_smoke_ws28_023.py

.venv/bin/python scripts/run_ws28_plugin_worker_real_mcp_smoke_ws28_023.py --strict
```

---

## 4. NGA-WS28-024（#4）Brainstem Supervisor 接入主启动链

- priority: `P1`
- type: `refactor`
- status: `done`（2026-02-27）
- depends_on: `NGA-WS28-020`
- implementation: `doc/task/implementation/NGA-WS28-024-implementation.md`

### 4.1 代码点

1. `main.py`
- 引入统一“脑干托管启动器”作为主启动链的一部分，减少裸线程 + 手写 `uvicorn.run` 分叉路径。
- 避免与 `apiserver/api_server.py` lifespan 中的托管逻辑重复启动。

2. `apiserver/api_server.py`
- 增加幂等保护字段，确保“主链已托管时”lifespan 只做状态确认不重复拉起。

### 4.2 测试点

1. `tests/test_api_server_brainstem_bootstrap_ws28_018.py`
- 增加“主启动链已托管”分支断言（无重复 spawn）。

2. `tests/test_manage_brainstem_control_plane_ws28_017.py`
- 保持 manager 脚本接口兼容，确保 runbook 入口不回归。

### 4.3 验收命令

```bash
.venv/bin/ruff check \
  main.py \
  apiserver/api_server.py \
  tests/test_api_server_brainstem_bootstrap_ws28_018.py \
  tests/test_manage_brainstem_control_plane_ws28_017.py

.venv/bin/pytest -q \
  tests/test_api_server_brainstem_bootstrap_ws28_018.py \
  tests/test_manage_brainstem_control_plane_ws28_017.py
```

---

## 5. NGA-WS28-025（#6）Watchdog Daemon 常驻化

- priority: `P1`
- type: `feature`
- status: `done`（2026-02-27）
- depends_on: `NGA-WS28-024`
- implementation: `doc/task/implementation/NGA-WS28-025-implementation.md`

### 5.1 代码点

1. `system/watchdog_daemon.py`
- 在现有 `run_once()` 之上增加 daemon loop（可配置 interval、max_ticks、stop 条件）。
- 输出心跳/状态快照，供 runtime posture 聚合消费。

2. `scripts/run_watchdog_daemon_ws28_025.py`（新增）
- 提供 `start/status/stop` 或 `run` CLI 入口，用于长期托管与演练。

3. `autonomous/system_agent.py`
- 从“任务内即时采样”过渡到“消费常驻 watchdog 状态”的门禁判定路径。

### 5.2 测试点

1. `tests/test_watchdog_daemon_ws18_004.py`
- 新增 daemon loop 运行、停止、快照产出、stale 判定覆盖。

2. `autonomous/tests/test_system_agent_watchdog_gate_ws23_002.py`
- 增加“读取常驻 watchdog 状态”分支断言。

3. `tests/test_run_watchdog_daemon_ws28_025.py`（新增）
- 覆盖脚本 CLI smoke。

### 5.3 验收命令

```bash
.venv/bin/ruff check \
  system/watchdog_daemon.py \
  scripts/run_watchdog_daemon_ws28_025.py \
  tests/test_watchdog_daemon_ws18_004.py \
  autonomous/tests/test_system_agent_watchdog_gate_ws23_002.py \
  tests/test_run_watchdog_daemon_ws28_025.py

.venv/bin/pytest -q \
  tests/test_watchdog_daemon_ws18_004.py \
  autonomous/tests/test_system_agent_watchdog_gate_ws23_002.py \
  tests/test_run_watchdog_daemon_ws28_025.py
```
