# M11 Runtime Guard & Metrics Onepager（WS26-001 / WS26-002）

## 适用范围
- 里程碑: `M11`
- 任务:
  - `NGA-WS26-001`（写路径强制收敛）
  - `NGA-WS26-002`（统一指标导出）

## 一键最小回归

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_native_tools_runtime_hardening.py `
  tests/test_main_brainstem_bootstrap_ws28_024.py `
  tests/test_slo_snapshot_export.py `
  tests/test_export_ws26_runtime_snapshot_ws26_002.py
```

## 导出统一指标报告

```powershell
.\.venv\Scripts\python.exe scripts/export_ws26_runtime_snapshot_ws26_002.py `
  --output scratch/reports/ws26_runtime_snapshot_ws26_002.json
```

## 检查要点

1. 写路径门禁
- 观察 `ReleaseGateRejected` 中 `gate=write_path` 是否可追踪到具体 `decision_reason`。
- 观察 `SubAgentRuntimeFailOpenBlocked`（archived_legacy 历史事件命名空间）是否在默认策略下触发（write 任务 fail-open 阻断）。

2. rollout 灰度命中
- `metrics.runtime_rollout.value`：subagent 命中率。
- `metrics.runtime_rollout.decision_reasons`：灰度决策原因分布。

3. fail-open 预算
- `metrics.runtime_fail_open.value`：实际 fail-open 比率。
- `metrics.runtime_fail_open.configured_budget_ratio`：配置预算。
- `metrics.runtime_fail_open.budget_exhausted`：是否超限。

4. lease 稳态
- `metrics.runtime_lease.lease_acquired_count` / `lease_lost_count`。
- `metrics.runtime_lease.state` 与 `seconds_to_expiry`（`value`）。

## 常见异常与处理

1. `gate=write_path` 大量拒绝
- 检查 `autonomous.subagent_runtime.enabled` 是否被误关。
- 检查任务是否被错误标记为 write（`metadata.write_intent` / `target_files` / `subtasks.patches`）。

2. fail-open 预算持续超限
- 暂时降低 rollout 或收紧输入任务，优先修复 `gate_failure` 高发项（contract/scaffold/runtime）。
- 进入 `WS26-003` 自动降级策略实施前，手工将 `rollout_percent` 下调并记录审计。

3. lease 抖动高
- 优先排查 `orchestrator_lease` 写入抖动与部署实例数量。
- 结合 `LeaseLost` 事件时间窗口确认是否存在并发抢占或租约刷新延迟。
