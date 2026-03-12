# WS18-007 Runbook: DNA 变更审批与追踪

## 1. 目标
- 规范 DNA 变更申请、审批、拒绝、落地流程。
- 确保每次变更都能追溯到责任人与工单票据。
- 输出可审计追踪报表用于值班与复盘。

## 2. 模块入口
- 核心模块：`system/dna_change_audit.py`
- 核心类：`DNAChangeAuditLedger`

## 3. 台账文件与报表文件
- 审计台账（append-only）：`logs/autonomous/dna_change_audit.jsonl`
- 追踪报表（聚合快照）：`logs/autonomous/dna_change_tracking_report.json`

## 4. 操作流程（标准）
1. 创建变更申请（必须包含责任人 + 工单号）
2. 安全/运维审批（或拒绝）
3. 执行落地并记录执行责任人
4. 导出追踪报表并回填值班工单

## 5. 快速示例
```python
from pathlib import Path
from system.dna_change_audit import DNAChangeAuditLedger

ledger = DNAChangeAuditLedger(
    ledger_file=Path("logs/autonomous/dna_change_audit.jsonl")
)

change_id = ledger.request_change(
    file_path="system/prompts/core/dna/conversation_style_prompt.md",
    old_hash="sha256_old",
    new_hash="sha256_new",
    requested_by="agent-security",
    request_ticket="CHG-2026-0201",
    notes="refine global conversation composition DNA",
)

ledger.approve_change(
    change_id=change_id,
    approved_by="ops-lead",
    approval_ticket="CAB-2026-1001",
    notes="CAB approved",
)

ledger.mark_applied(
    change_id=change_id,
    applied_by="release-bot",
    notes="deployed in maintenance window",
)

ledger.write_tracking_report(
    output_file=Path("logs/autonomous/dna_change_tracking_report.json")
)
```

## 6. 拒绝流程示例
```python
ledger.reject_change(
    change_id=change_id,
    rejected_by="security-reviewer",
    rejection_ticket="SEC-REJECT-2026-09",
    notes="missing blast radius assessment",
)
```

## 7. 验收点（值班检查）
1. 每条变更至少包含：
   - `requested_by`, `request_ticket`
2. 审批通过记录包含：
   - `approved_by`, `approval_ticket`
3. 拒绝记录包含：
   - `rejected_by`, `rejection_ticket`
4. 落地记录包含：
   - `applied_by`
5. 报表中 `by_status` 与台账记录一致。

## 8. 异常处理
1. 报错 `request_ticket is required`
- 变更单未绑定工单号，禁止提交。

2. 报错 `change_id ... is not pending and cannot be approved/rejected`
- 该变更已离开待审批态（可能已审批、已拒绝或已落地）。

3. 报错 `change_id ... is not approved and cannot be applied`
- 需先走审批通过，再执行落地。

## 9. 回退策略（冻结 DNA 写入窗口）
出现审批链路异常或疑似篡改时：
1. 暂停所有自动 DNA 写入动作（进入人工审批模式）。
2. 仅允许从最后已审计版本恢复。
3. 补齐工单与审批票据后再恢复自动流程。

## 10. 最后更新
- 2026-02-24
