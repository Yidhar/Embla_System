# 07 执行启动手册（按 5 条指令落地）

生效时间：2026-02-23  
适用范围：`M0-M5` 基线启动手册（76 任务）；统一执行板当前总量见 `doc/task/09-execution-board.csv`（`M0-M12`）。

## 0. 执行决议

1. 立即启动 P0 止血路径（W1-W5，23 任务）。
2. 按 Sprint 波次推进（S1-S7，依赖层级驱动）。
3. 按 lane 并行执行（同层按 WS lane 分配）。
4. 严格执行里程碑门禁（M0-M5 出场条件）。
5. 风险闭环验证（Critical/High 全量绑定验证任务）。

## 1. 立即启动 P0（W1-W5）

| 波次 | 层级 | 任务数 | 任务清单 | 开工条件 | 完成判定 |
|---|---|---:|---|---|---|
| W1 | L0 | 3 | NGA-WS10-001<br/>NGA-WS16-001<br/>NGA-WS17-001 | 立即开工 | 本波次任务全部 `review/done` + 回滚演练记录齐全 |
| W2 | L1 | 6 | NGA-WS10-002<br/>NGA-WS10-003<br/>NGA-WS11-001<br/>NGA-WS12-001<br/>NGA-WS13-001<br/>NGA-WS17-002 | 前一波次 Gate 通过 | 本波次任务全部 `review/done` + 回滚演练记录齐全 |
| W3 | L2 | 7 | NGA-WS11-002<br/>NGA-WS11-004<br/>NGA-WS12-002<br/>NGA-WS13-002<br/>NGA-WS14-001<br/>NGA-WS14-003<br/>NGA-WS14-007 | 前一波次 Gate 通过 | 本波次任务全部 `review/done` + 回滚演练记录齐全 |
| W4 | L3 | 5 | NGA-WS11-003<br/>NGA-WS13-003<br/>NGA-WS14-002<br/>NGA-WS14-005<br/>NGA-WS14-009 | 前一波次 Gate 通过 | 本波次任务全部 `review/done` + 回滚演练记录齐全 |
| W5 | L4 | 2 | NGA-WS13-004<br/>NGA-WS14-006 | 前一波次 Gate 通过 | 本波次任务全部 `review/done` + 回滚演练记录齐全 |

当前启动状态：W1 三任务已置为 `in_progress`（见 `doc/task/09-execution-board.csv`）。

## 2. Sprint 波次推进（S1-S7）

| Sprint | 依赖层 | 任务数 | 推进规则 |
|---|---|---:|---|
| S1 | L0 | 3 | 根层，直接并行开工 |
| S2 | L1 | 12 | 仅在上一层 Sprint Gate 通过后开工 |
| S3 | L2 | 20 | 仅在上一层 Sprint Gate 通过后开工 |
| S4 | L3 | 19 | 仅在上一层 Sprint Gate 通过后开工 |
| S5 | L4 | 9 | 仅在上一层 Sprint Gate 通过后开工 |
| S6 | L5 | 10 | 仅在上一层 Sprint Gate 通过后开工 |
| S7 | L6 | 3 | 仅在上一层 Sprint Gate 通过后开工 |

## 3. Lane 并行执行策略

| Lane | Pool | 并发建议 | WIP 规则 |
|---|---|---:|---|
| Lane-WS10 (WS10) | POOL-01 Contract-Gateway | 2-3 | 同一 task_id 仅允许 1 个 Agent owner；跨池任务必须挂协同票据 |
| Lane-WS11 (WS11) | POOL-02 Artifact-Evidence | 2-3 | 同一 task_id 仅允许 1 个 Agent owner；跨池任务必须挂协同票据 |
| Lane-WS12 (WS12) | POOL-03 AST-Concurrency | 2-3 | 同一 task_id 仅允许 1 个 Agent owner；跨池任务必须挂协同票据 |
| Lane-WS13 (WS13) | POOL-04 SubAgent-Scaffold | 2-3 | 同一 task_id 仅允许 1 个 Agent owner；跨池任务必须挂协同票据 |
| Lane-WS14 (WS14) | POOL-05 Security-Runtime | 3-4 | 同一 task_id 仅允许 1 个 Agent owner；跨池任务必须挂协同票据 |
| Lane-WS15 (WS15) | POOL-06 Memory-GC | 2-3 | 同一 task_id 仅允许 1 个 Agent owner；跨池任务必须挂协同票据 |
| Lane-WS16 (WS16) | POOL-07 Migration-Compat | 1-2 | 同一 task_id 仅允许 1 个 Agent owner；跨池任务必须挂协同票据 |
| Lane-WS17 (WS17) | POOL-08 QA-Release | 2-3 | 同一 task_id 仅允许 1 个 Agent owner；跨池任务必须挂协同票据 |
| Lane-WS18 (WS18) | POOL-09 Brainstem-Core | 2-3 | 同一 task_id 仅允许 1 个 Agent owner；跨池任务必须挂协同票据 |
| Lane-WS19 (WS19) | POOL-10 Brain-Core | 2-3 | 同一 task_id 仅允许 1 个 Agent owner；跨池任务必须挂协同票据 |
| Lane-WS20 (WS20) | POOL-11 Frontend-BFF | 2-3 | 同一 task_id 仅允许 1 个 Agent owner；跨池任务必须挂协同票据 |

## 4. 里程碑门禁（M0-M5）

| 里程碑 | 强制出场条件 | Gate 决策 | 未通过处理 |
|---|---|---|---|
| M0 | backlog 完整、关键风险归属完备 | `GO/NO-GO` | 缺字段任务不得入 S2 |
| M1 | `artifact_reader` 可读、Artifact 防爆、KillSwitch OOB 生效 | `GO/NO-GO` | 阻断 S4+ |
| M2 | file_ast 冲突治理、Sub-Agent 事务化、Double-Fork 回收演练通过 | `GO/NO-GO` | 阻断 S6+ |
| M3 | GC 证据召回达标、Token 守门生效 | `GO/NO-GO` | 阻断能力放大任务 |
| M4 | 兼容迁移完成且可回退、弃用路径收口 | `GO/NO-GO` | 阻断发布预备 |
| M5 | 混沌场景通过、Canary+Rollback 通过、值班体系完整 | `GO/NO-GO` | 禁止正式发布 |

## 5. 风险闭环验证（Critical/High）

| 风险 | 等级 | 主实现任务 | 验证任务 | 闭环要求 |
|---|---|---|---|---|
| R1 命令混淆绕过 | Critical | NGA-WS14-001,NGA-WS14-002 | NGA-WS17-005 | 必须产出验证证据（日志/报告/runbook） |
| R2 插件宿主劫持 | Critical | NGA-WS10-003,NGA-WS13-001 | NGA-WS17-003 | 必须产出验证证据（日志/报告/runbook） |
| R3 锁泄漏与物理层失控 | Critical | NGA-WS14-003,NGA-WS14-004 | NGA-WS17-004 | 必须产出验证证据（日志/报告/runbook） |
| R4 结构化数据破损 | High | NGA-WS10-001,NGA-WS11-003 | NGA-WS17-003 | 必须产出验证证据（日志/报告/runbook） |
| R5 Test Poisoning | Critical | NGA-WS17-001,NGA-WS17-002 | NGA-WS17-003 | 必须产出验证证据（日志/报告/runbook） |
| R6 ReDoS + 日志轮转假死 | Critical | NGA-WS14-007,NGA-WS14-008 | NGA-WS17-005 | 必须产出验证证据（日志/报告/runbook） |
| R7 ZFS/Btrfs 单依赖 | High | NGA-WS16-001,NGA-WS16-004 | NGA-WS17-006 | 必须产出验证证据（日志/报告/runbook） |
| R8 GC 丢失关键证据 | High | NGA-WS15-001,NGA-WS15-002 | NGA-WS15-006 | 必须产出验证证据（日志/报告/runbook） |
| R9 raw_result_ref 读后即盲 | High | NGA-WS11-002,NGA-WS11-003 | NGA-WS17-003 | 必须产出验证证据（日志/报告/runbook） |
| R10 file_ast Monolith OOM | High | NGA-WS12-001,NGA-WS12-002 | NGA-WS12-006 | 必须产出验证证据（日志/报告/runbook） |
| R11 file_ast 并发活锁 | High | NGA-WS12-003,NGA-WS12-004 | NGA-WS12-006 | 必须产出验证证据（日志/报告/runbook） |
| R12 Sub-Agent 并行盲写 | High | NGA-WS13-001,NGA-WS13-002 | NGA-WS13-006 | 必须产出验证证据（日志/报告/runbook） |
| R13 Scaffold 非原子半写 | High | NGA-WS13-004,NGA-WS13-005 | NGA-WS13-006 | 必须产出验证证据（日志/报告/runbook） |
| R14 KillSwitch 无 OOB | Critical | NGA-WS14-009,NGA-WS14-010 | NGA-WS17-007 | 必须产出验证证据（日志/报告/runbook） |
| R15 Double-Fork 幽灵逃逸 | Critical | NGA-WS14-005,NGA-WS14-006 | NGA-WS17-006 | 必须产出验证证据（日志/报告/runbook） |
| R16 Artifact 磁盘 DoS | Critical | NGA-WS11-004,NGA-WS11-005 | NGA-WS17-006 | 必须产出验证证据（日志/报告/runbook） |

校验结论：Critical/High 风险 16/16 均已绑定验证任务。

## 6. 日执行节奏

1. 每日按 `WIP <= 并发建议` 派工，超载任务自动推迟到下一日。
2. 每日两次 Gate 快照（中午/收工）：更新 `09-execution-board.csv` 状态。
3. `blocked` 超过 1 个工作日必须提交依赖解除单。
4. 任何 P0 任务转 `done` 前必须附回滚演练证据。
