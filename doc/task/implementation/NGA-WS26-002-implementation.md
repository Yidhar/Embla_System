# NGA-WS26-002 实施记录（rollout/fail-open/lease 统一指标与导出）

## 任务信息
- 任务ID: `NGA-WS26-002`
- 标题: rollout/fail-open/lease 统一指标与导出
- 状态: 已完成

## 变更范围

1. 统一指标扩展（SLO Snapshot）
- 文件: `scripts/export_slo_snapshot.py`
- 新增指标:
  - `metrics.runtime_rollout`
    - 来源: `SubAgentRuntimeRolloutDecision`
    - 输出: 总决策数、subagent/legacy 分布、命中率、原因分布。
  - `metrics.runtime_fail_open`
    - 来源: `SubAgentRuntimeCompleted` / `SubAgentRuntimeFailOpen` / `SubAgentRuntimeFailOpenBlocked`
    - 输出: fail-open 比率、阻断比率、门失败分布、预算消耗与是否超限。
  - `metrics.runtime_lease`
    - 来源: `LeaseAcquired` / `LeaseLost` 事件 + `workflow.db.orchestrator_lease`
    - 输出: lease 抖动（lost/acquired）、当前 owner/epoch、剩余 TTL 与健康状态。
- 阈值配置扩展:
  - `autonomous.subagent_runtime.rollout_percent`
  - `autonomous.subagent_runtime.fail_open_budget_ratio`
  - `autonomous.lease.lease_name`

2. WS26 专用导出入口
- 文件: `scripts/export_ws26_runtime_snapshot_ws26_002.py`（新增）
- 能力:
  - 复用 `build_snapshot()`；
  - 聚合并导出 WS26 关心的三组指标；
  - 输出标准报告:
    - `task_id = NGA-WS26-002`
    - `scenario = runtime_rollout_fail_open_lease_unified_snapshot`

3. 配置样例补齐
- 文件: `autonomous/config/autonomous_config.yaml`
- 新增 `subagent_runtime` 段默认项:
  - `enforce_scaffold_txn_for_write`
  - `allow_legacy_fail_open_for_write`
  - `fail_open_budget_ratio`
  - 以及 runtime 相关参数完整样例。

4. 回归测试
- 文件:
  - `tests/test_slo_snapshot_export.py`（更新）
  - `tests/test_export_ws26_runtime_snapshot_ws26_002.py`（新增）
- 覆盖点:
  - 统一指标字段存在与关键值计算正确；
  - WS26 专用导出脚本可执行并产出报告。

## 验证命令

1. 指标聚合回归
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_slo_snapshot_export.py tests/test_export_ws26_runtime_snapshot_ws26_002.py`

2. 脚本执行
- `.\.venv\Scripts\python.exe scripts/export_ws26_runtime_snapshot_ws26_002.py --output scratch/reports/ws26_runtime_snapshot_ws26_002.json`

## 结果摘要

- 现有 SLO 快照已具备 rollout/fail-open/lease 的统一观测面，能直接看到灰度命中与 fail-open 预算。
- 新增 WS26 专用导出入口，可作为 M11 门禁前置输入与后续 WS26-003（预算超限自动降级）策略依据。
