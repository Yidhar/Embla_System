# 02 AI Agent Sprint 自动拆解（76任务）

生成时间：2026-02-23  
拆解算法：按依赖拓扑层级（L0-L6）自动分配 Sprint（S1-S7），同层并行、跨层串行。

## 全局统计

- 总任务数：76
- P0 任务数：22
- 依赖层级：L0-L6（共 7 层）
- Sprint 数：7

## Sprint 汇总表

| Sprint | 依赖层级 | 任务数 | P0数 | 主要工作流 |
|---|---|---:|---:|---|
| S1 | L0 | 3 | 3 | WS10, WS16, WS17 |
| S2 | L1 | 12 | 6 | WS10, WS11, WS12, WS13, WS16, WS17, WS18, WS20 |
| S3 | L2 | 20 | 7 | WS10, WS11, WS12, WS13, WS14, WS15, WS16, WS17, WS18, WS19, WS20 |
| S4 | L3 | 19 | 4 | WS11, WS12, WS13, WS14, WS15, WS16, WS18, WS19, WS20 |
| S5 | L4 | 9 | 2 | WS12, WS13, WS14, WS15, WS17, WS19, WS20 |
| S6 | L5 | 10 | 0 | WS12, WS13, WS15, WS17, WS19, WS20 |
| S7 | L6 | 3 | 0 | WS13, WS15, WS19 |

## Sprint S1（L0）

- 目标：建立基线根节点（契约、迁移盘点、测试基线）
- 任务数：3，其中 P0：3

| task_id | priority | phase | workstream | title | depends_on |
|---|---|---|---|---|---|
| NGA-WS10-001 | P0 | M0 | WS10 | 统一 Tool Contract 字段模型 | - |
| NGA-WS16-001 | P0 | M0 | WS16 | 迁移资产清单与依赖盘点 | - |
| NGA-WS17-001 | P0 | M1 | WS17 | 测试基线只读隔离 | - |

## Sprint S2（L1）

- 目标：打通 P0 前置门禁（调用元数据、schema、大文件入口）
- 任务数：12，其中 P0：6

| task_id | priority | phase | workstream | title | depends_on |
|---|---|---|---|---|---|
| NGA-WS10-002 | P0 | M0 | WS10 | 注入调用上下文元数据 | NGA-WS10-001 |
| NGA-WS10-003 | P0 | M1 | WS10 | 建立输入输出 schema 强校验 | NGA-WS10-001 |
| NGA-WS11-001 | P0 | M1 | WS11 | 建立 Artifact 元数据模型 | NGA-WS10-001 |
| NGA-WS12-001 | P0 | M1 | WS12 | 实现 file_ast_skeleton 分层读取 | NGA-WS10-001 |
| NGA-WS13-001 | P0 | M2 | WS13 | 设计 Contract Gate 契约模型 | NGA-WS10-001 |
| NGA-WS17-002 | P0 | M1 | WS17 | Anti-Test-Poisoning 检查器 | NGA-WS17-001 |
| NGA-WS16-002 | P1 | M4 | WS16 | AgentServer 弃用路径设计 | NGA-WS16-001 |
| NGA-WS16-003 | P1 | M4 | WS16 | MCP 状态占位接口收敛 | NGA-WS10-001 |
| NGA-WS16-004 | P1 | M4 | WS16 | 配置迁移脚本与版本化 | NGA-WS16-001 |
| NGA-WS17-003 | P1 | M2 | WS17 | Clean Checkout 双轨验证 | NGA-WS17-001 |
| NGA-WS18-001 | P1 | M2 | WS18 | Event Bus 事件模型收敛 | NGA-WS10-001 |
| NGA-WS20-001 | P1 | M1 | WS20 | API 契约冻结与版本策略 | NGA-WS10-001 |

## Sprint S3（L2）

- 目标：P0 止血主战场（artifact、mutex、policy、watch）
- 任务数：20，其中 P0：7

| task_id | priority | phase | workstream | title | depends_on |
|---|---|---|---|---|---|
| NGA-WS11-002 | P0 | M1 | WS11 | 实现 artifact_reader 工具 | NGA-WS11-001 |
| NGA-WS11-004 | P0 | M1 | WS11 | 实现 Artifact 配额与生命周期策略 | NGA-WS11-001 |
| NGA-WS12-002 | P0 | M1 | WS12 | 实现定向 chunk 读取 | NGA-WS12-001 |
| NGA-WS13-002 | P0 | M2 | WS13 | 并行前契约协商门禁 | NGA-WS13-001 |
| NGA-WS14-001 | P0 | M1 | WS14 | Policy Firewall 能力白名单校验 | NGA-WS10-003 |
| NGA-WS14-003 | P0 | M2 | WS14 | Global Mutex TTL Heartbeat Fencing | NGA-WS10-002 |
| NGA-WS14-007 | P0 | M1 | WS14 | Sleep Watch ReDoS 防护 | NGA-WS10-003 |
| NGA-WS10-004 | P1 | M1 | WS10 | 统一工具回执模板与审计记录 | NGA-WS10-002 |
| NGA-WS10-005 | P1 | M1 | WS10 | 风险门禁与审批钩子收敛 | NGA-WS10-003 |
| NGA-WS10-006 | P1 | M2 | WS10 | 兼容开关与灰度发布策略 | NGA-WS10-001;NGA-WS10-003 |
| NGA-WS15-001 | P1 | M3 | WS15 | 关键证据字段抽取器 | NGA-WS11-001 |
| NGA-WS16-005 | P1 | M4 | WS16 | 兼容双栈灰度与下线开关 | NGA-WS16-003;NGA-WS16-004 |
| NGA-WS17-007 | P1 | M5 | WS17 | Canary 与自动回滚收敛 | NGA-WS17-003 |
| NGA-WS18-002 | P1 | M2 | WS18 | Outbox Inbox 可靠投递整合 | NGA-WS18-001 |
| NGA-WS18-004 | P1 | M2 | WS18 | Watchdog 资源监控器落地 | NGA-WS10-002 |
| NGA-WS18-006 | P1 | M2 | WS18 | Immutable DNA 注入与校验 | NGA-WS10-003 |
| NGA-WS19-001 | P1 | M3 | WS19 | Meta-Agent 服务骨架落地 | NGA-WS18-001 |
| NGA-WS19-003 | P1 | M3 | WS19 | LLM Gateway 分层路由与缓存 | NGA-WS10-003 |
| NGA-WS20-004 | P1 | M4 | WS20 | MCP 状态展示与真实后端对齐 | NGA-WS16-003 |
| NGA-WS20-003 | P2 | M3 | WS20 | 前端模块按域解耦 | NGA-WS20-001 |

## Sprint S4（L3）

- 目标：冲突治理与 OOB/双栈关键链路
- 任务数：19，其中 P0：4

| task_id | priority | phase | workstream | title | depends_on |
|---|---|---|---|---|---|
| NGA-WS11-003 | P0 | M1 | WS11 | os_bash 接入 fetch_hints | NGA-WS11-002 |
| NGA-WS14-002 | P0 | M1 | WS14 | 解释器入口硬门禁 | NGA-WS14-001 |
| NGA-WS14-005 | P0 | M2 | WS14 | Process Lineage 绑定与回收 | NGA-WS14-003 |
| NGA-WS14-009 | P0 | M1 | WS14 | KillSwitch OOB 出口策略 | NGA-WS14-001 |
| NGA-WS11-005 | P1 | M2 | WS11 | 高水位背压与关键路径保护 | NGA-WS11-004 |
| NGA-WS11-006 | P1 | M2 | WS11 | 证据链可观测性 | NGA-WS11-002;NGA-WS11-004 |
| NGA-WS12-003 | P1 | M2 | WS12 | 语义重基 semantic_rebase | NGA-WS12-002 |
| NGA-WS13-003 | P1 | M2 | WS13 | Scaffold contract-aware 生成 | NGA-WS13-002 |
| NGA-WS14-004 | P1 | M2 | WS14 | Orphan Lock 清道夫 | NGA-WS14-003 |
| NGA-WS14-008 | P1 | M1 | WS14 | Logrotate 容错 | NGA-WS14-007 |
| NGA-WS15-002 | P1 | M3 | WS15 | 叙事摘要与证据引用分离 | NGA-WS15-001 |
| NGA-WS18-003 | P1 | M2 | WS18 | Event Replay 与恢复路径 | NGA-WS18-002 |
| NGA-WS18-005 | P1 | M2 | WS18 | Loop Detector 与成本熔断联动 | NGA-WS18-004 |
| NGA-WS19-002 | P1 | M3 | WS19 | Router 规则引擎与角色路由 | NGA-WS19-001 |
| NGA-WS19-004 | P1 | M3 | WS19 | Working Memory 窗口管理器 | NGA-WS19-003 |
| NGA-WS20-002 | P1 | M2 | WS20 | SSE 事件协议统一 | NGA-WS10-004 |
| NGA-WS16-006 | P2 | M4 | WS16 | 文档与 runbook 同步收口 | NGA-WS16-005 |
| NGA-WS18-007 | P2 | M3 | WS18 | DNA 变更审计与审批流程 | NGA-WS18-006 |
| NGA-WS18-008 | P2 | M4 | WS18 | Brainstem 守护进程打包与托管 | NGA-WS18-004;NGA-WS18-006 |

## Sprint S5（L4）

- 目标：事务化提交与 detached 清理
- 任务数：9，其中 P0：2

| task_id | priority | phase | workstream | title | depends_on |
|---|---|---|---|---|---|
| NGA-WS13-004 | P0 | M2 | WS13 | Workspace Transaction 管理器 | NGA-WS13-003 |
| NGA-WS14-006 | P0 | M2 | WS14 | Double-Fork 幽灵进程清理 | NGA-WS14-005 |
| NGA-WS12-004 | P1 | M2 | WS12 | 冲突票据与退避机制 | NGA-WS12-003 |
| NGA-WS14-010 | P1 | M1 | WS14 | OOB 健康探测与恢复 runbook | NGA-WS14-009 |
| NGA-WS15-003 | P1 | M3 | WS15 | GC 注入策略改造 | NGA-WS15-002 |
| NGA-WS17-004 | P1 | M5 | WS17 | 混沌演练 锁泄漏与切主 | NGA-WS14-003;NGA-WS14-004 |
| NGA-WS17-005 | P1 | M5 | WS17 | 混沌演练 ReDoS 与 logrotate | NGA-WS14-007;NGA-WS14-008 |
| NGA-WS19-005 | P1 | M3 | WS19 | Episodic Memory 写入与检索链路 | NGA-WS15-002 |
| NGA-WS20-005 | P1 | M4 | WS20 | 前后端联调回归套件 | NGA-WS20-002;NGA-WS20-004 |

## Sprint S6（L5）

- 目标：迁移收口与发布前回归
- 任务数：10，其中 P0：0

| task_id | priority | phase | workstream | title | depends_on |
|---|---|---|---|---|---|
| NGA-WS12-005 | P1 | M2 | WS12 | Router 仲裁升级路径 | NGA-WS12-004 |
| NGA-WS12-006 | P1 | M2 | WS12 | 大文件与并发压测基线 | NGA-WS12-001;NGA-WS12-004 |
| NGA-WS13-005 | P1 | M2 | WS13 | clean_state 保证与恢复票据 | NGA-WS13-004 |
| NGA-WS15-004 | P1 | M3 | WS15 | GC 预算守门与回路防抖 | NGA-WS15-003 |
| NGA-WS15-005 | P1 | M3 | WS15 | 证据回读自动化链路 | NGA-WS11-002;NGA-WS15-003 |
| NGA-WS17-006 | P1 | M5 | WS17 | 混沌演练 double-fork 与磁盘压力 | NGA-WS14-006;NGA-WS11-004 |
| NGA-WS17-008 | P2 | M5 | WS17 | SLO 告警看板上线 | NGA-WS11-006;NGA-WS14-010 |
| NGA-WS19-006 | P2 | M3 | WS19 | 工具结果拓扑扫描与更新 | NGA-WS19-005 |
| NGA-WS19-007 | P2 | M4 | WS19 | Daily Checkpoint 日结归档 | NGA-WS19-004;NGA-WS19-005 |
| NGA-WS20-006 | P2 | M5 | WS20 | 桌面端发布兼容性验证 | NGA-WS20-005 |

## Sprint S7（L6）

- 目标：最终发布稳态验收
- 任务数：3，其中 P0：0

| task_id | priority | phase | workstream | title | depends_on |
|---|---|---|---|---|---|
| NGA-WS13-006 | P1 | M3 | WS13 | 跨文件事务回归与联调 | NGA-WS13-004;NGA-WS13-005 |
| NGA-WS19-008 | P1 | M3 | WS19 | Router 仲裁熔断联动 | NGA-WS19-002;NGA-WS12-005 |
| NGA-WS15-006 | P2 | M3 | WS15 | GC 质量评测与回归基线 | NGA-WS15-001;NGA-WS15-005 |

