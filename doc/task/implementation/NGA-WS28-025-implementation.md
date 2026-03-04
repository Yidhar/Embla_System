> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS28-025 实施记录（Watchdog Daemon 常驻化）

最后更新：2026-02-27  
任务状态：`done`  
优先级：`P1`  
类型：`feature`

## 1. 目标

将 watchdog 从“任务执行时 `run_once` 临时采样”升级为“独立常驻采样循环 + 状态文件 + 聚合可观测”。

## 2. 代码改动

1. `system/watchdog_daemon.py`
- 新增常驻循环能力：`run_daemon(...)`，支持周期采样与状态文件落盘。
- 新增状态读取解析：`read_daemon_state(...)`，统一处理 missing/invalid/stale/threshold 信号。
- 新增最近观测缓存：`get_last_observation()`，与 `run_once()` 同源。

2. `scripts/run_watchdog_daemon_ws28_025.py`
- 新增 WS28-025 入口脚本，支持：
  - `--mode run`：执行 daemon loop（可控 tick）
  - `--mode status`：读取 daemon 状态并输出标准报告
- 默认状态文件：`scratch/runtime/watchdog_daemon_state_ws28_025.json`
- 默认报告：`scratch/reports/watchdog_daemon_ws28_025.json`

3. `autonomous/system_agent.py`
- `watchdog` 配置新增 daemon 状态字段：
  - `prefer_daemon_state`
  - `daemon_state_file`
  - `daemon_state_stale_warning_seconds`
  - `daemon_state_stale_critical_seconds`
  - `fail_closed_on_daemon_state_stale`
- `_evaluate_watchdog_gate(...)` 优先消费 daemon 状态文件（事件：`WatchdogDaemonStateConsumed`），缺失/陈旧时可回退 `run_once()`。

4. `apiserver/api_server.py`
- `/v1/ops/runtime/posture` 接入 watchdog daemon 聚合：
  - `data.summary.watchdog_daemon_status`
  - `data.metrics.watchdog_daemon`
  - `data.watchdog_daemon`
- `/v1/ops/incidents/latest` 接入 watchdog daemon incident：
  - `WatchdogDaemonStateStale`
  - `WatchdogDaemonThresholdExceeded`
  - `WatchdogDaemonIssue`

5. `autonomous/config/autonomous_config.yaml`
- 增补 watchdog daemon 默认配置字段。

6. `scripts/manage_brainstem_control_plane_ws28_017.py` + `scripts/release_closure_chain_full_m0_m12.py`
- 将 watchdog daemon 挂入 WS28-017 标准托管链：
  - `start` 自动拉起 `scripts/run_watchdog_daemon_ws28_025.py` 常驻循环；
  - `status` 合并 brainstem + watchdog 双通道健康检查；
  - `stop` 统一回收 brainstem/watchdog 相关 PID。
- M12-T0 收口步骤新增 watchdog 托管检查项（`watchdog_gate`、`watchdog_state_file_consistent` 等），使其成为全链标准验收信号。

## 3. 测试改动

1. `tests/test_watchdog_daemon_ws18_004.py`
- 新增 daemon loop 状态文件写入测试。
- 新增 stale 状态识别测试。

2. `tests/test_run_watchdog_daemon_ws28_025.py`
- 新增脚本 `run/status` CLI smoke。

3. `tests/test_system_agent_watchdog_gate_ws23_002.py`
- 新增 daemon 状态消费路径测试（验证阻断不依赖 `run_once`）。

4. `tests/test_system_agent_config.py`
- 新增 watchdog daemon 配置字段的默认值与覆盖值断言。

5. `tests/test_ops_dashboard_extensions.py`
- 新增 runtime posture watchdog 字段断言。
- 新增 incidents latest watchdog stale 事件断言。

6. `tests/test_manage_brainstem_control_plane_ws28_017.py` + `tests/test_release_closure_chain_full_m0_m12.py`
- 新增/更新 WS28-017 托管链 watchdog 生命周期断言（start/status/stop）。
- 新增/更新 M12-T0 全链检查项断言（watchdog 托管联动）。

## 4. 回归命令

```bash
.venv/bin/ruff check \
  system/watchdog_daemon.py \
  scripts/run_watchdog_daemon_ws28_025.py \
  autonomous/system_agent.py \
  tests/test_system_agent_watchdog_gate_ws23_002.py \
  tests/test_system_agent_config.py \
  tests/test_watchdog_daemon_ws18_004.py \
  tests/test_run_watchdog_daemon_ws28_025.py \
  tests/test_ops_dashboard_extensions.py

.venv/bin/pytest -q \
  tests/test_watchdog_daemon_ws18_004.py \
  tests/test_run_watchdog_daemon_ws28_025.py \
  tests/test_system_agent_watchdog_gate_ws23_002.py \
  tests/test_system_agent_config.py \
  tests/test_ops_dashboard_extensions.py

.venv/bin/python scripts/run_watchdog_daemon_ws28_025.py --mode run --interval-seconds 0 --max-ticks 1 --strict

.venv/bin/pytest -q \
  tests/test_manage_brainstem_control_plane_ws28_017.py \
  tests/test_release_closure_chain_full_m0_m12.py
```

结果：通过。
