# NGA-WS18-004 实施记录（Watchdog 资源监控器落地）

## 任务信息
- Task ID: `NGA-WS18-004`
- Title: Watchdog 资源监控器落地
- 状态: 已完成（进入 review）

## 本次范围（仅 WS18-004）
1. Watchdog 守护模块
- 新增 `system/watchdog_daemon.py`
  - 阈值模型：`WatchdogThresholds`
    - CPU / RAM / Disk / IO(read/write bps) / cost_per_hour
  - 采样模型：`WatchdogSnapshot`
  - 动作模型：`WatchdogAction`
  - 主逻辑：`WatchdogDaemon.run_once()`
    - 采样资源
    - 阈值评估
    - 告警/干预动作输出
    - 事件发射（可接 Event Bus emitter）

2. 动作策略
- `warn_only=True`：
  - 超阈值仅告警 `alert_only`
- `warn_only=False`：
  - `critical`：`pause_dispatch_and_escalate`
  - `warn`：`throttle_new_workloads`

3. 资源采集能力
- 默认 provider 使用 `psutil` 采集：
  - `cpu_percent`
  - `virtual_memory().percent`
  - `disk_usage('/').percent`
  - `disk_io_counters()` 差分计算 IO bps
  - 轻量成本估算 `cost_per_hour`

4. 测试覆盖
- 新增 `tests/test_watchdog_daemon_ws18_004.py`
  - 低负载无触发
  - warn_only 告警触发
  - 非 warn_only 的 critical 干预触发
  - 非 warn_only 的 warn 级节流触发

## 验证命令
- `python -m ruff check system/watchdog_daemon.py tests/test_watchdog_daemon_ws18_004.py`
  - 结果: `All checks passed`
- `python -m pytest -q tests/test_watchdog_daemon_ws18_004.py tests/test_native_executor_guards.py tests/test_policy_firewall.py tests/test_global_mutex.py tests/test_process_lineage.py tests/test_native_tools_runtime_hardening.py tests/test_agentic_loop_contract_and_mutex.py`
  - 结果: `passed`

## 交付结果与验收对应
- 交付“CPU/RAM/IO/成本采集与阈值配置”：已提供阈值模型 + 默认采样实现。
- 验收“超阈值告警与干预动作可触发”：已通过单测覆盖告警与干预两条路径。
- 回退策略“降级为仅告警”：`warn_only=True` 即可回退。

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `system/watchdog_daemon.py; tests/test_watchdog_daemon_ws18_004.py; doc/task/implementation/NGA-WS18-004-implementation.md`
- `notes`:
  - `watchdog daemon now samples cpu/memory/disk/io/cost with configurable thresholds and emits alert/throttle/pause escalation actions, with focused threshold-action regression coverage`

## Date
2026-02-24
