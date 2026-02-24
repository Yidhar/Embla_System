# 01 迁移与增量开发总路线图

## 1. 路线图原则

1. 先止血（P0）再补治理（P1），最后做能力放大（P2）。
2. 先契约收敛，再大规模并行开发。
3. 每个里程碑必须有明确出场条件（Exit Criteria）。

## 2. 里程碑定义

| 里程碑 | 目标 | 主要工作流 |
|---|---|---|
| `M0` 基线收敛 | 任务模型、契约边界、排期落地 | WS10, WS16 |
| `M1` P0 止血 | 高风险链路先可控可回退 | WS11, WS14, WS17, WS20 |
| `M2` P1 治理 | 并发/事务/安全治理补齐 | WS12, WS13, WS14, WS18 |
| `M3` P2 能力 | 认知与记忆闭环增强 | WS15, WS19 |
| `M4` 迁移收尾 | 兼容清理、弃用收敛 | WS16, WS20, WS18 |
| `M5` 发布稳态 | 混沌验证、SLO、灰度发布 | WS17, WS20 |

## 3. 阶段出场条件

### M0 出场条件

1. `99-task-backlog.csv` 可导入并完整。
2. 所有任务均具备 `task_id/depends_on/acceptance/rollback`。
3. 关键风险（R9-R16）有明确归属任务。

### M1 出场条件

1. `raw_result_ref` 已具备可读链路（artifact_reader）。
2. KillSwitch 具备 OOB 保活策略。
3. Artifact Store 有配额与高水位保护。

### M2 出场条件

1. `file_ast` 巨型文件路径与冲突退避上线。
2. Sub-Agent 契约门禁 + 脚手架事务化可用。
3. Double-Fork 回收路径通过演练。

### M3 出场条件

1. GC 证据链可检索且关键字段召回达标。
2. Token 预算守门与回路防抖生效。

### M4 出场条件

1. 兼容层迁移完成且有回退窗口。
2. 弃用路径关闭并保留审计记录。

### M5 出场条件

1. 混沌场景通过：锁泄漏、logrotate、double-fork、磁盘压力。
2. canary + rollback 机制在预生产演练通过。
3. 发布 runbook、告警面板、值班策略完整。

## 4. 关键依赖链

1. `WS10` -> `WS11` -> `WS15` -> `WS19`
2. `WS12` -> `WS13` -> `WS17`
3. `WS14` 与 `WS18` 贯穿控制面，是 `M1/M2` 核心门禁
4. `WS20` 依赖契约收敛，禁止先改 UI 再改协议
5. `WS16` 在 `M4` 收口，禁止提前硬删兼容层

## 5. 参考文档

- `doc/01-module-overview.md`
- `doc/07-autonomous-agent-sdlc-architecture.md`
- `doc/09-tool-execution-specification.md`
- `doc/10-brainstem-layer-modules.md`
- `doc/11-brain-layer-modules.md`
- `doc/12-limbs-layer-modules.md`
- `doc/13-security-blindspots-and-hardening.md`
