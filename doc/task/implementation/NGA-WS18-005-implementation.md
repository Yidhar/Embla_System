> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS18-005 实施记录（Loop Detector 与成本熔断联动）

## 任务信息
- Task ID: `NGA-WS18-005`
- Title: Loop Detector 与成本熔断联动
- 状态: 已完成（进入 review）

## 本次范围（仅 WS18-005）
1. Loop + Cost Guard 模块
- 新增 `system/loop_cost_guard.py`
  - 阈值配置：`LoopCostThresholds`
    - 连续错误阈值
    - 工具调用频率阈值（窗口内）
    - 单任务成本阈值
    - 日成本阈值
  - 行为输出：`LoopCostAction`
    - `kill_agent_loop`
    - `terminate_task_budget_exceeded`
    - `freeze_noncritical_budget`
  - 主逻辑：`LoopCostGuard.observe_tool_call(...)`
    - 连续失败检测
    - 工具调用风暴检测
    - 任务成本熔断
    - 日成本冻结

2. 与 Watchdog 联动
- 更新 `system/watchdog_daemon.py`
  - 支持注入 `loop_cost_guard`
  - 新增 `observe_tool_call(...)` 桥接入口
  - 触发 loop/cost 动作时发射 `WatchdogLoopCostAction` 事件

3. 测试覆盖
- 新增 `tests/test_loop_cost_guard_ws18_005.py`
  - 连续失败触发 loop 杀断
  - 成功后错误计数重置
  - 工具调用风暴触发 loop 杀断
  - 任务/日成本熔断动作触发
  - Watchdog 桥接 loop guard 事件

## 验证命令
- `python -m ruff check system/loop_cost_guard.py system/watchdog_daemon.py tests/test_loop_cost_guard_ws18_005.py tests/test_watchdog_daemon_ws18_004.py`
  - 结果: `All checks passed`
- `python -m pytest -q tests/test_loop_cost_guard_ws18_005.py tests/test_watchdog_daemon_ws18_004.py tests/test_native_executor_guards.py tests/test_policy_firewall.py tests/test_global_mutex.py tests/test_process_lineage.py tests/test_native_tools_runtime_hardening.py tests/test_agentic_loop_contract_and_mutex.py`
  - 结果: `passed`

## 交付结果与验收对应
- 交付“连续失败检测与任务熔断”：已覆盖连续错误与调用风暴两类 loop 模式。
- 交付“成本熔断联动”：已覆盖单任务成本终止与日预算冻结。
- 验收“死循环场景被自动中断”：由 `kill_agent_loop` 路径测试验证。
- 回退策略“手动仲裁兜底”：阈值可上调到极高值，等效禁用自动熔断。

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `system/loop_cost_guard.py; system/watchdog_daemon.py; tests/test_loop_cost_guard_ws18_005.py; doc/task/implementation/NGA-WS18-005-implementation.md`
- `notes`:
  - `loop-cost guard now detects consecutive failures and call storms, enforces per-task/daily cost breakers, and bridges watchdog actions through a unified WatchdogLoopCostAction event`

## Date
2026-02-24
