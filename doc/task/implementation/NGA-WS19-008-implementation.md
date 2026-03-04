> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS19-008 实施记录（Router 仲裁熔断联动）


> Migration Note (archived/legacy)
> 文中 `autonomous/*` 路径属于历史实现标识；当前实现请优先使用 `agents/*`、`core/*` 与 `config/autonomous_runtime.yaml`。

## 任务信息
- Task ID: `NGA-WS19-008`
- Title: Router 仲裁熔断联动
- 状态: 已完成（进入 review）

## 本次范围（仅 WS19-008）
1. Router 仲裁守卫模块
- 新增 `agents/router_arbiter_guard.py`
  - 决策模型：`RouterArbiterDecision`
  - 核心守卫：`RouterArbiterGuard`
    - `register_delegate_turn(...)`：
      - 按 `task_id + conflict_ticket` 统计 delegate turns
      - 达到上限触发 `freeze=true + hitl=true`
    - `observe_workspace_conflict(...)`：
      - 对接 `system.router_arbiter.evaluate_workspace_conflict_retry`
      - 复用 WS12-005 的冲突识别语义
    - `should_freeze_task(task_id)`：快速判断任务是否冻结
    - `build_conflict_summary(task_id)`：输出冲突点与候选决策摘要
    - `reset_task(task_id)`：HITL 处置后解冻任务

2. 仲裁联动语义
- 固定 `max_delegate_turns=3`（可配置）
- 超限触发：
  - `escalated=true`
  - `freeze=true`
  - `hitl=true`
  - `reason=router_delegate_threshold_exceeded`
- 冲突 ticket 变更时，委派计数重置，避免跨问题误熔断。

3. 对外导出
- 更新 `autonomous/__init__.py`（archived/legacy）：
  - `RouterArbiterGuard`
  - `RouterArbiterDecision`

## 测试覆盖
- 新增 `tests/test_chat_route_quality_guard_ws28_012.py`
  - 委派次数达到阈值后冻结/HITL 升级
  - 冲突 ticket 变化时计数重置
  - workspace_txn 冲突信号接入并触发升级
  - 冲突摘要构建与 reset 解冻

## 验证命令
- `.\.venv\Scripts\python.exe -m ruff check agents/router_arbiter_guard.py tests/test_chat_route_quality_guard_ws28_012.py autonomous/__init__.py`（archived/legacy path in command）
  - 结果: `All checks passed!`
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_chat_route_quality_guard_ws28_012.py tests/test_router_engine_prompt_profile_ws28_001.py tests/test_agentic_loop_contract_and_mutex.py`
  - 结果: `passed`
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_agentserver_deprecation_guard_ws16_002.py tests/test_native_executor_guards.py tests/test_policy_firewall.py tests/test_global_mutex.py tests/test_process_lineage.py tests/test_native_tools_runtime_hardening.py tests/test_agentic_loop_contract_and_mutex.py tests/test_dna_change_audit_ws18_007.py tests/test_immutable_dna_ws18_006.py tests/test_loop_cost_guard_ws18_005.py tests/test_watchdog_daemon_ws18_004.py tests/test_embla_core_release_compat_gate.py tests/test_embla_core_release_compat_gate.py tests/test_llm_stream_json_protocol_ws28_035.py tests/test_mcp_status_snapshot.py tests/test_router_engine_prompt_profile_ws28_001.py tests/test_core_event_bus_consumers_ws28_029.py tests/test_llm_gateway_prompt_slice_ws28_002.py tests/test_memory_agents.py tests/test_chat_route_quality_guard_ws28_012.py`
  - 结果: `104 passed, 0 failed`

## 交付结果与验收对应
- deliverables“delegate 上限、冲突冻结、HITL 接管”：已通过 `RouterArbiterGuard` 完整落地。
- acceptance“超限冲突不进入无限修复循环”：阈值熔断与冻结判定路径已自动化测试覆盖。
- rollback“人工仲裁强制接管”：`reset_task` 允许 HITL 后手动解冻恢复。

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `agents/router_arbiter_guard.py; tests/test_chat_route_quality_guard_ws28_012.py; autonomous/__init__.py [archived/legacy]; doc/task/implementation/NGA-WS19-008-implementation.md`
- `notes`:
  - `router arbiter guard now enforces max delegate turns, freezes escalated conflict loops, integrates workspace conflict signals, and exposes conflict summary plus hitl reset hooks`

## Date
2026-02-24
