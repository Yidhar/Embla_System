# 05 Sprint 执行池分配矩阵（AI Agent 团队）

生成时间：2026-02-23  
输入基线：`doc/task/99-task-backlog.csv`（76 任务）

## 目标

- 把每个 Sprint 进一步细分为可分派给 AI Agent 执行池（Pool）的任务包。
- 同层任务并行，跨层任务串行；每个 Sprint 执行后必须做 Gate 检查。
- 统一采用任务单元规范：`doc/task/00-task-unit-spec.md`。

## 执行池定义

| Pool | 对应工作流 | 责任域 | 建议并发(Agent) |
|---|---|---|---:|
| POOL-01 Contract-Gateway | WS10 | Tool Contract / Gateway / Schema | 2-3 |
| POOL-02 Artifact-Evidence | WS11 | Artifact Store / Reader / IO Evidence | 2-3 |
| POOL-03 AST-Concurrency | WS12 | file_ast / Conflict / Arbiter | 2-3 |
| POOL-04 SubAgent-Scaffold | WS13 | Contract Gate / Scaffold / Txn | 2-3 |
| POOL-05 Security-Runtime | WS14 | Firewall / Mutex / Fencing / OOB | 3-4 |
| POOL-06 Memory-GC | WS15 | GC / Evidence Extract / Injection | 2-3 |
| POOL-07 Migration-Compat | WS16 | Migration / Compatibility / Deprecation | 1-2 |
| POOL-08 QA-Release | WS17 | Test Guard / Chaos / Canary / SLO | 2-3 |
| POOL-09 Brainstem-Core | WS18 | EventBus / Watchdog / DNA | 2-3 |
| POOL-10 Brain-Core | WS19 | Meta / Router / Memory Core | 2-3 |
| POOL-11 Frontend-BFF | WS20 | API Contract / SSE / UI-BFF | 2-3 |

## Sprint 资源总览

| Sprint | 依赖层 | 任务数 | P0 | P1 | P2 | 建议并发上限 |
|---|---|---:|---:|---:|---:|---:|
| S1 | L0 | 3 | 3 | 0 | 0 | 3 |
| S2 | L1 | 12 | 6 | 6 | 0 | 12 |
| S3 | L2 | 20 | 7 | 12 | 0 | 20 |
| S4 | L3 | 19 | 4 | 12 | 3 | 19 |
| S5 | L4 | 9 | 2 | 7 | 0 | 9 |
| S6 | L5 | 10 | 0 | 6 | 4 | 10 |
| S7 | L6 | 3 | 0 | 2 | 0 | 3 |

## S1（L0）

- Sprint 目标：建立基线根节点（契约、迁移盘点、测试基线）
- 任务数：3
- P0 任务：NGA-WS10-001、NGA-WS16-001、NGA-WS17-001
- 跨池同步关注：无

| 执行池 | 任务包 |
|---|---|
| POOL-01 Contract-Gateway | NGA-WS10-001 统一 Tool Contract 字段模型 |
| POOL-07 Migration-Compat | NGA-WS16-001 迁移资产清单与依赖盘点 |
| POOL-08 QA-Release | NGA-WS17-001 测试基线只读隔离 |

Sprint Gate（DoD）:
1. 本层任务状态全部进入 `review` 或 `done`，且无 `blocked`。
2. P0 任务必须带负向测试与回滚验证记录。
3. 本层变更通过最小联调回归后，方可进入下一层。

## S2（L1）

- Sprint 目标：打通 P0 前置门禁（调用元数据、schema、大文件入口）
- 任务数：12
- P0 任务：NGA-WS10-002、NGA-WS10-003、NGA-WS11-001、NGA-WS12-001、NGA-WS13-001、NGA-WS17-002
- 跨池同步关注：无

| 执行池 | 任务包 |
|---|---|
| POOL-01 Contract-Gateway | NGA-WS10-002 注入调用上下文元数据<br/>NGA-WS10-003 建立输入输出 schema 强校验 |
| POOL-02 Artifact-Evidence | NGA-WS11-001 建立 Artifact 元数据模型 |
| POOL-03 AST-Concurrency | NGA-WS12-001 实现 file_ast_skeleton 分层读取 |
| POOL-04 SubAgent-Scaffold | NGA-WS13-001 设计 Contract Gate 契约模型 |
| POOL-07 Migration-Compat | NGA-WS16-002 AgentServer 弃用路径设计<br/>NGA-WS16-003 MCP 状态占位接口收敛<br/>NGA-WS16-004 配置迁移脚本与版本化 |
| POOL-08 QA-Release | NGA-WS17-002 Anti-Test-Poisoning 检查器<br/>NGA-WS17-003 Clean Checkout 双轨验证 |
| POOL-09 Brainstem-Core | NGA-WS18-001 Event Bus 事件模型收敛 |
| POOL-11 Frontend-BFF | NGA-WS20-001 API 契约冻结与版本策略 |

Sprint Gate（DoD）:
1. 本层任务状态全部进入 `review` 或 `done`，且无 `blocked`。
2. P0 任务必须带负向测试与回滚验证记录。
3. 本层变更通过最小联调回归后，方可进入下一层。

## S3（L2）

- Sprint 目标：P0 止血主战场（artifact、mutex、policy、watch）
- 任务数：20
- P0 任务：NGA-WS11-002、NGA-WS11-004、NGA-WS12-002、NGA-WS13-002、NGA-WS14-001、NGA-WS14-003、NGA-WS14-007
- 跨池同步关注：NGA-WS10-006 兼容开关与灰度发布策略；NGA-WS16-005 兼容双栈灰度与下线开关

| 执行池 | 任务包 |
|---|---|
| POOL-01 Contract-Gateway | NGA-WS10-004 统一工具回执模板与审计记录<br/>NGA-WS10-005 风险门禁与审批钩子收敛<br/>NGA-WS10-006 兼容开关与灰度发布策略 |
| POOL-02 Artifact-Evidence | NGA-WS11-002 实现 artifact_reader 工具<br/>NGA-WS11-004 实现 Artifact 配额与生命周期策略 |
| POOL-03 AST-Concurrency | NGA-WS12-002 实现定向 chunk 读取 |
| POOL-04 SubAgent-Scaffold | NGA-WS13-002 并行前契约协商门禁 |
| POOL-05 Security-Runtime | NGA-WS14-001 Policy Firewall 能力白名单校验<br/>NGA-WS14-003 Global Mutex TTL Heartbeat Fencing<br/>NGA-WS14-007 Sleep Watch ReDoS 防护 |
| POOL-06 Memory-GC | NGA-WS15-001 关键证据字段抽取器 |
| POOL-07 Migration-Compat | NGA-WS16-005 兼容双栈灰度与下线开关 |
| POOL-08 QA-Release | NGA-WS17-007 Canary 与自动回滚收敛 |
| POOL-09 Brainstem-Core | NGA-WS18-002 Outbox Inbox 可靠投递整合<br/>NGA-WS18-004 Watchdog 资源监控器落地<br/>NGA-WS18-006 Immutable DNA 注入与校验 |
| POOL-10 Brain-Core | NGA-WS19-001 Meta-Agent 服务骨架落地<br/>NGA-WS19-003 LLM Gateway 分层路由与缓存 |
| POOL-11 Frontend-BFF | NGA-WS20-003 前端模块按域解耦<br/>NGA-WS20-004 MCP 状态展示与真实后端对齐 |

Sprint Gate（DoD）:
1. 本层任务状态全部进入 `review` 或 `done`，且无 `blocked`。
2. P0 任务必须带负向测试与回滚验证记录。
3. 本层变更通过最小联调回归后，方可进入下一层。

## S4（L3）

- Sprint 目标：冲突治理与 OOB/双栈关键链路
- 任务数：19
- P0 任务：NGA-WS11-003、NGA-WS14-002、NGA-WS14-005、NGA-WS14-009
- 跨池同步关注：NGA-WS11-006 证据链可观测性；NGA-WS18-008 Brainstem 守护进程打包与托管

| 执行池 | 任务包 |
|---|---|
| POOL-02 Artifact-Evidence | NGA-WS11-003 os_bash 接入 fetch_hints<br/>NGA-WS11-005 高水位背压与关键路径保护<br/>NGA-WS11-006 证据链可观测性 |
| POOL-03 AST-Concurrency | NGA-WS12-003 语义重基 semantic_rebase |
| POOL-04 SubAgent-Scaffold | NGA-WS13-003 Scaffold contract-aware 生成 |
| POOL-05 Security-Runtime | NGA-WS14-002 解释器入口硬门禁<br/>NGA-WS14-004 Orphan Lock 清道夫<br/>NGA-WS14-005 Process Lineage 绑定与回收<br/>NGA-WS14-008 Logrotate 容错<br/>NGA-WS14-009 KillSwitch OOB 出口策略 |
| POOL-06 Memory-GC | NGA-WS15-002 叙事摘要与证据引用分离 |
| POOL-07 Migration-Compat | NGA-WS16-006 文档与 runbook 同步收口 |
| POOL-09 Brainstem-Core | NGA-WS18-003 Event Replay 与恢复路径<br/>NGA-WS18-005 Loop Detector 与成本熔断联动<br/>NGA-WS18-007 DNA 变更审计与审批流程<br/>NGA-WS18-008 Brainstem 守护进程打包与托管 |
| POOL-10 Brain-Core | NGA-WS19-002 Router 规则引擎与角色路由<br/>NGA-WS19-004 Working Memory 窗口管理器 |
| POOL-11 Frontend-BFF | NGA-WS20-002 SSE 事件协议统一 |

Sprint Gate（DoD）:
1. 本层任务状态全部进入 `review` 或 `done`，且无 `blocked`。
2. P0 任务必须带负向测试与回滚验证记录。
3. 本层变更通过最小联调回归后，方可进入下一层。

## S5（L4）

- Sprint 目标：事务化提交与 detached 清理
- 任务数：9
- P0 任务：NGA-WS13-004、NGA-WS14-006
- 跨池同步关注：NGA-WS17-004 混沌演练 锁泄漏与切主；NGA-WS17-005 混沌演练 ReDoS 与 logrotate；NGA-WS20-005 前后端联调回归套件

| 执行池 | 任务包 |
|---|---|
| POOL-03 AST-Concurrency | NGA-WS12-004 冲突票据与退避机制 |
| POOL-04 SubAgent-Scaffold | NGA-WS13-004 Workspace Transaction 管理器 |
| POOL-05 Security-Runtime | NGA-WS14-006 Double-Fork 幽灵进程清理<br/>NGA-WS14-010 OOB 健康探测与恢复 runbook |
| POOL-06 Memory-GC | NGA-WS15-003 GC 注入策略改造 |
| POOL-08 QA-Release | NGA-WS17-004 混沌演练 锁泄漏与切主<br/>NGA-WS17-005 混沌演练 ReDoS 与 logrotate |
| POOL-10 Brain-Core | NGA-WS19-005 Episodic Memory 写入与检索链路 |
| POOL-11 Frontend-BFF | NGA-WS20-005 前后端联调回归套件 |

Sprint Gate（DoD）:
1. 本层任务状态全部进入 `review` 或 `done`，且无 `blocked`。
2. P0 任务必须带负向测试与回滚验证记录。
3. 本层变更通过最小联调回归后，方可进入下一层。

## S6（L5）

- Sprint 目标：迁移收口与发布前回归
- 任务数：10
- P0 任务：无
- 跨池同步关注：NGA-WS12-006 大文件与并发压测基线；NGA-WS15-005 证据回读自动化链路；NGA-WS17-006 混沌演练 double-fork 与磁盘压力；NGA-WS17-008 SLO 告警看板上线；NGA-WS19-007 Daily Checkpoint 日结归档

| 执行池 | 任务包 |
|---|---|
| POOL-03 AST-Concurrency | NGA-WS12-005 Router 仲裁升级路径<br/>NGA-WS12-006 大文件与并发压测基线 |
| POOL-04 SubAgent-Scaffold | NGA-WS13-005 clean_state 保证与恢复票据 |
| POOL-06 Memory-GC | NGA-WS15-004 GC 预算守门与回路防抖<br/>NGA-WS15-005 证据回读自动化链路 |
| POOL-08 QA-Release | NGA-WS17-006 混沌演练 double-fork 与磁盘压力<br/>NGA-WS17-008 SLO 告警看板上线 |
| POOL-10 Brain-Core | NGA-WS19-006 Semantic Graph 拓扑扫描与更新<br/>NGA-WS19-007 Daily Checkpoint 日结归档 |
| POOL-11 Frontend-BFF | NGA-WS20-006 桌面端发布兼容性验证 |

Sprint Gate（DoD）:
1. 本层任务状态全部进入 `review` 或 `done`，且无 `blocked`。
2. P0 任务必须带负向测试与回滚验证记录。
3. 本层变更通过最小联调回归后，方可进入下一层。

## S7（L6）

- Sprint 目标：最终发布稳态验收
- 任务数：3
- P0 任务：无
- 跨池同步关注：NGA-WS13-006 跨文件事务回归与联调；NGA-WS15-006 GC 质量评测与回归基线；NGA-WS19-008 Router 仲裁熔断联动

| 执行池 | 任务包 |
|---|---|
| POOL-04 SubAgent-Scaffold | NGA-WS13-006 跨文件事务回归与联调 |
| POOL-06 Memory-GC | NGA-WS15-006 GC 质量评测与回归基线 |
| POOL-10 Brain-Core | NGA-WS19-008 Router 仲裁熔断联动 |

Sprint Gate（DoD）:
1. 本层任务状态全部进入 `review` 或 `done`，且无 `blocked`。
2. P0 任务必须带负向测试与回滚验证记录。
3. 本层变更通过最小联调回归后，方可进入下一层。

