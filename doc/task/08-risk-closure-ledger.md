# 08 风险闭环验证台账（Critical/High）

用途：确保每个 Critical/High 风险都存在“实现任务 + 验证任务 + 证据产物”。

| risk_id | topic | severity | implementation_tasks | verification_tasks | evidence_required | gate | status |
|---|---|---|---|---|---|---|---|
| R1 | 命令混淆绕过 | Critical | NGA-WS14-001,NGA-WS14-002 | NGA-WS17-005 | 负向测试报告 + 运行日志 + 回滚/恢复记录 | M1/M2/M5 | done |
| R2 | 插件宿主劫持 | Critical | NGA-WS10-003,NGA-WS13-001 | NGA-WS17-003 | 负向测试报告 + 运行日志 + 回滚/恢复记录 | M1/M2/M5 | review |
| R3 | 锁泄漏与物理层失控 | Critical | NGA-WS14-003,NGA-WS14-004 | NGA-WS17-004 | 负向测试报告 + 运行日志 + 回滚/恢复记录 | M1/M2/M5 | review |
| R4 | 结构化数据破损 | High | NGA-WS10-001,NGA-WS11-003 | NGA-WS17-003 | 负向测试报告 + 运行日志 + 回滚/恢复记录 | M2/M3/M5 | review |
| R5 | Test Poisoning | Critical | NGA-WS17-001,NGA-WS17-002 | NGA-WS17-003 | 负向测试报告 + 运行日志 + 回滚/恢复记录 | M1/M2/M5 | review |
| R6 | ReDoS + 日志轮转假死 | Critical | NGA-WS14-007,NGA-WS14-008 | NGA-WS17-005 | 负向测试报告 + 运行日志 + 回滚/恢复记录 | M1/M2/M5 | done |
| R7 | ZFS/Btrfs 单依赖 | High | NGA-WS16-001,NGA-WS16-004 | NGA-WS17-006 | 负向测试报告 + 运行日志 + 回滚/恢复记录 | M2/M3/M5 | review |
| R8 | GC 丢失关键证据 | High | NGA-WS15-001,NGA-WS15-002 | NGA-WS15-006 | 负向测试报告 + 运行日志 + 回滚/恢复记录 | M2/M3/M5 | review |
| R9 | raw_result_ref 读后即盲 | High | NGA-WS11-002,NGA-WS11-003 | NGA-WS17-003 | 负向测试报告 + 运行日志 + 回滚/恢复记录 | M2/M3/M5 | review |
| R10 | file_ast Monolith OOM | High | NGA-WS12-001,NGA-WS12-002 | NGA-WS12-006 | 负向测试报告 + 运行日志 + 回滚/恢复记录 | M2/M3/M5 | review |
| R11 | file_ast 并发活锁 | High | NGA-WS12-003,NGA-WS12-004 | NGA-WS12-006 | 负向测试报告 + 运行日志 + 回滚/恢复记录 | M2/M3/M5 | review |
| R12 | Sub-Agent 并行盲写 | High | NGA-WS13-001,NGA-WS13-002 | NGA-WS13-006 | 负向测试报告 + 运行日志 + 回滚/恢复记录 | M2/M3/M5 | review |
| R13 | Scaffold 非原子半写 | High | NGA-WS13-004,NGA-WS13-005 | NGA-WS13-006 | 负向测试报告 + 运行日志 + 回滚/恢复记录 | M2/M3/M5 | review |
| R14 | KillSwitch 无 OOB | Critical | NGA-WS14-009,NGA-WS14-010 | NGA-WS17-007 | 负向测试报告 + 运行日志 + 回滚/恢复记录 | M1/M2/M5 | review |
| R15 | Double-Fork 幽灵逃逸 | Critical | NGA-WS14-005,NGA-WS14-006 | NGA-WS17-006 | 负向测试报告 + 运行日志 + 回滚/恢复记录 | M1/M2/M5 | review |
| R16 | Artifact 磁盘 DoS | Critical | NGA-WS11-004,NGA-WS11-005 | NGA-WS17-006 | 负向测试报告 + 运行日志 + 回滚/恢复记录 | M1/M2/M5 | review |

执行规则：
1. `status=done` 前必须补齐证据链接。
2. Critical 风险未闭环，不得通过 M2/M5 Gate。
3. High 风险未闭环，不得通过 M3/M5 Gate。

