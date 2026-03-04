> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS18-002 实施记录（Outbox/Inbox 可靠投递整合）

## 任务信息
- Task ID: `NGA-WS18-002`
- Title: Outbox/Inbox 可靠投递整合
- 状态: 已完成（进入 review）

## 本次范围（仅 WS18-002）
1. Outbox 失败补偿状态机
- `agents/runtime/schema.sql`
  - `outbox_event` 新增字段：
    - `dispatch_attempts`
    - `max_attempts`
    - `last_error`
    - `next_retry_at`
- `agents/runtime/workflow_store.py`
  - `_init_schema` 增加 outbox 列补齐逻辑（兼容老库自动 `ALTER TABLE`）。
  - `enqueue_outbox(...)` 支持 `max_attempts` 并写入统一初始状态。
  - `read_pending_outbox(...)` 只返回可重试窗口内事件：
    - `status='pending'`
    - `dispatch_attempts < max_attempts`
    - `next_retry_at` 到期或为空
  - 新增 `record_outbox_attempt_failure(...)`：
    - 指数退避重试（backoff）
    - 超限自动进入 `dead_letter`

2. SystemAgent 投递链路接线
- `agents/pipeline.py`
  - `_dispatch_single_outbox_event(...)` 新增三种路径：
    - Inbox 命中去重：`OutboxDedupHit`
    - 失败可重试：`OutboxDispatchRetryScheduled`
    - 重试耗尽：`OutboxDispatchDeadLetter`
  - 成功投递继续走 `complete_outbox_for_consumer(...)`，保持 inbox 去重语义。

3. 故障注入与回归验证
- `tests/test_slo_snapshot_export.py`
  - 新增 outbox 失败重试与 dead-letter 测试。
- `tests/test_canary_rollback_drill.py`
  - 新增 outbox 业务处理异常下的重试调度测试。
  - 新增重试耗尽进入 dead-letter 测试。

## 验证命令
- `python -m ruff check agents/runtime/workflow_store.py agents/pipeline.py tests/test_slo_snapshot_export.py tests/test_canary_rollback_drill.py`
  - 结果: `All checks passed`
- `python -m pytest -q tests/test_slo_snapshot_export.py tests/test_canary_rollback_drill.py tests/test_core_event_bus_consumers_ws28_029.py`
  - 结果: `12 passed`
- `python -m pytest -q tests/test_agentserver_deprecation_guard_ws16_002.py tests/test_native_executor_guards.py tests/test_policy_firewall.py tests/test_global_mutex.py tests/test_process_lineage.py tests/test_native_tools_runtime_hardening.py tests/test_agentic_loop_contract_and_mutex.py`
  - 结果: `58 passed`（含警告，无失败）

## 交付结果与验收对应
- 幂等投递：`inbox_dedup + complete_outbox_for_consumer` 继续保证消费幂等。
- 重试补偿：`record_outbox_attempt_failure` 提供重试窗口与退避。
- 去重逻辑：重复消费命中 `OutboxDedupHit`，并对 outbox 做幂等收敛。
- 故障注入：异常路径已覆盖“可重试”与“重试耗尽”两类行为。

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `agents/runtime/schema.sql; agents/runtime/workflow_store.py; agents/pipeline.py; tests/test_slo_snapshot_export.py; tests/test_canary_rollback_drill.py; doc/task/implementation/NGA-WS18-002-implementation.md`
- `notes`:
  - `outbox delivery now tracks attempts/backoff/dead-letter state, system_agent emits retry/dead-letter/dedup events, and fault-injection tests verify no-loss/no-dup compensation semantics`

## Date
2026-02-24
