# 90 风险-任务追踪矩阵（R1-R16）

## 1. 说明

本矩阵用于确认每个风险至少被一个任务包覆盖，且关键风险有“实现任务 + 测试任务 + 运维任务”三层闭环。

## 2. 映射矩阵

| 风险ID | 风险主题 | 对应任务（主） | 对应任务（验证/运维） |
|---|---|---|---|
| R1 | 命令混淆绕过 | NGA-WS14-001, NGA-WS14-002 | NGA-WS17-005 |
| R2 | 插件宿主劫持 | NGA-WS10-003, NGA-WS13-001 | NGA-WS17-003 |
| R3 | 锁泄漏与物理层失控 | NGA-WS14-003, NGA-WS14-004 | NGA-WS17-004 |
| R4 | 结构化数据破损 | NGA-WS10-001, NGA-WS11-003 | NGA-WS17-003 |
| R5 | Test Poisoning | NGA-WS17-001, NGA-WS17-002 | NGA-WS17-003 |
| R6 | ReDoS + 日志轮转假死 | NGA-WS14-007, NGA-WS14-008 | NGA-WS17-005 |
| R7 | ZFS/Btrfs 单依赖 | NGA-WS16-001, NGA-WS16-004 | NGA-WS17-006 |
| R8 | GC 丢失关键证据 | NGA-WS15-001, NGA-WS15-002 | NGA-WS15-006 |
| R9 | raw_result_ref 读后即盲 | NGA-WS11-002, NGA-WS11-003 | NGA-WS17-003 |
| R10 | file_ast Monolith OOM | NGA-WS12-001, NGA-WS12-002 | NGA-WS12-006 |
| R11 | file_ast 并发活锁 | NGA-WS12-003, NGA-WS12-004 | NGA-WS12-006 |
| R12 | Sub-Agent 并行盲写 | NGA-WS13-001, NGA-WS13-002 | NGA-WS13-006 |
| R13 | Scaffold 非原子半写 | NGA-WS13-004, NGA-WS13-005 | NGA-WS13-006 |
| R14 | KillSwitch 无 OOB | NGA-WS14-009, NGA-WS14-010 | NGA-WS17-007 |
| R15 | Double-Fork 幽灵逃逸 | NGA-WS14-005, NGA-WS14-006 | NGA-WS17-006 |
| R16 | Artifact 磁盘 DoS | NGA-WS11-004, NGA-WS11-005 | NGA-WS17-006 |

## 3. 覆盖检查规则

1. 每个风险至少要有一个 `P0/P1` 主任务。
2. 每个 `Critical/High` 风险必须同时存在验证任务。
3. 上线前需要出具“风险覆盖完成度”报告。
