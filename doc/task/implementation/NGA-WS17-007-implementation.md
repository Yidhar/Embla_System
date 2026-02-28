> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS17-007 实施记录（Canary 与自动回滚收敛）

## 任务信息
- Task ID: `NGA-WS17-007`
- Title: Canary 与自动回滚收敛
- 状态: 已完成（进入 review）

## 本次范围（仅 WS17-007）
1. Release Controller 决策审计增强
- `autonomous/release/controller.py`
  - `CanaryDecision` 新增：
    - `threshold_snapshot`
    - `stats`
    - `trigger_window_index`
  - `evaluate_canary()` 输出阈值快照与窗口统计
  - 新增 `evaluate_and_execute_rollback()`：
    - 聚合 canary 判定 + 自动回滚执行
    - 返回结构化 `rollback_result`（enabled/attempted/status/details）

2. SystemAgent 回滚事件载荷增强
- `autonomous/system_agent.py`
  - `decision_payload` 注入：
    - `policy_snapshot`
    - `threshold_snapshot`
    - `stats`
    - `trigger_window_index`
  - 使 `ReleaseRolledBack` 事件具备可追踪阈值上下文

3. 演练入口脚本
- `scripts/canary_rollback_drill.py`
  - 支持内置场景：`rollback` / `promote` / `observing`
  - 支持 `--observations-file` 载入自定义观测窗口
  - 支持 `--auto-rollback-enabled` 与 `--rollback-command`
  - 输出结构化 JSON 演练报告（stdout + 可落盘）

4. 测试覆盖
- `autonomous/tests/test_release_controller.py`
  - 阈值快照、触发窗口、自动回滚开关行为
- `autonomous/tests/test_system_agent_release_flow.py`
  - 回滚事件包含 decision 审计字段
- `tests/test_canary_rollback_drill.py`
  - 演练脚本在 auto rollback 开/关下输出正确结果

## 验证命令
- `uv --cache-dir .uv_cache run python -m pytest -q autonomous/tests/test_release_controller.py autonomous/tests/test_system_agent_release_flow.py tests/test_canary_rollback_drill.py`
  - 结果: `7 passed`
- `uv --cache-dir .uv_cache run python -m ruff check autonomous/release/controller.py autonomous/system_agent.py scripts/canary_rollback_drill.py autonomous/tests/test_release_controller.py autonomous/tests/test_system_agent_release_flow.py tests/test_canary_rollback_drill.py`
  - 结果: `All checks passed`

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `autonomous/release/controller.py; autonomous/system_agent.py; scripts/canary_rollback_drill.py; autonomous/tests/test_release_controller.py; autonomous/tests/test_system_agent_release_flow.py; tests/test_canary_rollback_drill.py; doc/task/implementation/NGA-WS17-007-implementation.md`
- `notes`:
  - `canary rollback closure shipped with threshold/policy snapshots, trigger-window stats, drill runner script, and regression tests proving rollback decision plus auto-rollback toggle behavior`

## Date
2026-02-24
