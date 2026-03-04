> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS19-004 实施记录（Working Memory 窗口管理器）

## 任务信息
- Task ID: `NGA-WS19-004`
- Title: Working Memory 窗口管理器
- 状态: 已完成（进入 review）

## 本次范围（仅 WS19-004）
1. Working Memory 管理模块
- 新增 `autonomous/working_memory_manager.py`
  - 阈值配置：`MemoryWindowThresholds`
    - `soft_limit_tokens`（软阈值）
    - `hard_limit_tokens`（硬阈值）
    - `keep_recent_messages_soft/hard`（双阶段保留策略）
    - `hard_truncate_chars`（硬阈值截断长度）
  - 回收结果：`MemoryWindowRebalanceResult`
  - 核心类：`WorkingMemoryWindowManager`
    - `estimate_tokens(messages)`：统一 token 估算
    - `rebalance(messages, on_soft_limit, on_hard_limit)`：
      - 软阈值回收：保留 system + 最近消息 + 关键上下文
      - 硬阈值回收：进一步压缩、必要时截断/丢弃非关键历史
      - 支持 soft/hard 两级策略回调（可接入告警或 GC）

2. 关键上下文保护策略
- 引入关键字段标记保留：
  - `trace_id`, `error_code`, `raw_result_ref`, `artifact_ref`,
    `conflict_ticket`, `approval_ticket`, `request_ticket`, `replay_fingerprint`
- 在回收窗口时，关键消息不会被优先删除，降低“排障盲化”风险。

3. 对外导出
- 更新 `autonomous/__init__.py`，导出：
  - `MemoryWindowThresholds`
  - `MemoryWindowRebalanceResult`
  - `WorkingMemoryWindowManager`

## 测试覆盖
- 新增 `tests/test_working_memory_manager_ws19_004.py`
  - 软阈值触发 + 回调触发 + 消息收敛验证
  - 关键上下文（trace_id）保留验证
  - 硬阈值触发后截断/丢弃路径验证

## 验证命令
- `.\.venv\Scripts\python.exe -m ruff check autonomous/working_memory_manager.py tests/test_working_memory_manager_ws19_004.py autonomous/__init__.py`
  - 结果: `All checks passed!`
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_working_memory_manager_ws19_004.py tests/test_llm_gateway_ws19_003.py tests/test_router_engine_ws19_002.py`
  - 结果: `passed`
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_agentserver_deprecation_guard_ws16_002.py tests/test_native_executor_guards.py tests/test_policy_firewall.py tests/test_global_mutex.py tests/test_process_lineage.py tests/test_native_tools_runtime_hardening.py tests/test_agentic_loop_contract_and_mutex.py tests/test_dna_change_audit_ws18_007.py tests/test_immutable_dna_ws18_006.py tests/test_loop_cost_guard_ws18_005.py tests/test_watchdog_daemon_ws18_004.py tests/test_router_engine_ws19_002.py tests/test_event_replay_tool_ws18_003.py tests/test_llm_gateway_ws19_003.py tests/test_working_memory_manager_ws19_004.py`
  - 结果: `87 passed, 0 failed`

## 交付结果与验收对应
- deliverables“双阈值窗口管理与策略回调”：已通过 `rebalance + on_soft_limit/on_hard_limit` 落地。
- acceptance“token 峰值受控且不丢关键上下文”：软硬阈值回收与关键字段保留规则已单测验证。
- rollback“固定窗口策略”：可通过调大阈值并固定 `keep_recent` 退回保守策略。

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `autonomous/working_memory_manager.py; tests/test_working_memory_manager_ws19_004.py; autonomous/__init__.py; doc/task/implementation/NGA-WS19-004-implementation.md`
- `notes`:
  - `working memory manager now enforces soft-hard token thresholds with callback hooks, preserves critical troubleshooting context markers, and trims/truncates noncritical history to control token peaks`

## Date
2026-02-24
