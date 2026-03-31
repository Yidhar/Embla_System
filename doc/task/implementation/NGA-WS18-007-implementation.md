> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS18-007 实施记录（DNA 变更审计与审批流程）

## 任务信息
- Task ID: `NGA-WS18-007`
- Title: DNA 变更审计与审批流程
- 状态: 已完成（进入 review）

## 本次范围（仅 WS18-007）
1. DNA 变更审计台账模块
- 新增并完善 `system/dna_change_audit.py`
  - 审计模型：`DNAChangeSummary`
  - 台账核心：`DNAChangeAuditLedger`
  - 核心能力：
    - `request_change(...)`：创建变更申请（强制 `requested_by` + `request_ticket`）
    - `approve_change(...)`：审批通过（强制 `approved_by` + `approval_ticket`）
    - `reject_change(...)`：审批拒绝（强制 `rejected_by` + `rejection_ticket`）
    - `mark_applied(...)`：标记已落地（仅允许 `approved` 后执行）
    - `build_tracking_report()`：聚合生成追踪报表
    - `write_tracking_report(...)`：报表 JSON 落盘

2. 状态机约束与可追溯性增强
- 增加状态机校验，防止非法流程：
  - 未申请不可审批/拒绝/落地
  - 未审批不可落地
  - 非 `pending` 状态不可重复审批/拒绝
- 报表字段补齐责任链：
  - 申请责任人 + 工单：`requested_by`, `request_ticket`
  - 审批责任人 + 票据：`approved_by`, `approval_ticket`
  - 拒绝责任人 + 票据：`rejected_by`, `rejection_ticket`
  - 落地责任人：`applied_by`

3. 测试覆盖
- 新增 `tests/test_dna_change_audit_ws18_007.py`
  - 审批通过全链路：`request -> approve -> applied -> report/export`
  - 拒绝链路：`request -> reject -> report`
  - 非法状态/缺失票据校验：
    - 缺失 `request_ticket` / `approval_ticket`
    - 未审批直接 `mark_applied`
    - 已落地后重复审批
    - 不存在变更单直接拒绝

4. 运维交接文档
- 新增 `doc/task/runbooks/dna_change_approval_ws18_007.md`
  - 申请、审批、拒绝、追踪报表导出、回退冻结窗口操作步骤。

## 验证命令
- `.\.venv\Scripts\python.exe -m ruff check system/dna_change_audit.py tests/test_dna_change_audit_ws18_007.py`
  - 结果: `All checks passed!`
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_dna_change_audit_ws18_007.py`
  - 结果: `passed`
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_agentserver_deprecation_guard_ws16_002.py tests/test_native_executor_guards.py tests/test_policy_firewall.py tests/test_global_mutex.py tests/test_process_lineage.py tests/test_native_tools_runtime_hardening.py tests/test_agentic_loop_contract_and_mutex.py tests/test_dna_change_audit_ws18_007.py tests/test_immutable_dna_ws18_006.py tests/test_loop_cost_guard_ws18_005.py tests/test_watchdog_daemon_ws18_004.py tests/test_router_engine_prompt_profile_ws28_001.py tests/test_core_event_bus_consumers_ws28_029.py`
  - 结果: `80 passed, 0 failed`（含依赖链路回归）

## 交付结果与验收对应
- deliverables“变更审批记录与追踪报表”：已通过 JSONL 台账 + 聚合报表落盘能力实现。
- acceptance“DNA 变更可追溯到责任人和工单”：报表已覆盖 `requested_by/request_ticket/approved_by/approval_ticket/rejected_by/rejection_ticket/applied_by`。
- rollback“冻结 DNA 写入窗口”：runbook 中提供冻结窗口策略，变更可转人工审批通道。

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `system/dna_change_audit.py; tests/test_dna_change_audit_ws18_007.py; doc/task/runbooks/dna_change_approval_ws18_007.md; doc/task/implementation/NGA-WS18-007-implementation.md`
- `notes`:
  - `dna change audit ledger now enforces request/approve/apply state transitions, persists owner+tickets for full traceability, and exports tracking reports for ops review`

## Date
2026-02-24
