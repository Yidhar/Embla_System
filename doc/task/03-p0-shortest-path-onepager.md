# 03 P0 最短路径一页执行清单（先止血）

目标：以最短依赖路径完成 P0 风险止血。

- P0 目标任务：22
- 最短路径闭包任务：23
- 桥接任务（非P0但必须完成）：`NGA-WS13-003`

## 一页执行波次

| 波次 | 依赖层级 | 关键目标 | 任务清单 |
|---|---|---|---|
| W1 | L0 | 建立止血根节点 | NGA-WS10-001<br/>NGA-WS16-001<br/>NGA-WS17-001 |
| W2 | L1 | 打通契约与测试守门 | NGA-WS10-002<br/>NGA-WS10-003<br/>NGA-WS11-001<br/>NGA-WS12-001<br/>NGA-WS13-001<br/>NGA-WS17-002 |
| W3 | L2 | 上线核心止血能力 | NGA-WS11-002<br/>NGA-WS11-004<br/>NGA-WS12-002<br/>NGA-WS13-002<br/>NGA-WS14-001<br/>NGA-WS14-003<br/>NGA-WS14-007 |
| W4 | L3 | 补齐关键拦截与OOB通道 | NGA-WS11-003<br/>NGA-WS13-003(bridge)<br/>NGA-WS14-002<br/>NGA-WS14-005<br/>NGA-WS14-009 |
| W5 | L4 | 完成高风险链路收口 | NGA-WS13-004<br/>NGA-WS14-006 |

## 止血完成判定（Exit）

1. `raw_result_ref` 可读：`artifact_reader` 可定位中段根因。
2. Artifact 防爆：配额+TTL+高水位生效。
3. 命令策略与解释器入口拦截生效。
4. Global Mutex + Fencing + orphan 回收可用。
5. KillSwitch 保留 OOB 管理通道。
6. file_ast 大文件路径与冲突治理主链可用。
7. Sub-Agent 事务化提交链路已闭环。

## 关联风险

- 直接覆盖：R1, R3, R5, R6, R9, R10, R11, R12, R13, R14, R15, R16
- 参考映射：`doc/task/90-risk-traceability-matrix.md`
