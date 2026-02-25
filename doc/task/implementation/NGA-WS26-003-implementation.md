# NGA-WS26-003 实施记录（fail-open 预算超限自动降级策略）

## 任务信息
- 任务ID: `NGA-WS26-003`
- 标题: fail-open 预算超限自动降级策略
- 状态: 已完成

## 变更范围

1. SystemAgent 预算状态机
- 文件: `autonomous/system_agent.py`
- 变更:
  - 新增 `_subagent_fail_open_budget` 运行时状态：
    - `subagent_attempt_count`
    - `fail_open_count`
    - `fail_open_ratio`
    - `budget_ratio`
    - `degraded_to_legacy`
    - `degrade_reason`
  - 新增 `_record_subagent_attempt()`：每次 SubAgent 执行后累计样本。
  - 新增 `_record_fail_open_and_maybe_degrade(...)`：
    - 记录 fail-open 比率；
    - 比率超出 `fail_open_budget_ratio` 时触发自动降级；
    - 发射审计事件：
      - `SubAgentFailOpenBudgetUpdated`
      - `SubAgentRuntimeAutoDegraded`
      - `ReleaseGateRejected(gate=fail_open_budget)`
    - 同步发出告警事件：
      - `alert_key=subagent_fail_open_budget_exhausted`
      - `topic=alert.runtime`
      - `action=degrade_to_legacy`

2. 运行模式自动降级接入
- 文件: `autonomous/system_agent.py`
- 变更:
  - `_resolve_runtime_mode(task)` 接入降级判定：
    - 当预算已超限且任务非写路径强制任务时，自动返回 `legacy`。
    - `decision_reason=fail_open_budget_exhausted_auto_degrade`。
  - 与 WS26-001 兼容：
    - 写路径强制任务仍保持 `write_path_enforced -> subagent`，不绕过 Scaffold/Txn。

3. 事件可观测增强
- 文件: `autonomous/system_agent.py`
- 变更:
  - `SubAgentRuntimeRolloutDecision` 事件新增预算快照字段：
    - `fail_open_budget_ratio`
    - `fail_open_ratio`
    - `auto_degraded_to_legacy`

4. 回归测试
- 文件: `autonomous/tests/test_system_agent_fail_open_budget_ws26_003.py`（新增）
- 覆盖:
  - fail-open 预算超限后，后续非写任务自动切到 legacy；
  - 触发自动降级事件与告警；
  - 已降级场景下，写任务仍保持 subagent（与 WS26-001 写路径门禁一致）。

## 验证命令

1. 核心回归
- `.\.venv\Scripts\python.exe -m pytest -q autonomous/tests/test_system_agent_fail_open_budget_ws26_003.py autonomous/tests/test_system_agent_write_path_ws26_001.py`

2. 关联回归
- `.\.venv\Scripts\python.exe -m pytest -q autonomous/tests/test_system_agent_subagent_rollout_ws22_006.py autonomous/tests/test_system_agent_lease_guard_ws22_004.py`

3. 全量 SystemAgent 回归集合
- `.\.venv\Scripts\python.exe -m pytest -q autonomous/tests/test_system_agent_config.py autonomous/tests/test_system_agent_cron_alert_ws25_002.py autonomous/tests/test_system_agent_lease_guard_ws22_004.py autonomous/tests/test_system_agent_longrun_baseline_ws22_004.py autonomous/tests/test_system_agent_outbox_bridge_ws23_005.py autonomous/tests/test_system_agent_release_flow.py autonomous/tests/test_system_agent_subagent_bridge_ws22_001.py autonomous/tests/test_system_agent_subagent_rollout_ws22_006.py autonomous/tests/test_system_agent_topic_bus_ws25_001.py autonomous/tests/test_system_agent_watchdog_gate_ws23_002.py autonomous/tests/test_system_agent_write_path_ws26_001.py autonomous/tests/test_system_agent_fail_open_budget_ws26_003.py`

## 结果摘要

- fail-open 预算超限后，系统会自动将非写任务切回 legacy 并发出告警，满足 WS26-003 的“自动降级 + 告警”目标。
- 写路径强制门禁未被破坏，写任务仍不会默认绕过 Scaffold/Txn 提交链。
