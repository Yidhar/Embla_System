# 04 依赖驱动可并行任务组

规则：同一依赖层级（Lx）内任务可并行执行；跨层需等待前置层完成。

## 并行波次总览

| 并行组 | 依赖层级 | 任务数 | 说明 |
|---|---|---:|---|
| G1 | L0 | 3 | 根任务，可立即开工 |
| G2 | L1 | 12 | 依赖 L0 全量完成 |
| G3 | L2 | 20 | 依赖 L1 全量完成 |
| G4 | L3 | 19 | 依赖 L2 全量完成 |
| G5 | L4 | 9 | 依赖 L3 全量完成 |
| G6 | L5 | 10 | 依赖 L4 全量完成 |
| G7 | L6 | 3 | 依赖 L5 全量完成 |

## G1（L0）

- 并行执行建议：按工作流分 lane 并发执行。

### Lane WS10

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS10-001 | P0 | M0 | 统一 Tool Contract 字段模型 | - |

### Lane WS16

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS16-001 | P0 | M0 | 迁移资产清单与依赖盘点 | - |

### Lane WS17

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS17-001 | P0 | M1 | 测试基线只读隔离 | - |

## G2（L1）

- 并行执行建议：按工作流分 lane 并发执行。

### Lane WS10

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS10-002 | P0 | M0 | 注入调用上下文元数据 | NGA-WS10-001 |
| NGA-WS10-003 | P0 | M1 | 建立输入输出 schema 强校验 | NGA-WS10-001 |

### Lane WS11

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS11-001 | P0 | M1 | 建立 Artifact 元数据模型 | NGA-WS10-001 |

### Lane WS12

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS12-001 | P0 | M1 | 实现 file_ast_skeleton 分层读取 | NGA-WS10-001 |

### Lane WS13

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS13-001 | P0 | M2 | 设计 Contract Gate 契约模型 | NGA-WS10-001 |

### Lane WS16

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS16-002 | P1 | M4 | AgentServer 弃用路径设计 | NGA-WS16-001 |
| NGA-WS16-003 | P1 | M4 | MCP 状态占位接口收敛 | NGA-WS10-001 |
| NGA-WS16-004 | P1 | M4 | 配置迁移脚本与版本化 | NGA-WS16-001 |

### Lane WS17

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS17-002 | P0 | M1 | Anti-Test-Poisoning 检查器 | NGA-WS17-001 |
| NGA-WS17-003 | P1 | M2 | Clean Checkout 双轨验证 | NGA-WS17-001 |

### Lane WS18

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS18-001 | P1 | M2 | Event Bus 事件模型收敛 | NGA-WS10-001 |

### Lane WS20

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS20-001 | P1 | M1 | API 契约冻结与版本策略 | NGA-WS10-001 |

## G3（L2）

- 并行执行建议：按工作流分 lane 并发执行。

### Lane WS10

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS10-004 | P1 | M1 | 统一工具回执模板与审计记录 | NGA-WS10-002 |
| NGA-WS10-005 | P1 | M1 | 风险门禁与审批钩子收敛 | NGA-WS10-003 |
| NGA-WS10-006 | P1 | M2 | 兼容开关与灰度发布策略 | NGA-WS10-001;NGA-WS10-003 |

### Lane WS11

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS11-002 | P0 | M1 | 实现 artifact_reader 工具 | NGA-WS11-001 |
| NGA-WS11-004 | P0 | M1 | 实现 Artifact 配额与生命周期策略 | NGA-WS11-001 |

### Lane WS12

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS12-002 | P0 | M1 | 实现定向 chunk 读取 | NGA-WS12-001 |

### Lane WS13

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS13-002 | P0 | M2 | 并行前契约协商门禁 | NGA-WS13-001 |

### Lane WS14

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS14-001 | P0 | M1 | Policy Firewall 能力白名单校验 | NGA-WS10-003 |
| NGA-WS14-003 | P0 | M2 | Global Mutex TTL Heartbeat Fencing | NGA-WS10-002 |
| NGA-WS14-007 | P0 | M1 | Sleep Watch ReDoS 防护 | NGA-WS10-003 |

### Lane WS15

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS15-001 | P1 | M3 | 关键证据字段抽取器 | NGA-WS11-001 |

### Lane WS16

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS16-005 | P1 | M4 | 兼容双栈灰度与下线开关 | NGA-WS16-003;NGA-WS16-004 |

### Lane WS17

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS17-007 | P1 | M5 | Canary 与自动回滚收敛 | NGA-WS17-003 |

### Lane WS18

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS18-002 | P1 | M2 | Outbox Inbox 可靠投递整合 | NGA-WS18-001 |
| NGA-WS18-004 | P1 | M2 | Watchdog 资源监控器落地 | NGA-WS10-002 |
| NGA-WS18-006 | P1 | M2 | Immutable DNA 注入与校验 | NGA-WS10-003 |

### Lane WS19

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS19-001 | P1 | M3 | Meta-Agent 服务骨架落地 | NGA-WS18-001 |
| NGA-WS19-003 | P1 | M3 | LLM Gateway 分层路由与缓存 | NGA-WS10-003 |

### Lane WS20

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS20-003 | P2 | M3 | 前端模块按域解耦 | NGA-WS20-001 |
| NGA-WS20-004 | P1 | M4 | MCP 状态展示与真实后端对齐 | NGA-WS16-003 |

## G4（L3）

- 并行执行建议：按工作流分 lane 并发执行。

### Lane WS11

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS11-003 | P0 | M1 | os_bash 接入 fetch_hints | NGA-WS11-002 |
| NGA-WS11-005 | P1 | M2 | 高水位背压与关键路径保护 | NGA-WS11-004 |
| NGA-WS11-006 | P1 | M2 | 证据链可观测性 | NGA-WS11-002;NGA-WS11-004 |

### Lane WS12

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS12-003 | P1 | M2 | 语义重基 semantic_rebase | NGA-WS12-002 |

### Lane WS13

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS13-003 | P1 | M2 | Scaffold contract-aware 生成 | NGA-WS13-002 |

### Lane WS14

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS14-002 | P0 | M1 | 解释器入口硬门禁 | NGA-WS14-001 |
| NGA-WS14-004 | P1 | M2 | Orphan Lock 清道夫 | NGA-WS14-003 |
| NGA-WS14-005 | P0 | M2 | Process Lineage 绑定与回收 | NGA-WS14-003 |
| NGA-WS14-008 | P1 | M1 | Logrotate 容错 | NGA-WS14-007 |
| NGA-WS14-009 | P0 | M1 | KillSwitch OOB 出口策略 | NGA-WS14-001 |

### Lane WS15

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS15-002 | P1 | M3 | 叙事摘要与证据引用分离 | NGA-WS15-001 |

### Lane WS16

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS16-006 | P2 | M4 | 文档与 runbook 同步收口 | NGA-WS16-005 |

### Lane WS18

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS18-003 | P1 | M2 | Event Replay 与恢复路径 | NGA-WS18-002 |
| NGA-WS18-005 | P1 | M2 | Loop Detector 与成本熔断联动 | NGA-WS18-004 |
| NGA-WS18-007 | P2 | M3 | DNA 变更审计与审批流程 | NGA-WS18-006 |
| NGA-WS18-008 | P2 | M4 | Brainstem 守护进程打包与托管 | NGA-WS18-004;NGA-WS18-006 |

### Lane WS19

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS19-002 | P1 | M3 | Router 规则引擎与角色路由 | NGA-WS19-001 |
| NGA-WS19-004 | P1 | M3 | Working Memory 窗口管理器 | NGA-WS19-003 |

### Lane WS20

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS20-002 | P1 | M2 | SSE 事件协议统一 | NGA-WS10-004 |

## G5（L4）

- 并行执行建议：按工作流分 lane 并发执行。

### Lane WS12

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS12-004 | P1 | M2 | 冲突票据与退避机制 | NGA-WS12-003 |

### Lane WS13

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS13-004 | P0 | M2 | Workspace Transaction 管理器 | NGA-WS13-003 |

### Lane WS14

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS14-006 | P0 | M2 | Double-Fork 幽灵进程清理 | NGA-WS14-005 |
| NGA-WS14-010 | P1 | M1 | OOB 健康探测与恢复 runbook | NGA-WS14-009 |

### Lane WS15

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS15-003 | P1 | M3 | GC 注入策略改造 | NGA-WS15-002 |

### Lane WS17

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS17-004 | P1 | M5 | 混沌演练 锁泄漏与切主 | NGA-WS14-003;NGA-WS14-004 |
| NGA-WS17-005 | P1 | M5 | 混沌演练 ReDoS 与 logrotate | NGA-WS14-007;NGA-WS14-008 |

### Lane WS19

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS19-005 | P1 | M3 | Episodic Memory 写入与检索链路 | NGA-WS15-002 |

### Lane WS20

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS20-005 | P1 | M4 | 前后端联调回归套件 | NGA-WS20-002;NGA-WS20-004 |

## G6（L5）

- 并行执行建议：按工作流分 lane 并发执行。

### Lane WS12

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS12-005 | P1 | M2 | Router 仲裁升级路径 | NGA-WS12-004 |
| NGA-WS12-006 | P1 | M2 | 大文件与并发压测基线 | NGA-WS12-001;NGA-WS12-004 |

### Lane WS13

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS13-005 | P1 | M2 | clean_state 保证与恢复票据 | NGA-WS13-004 |

### Lane WS15

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS15-004 | P1 | M3 | GC 预算守门与回路防抖 | NGA-WS15-003 |
| NGA-WS15-005 | P1 | M3 | 证据回读自动化链路 | NGA-WS11-002;NGA-WS15-003 |

### Lane WS17

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS17-006 | P1 | M5 | 混沌演练 double-fork 与磁盘压力 | NGA-WS14-006;NGA-WS11-004 |
| NGA-WS17-008 | P2 | M5 | SLO 告警看板上线 | NGA-WS11-006;NGA-WS14-010 |

### Lane WS19

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS19-006 | P2 | M3 | Semantic Graph 拓扑扫描与更新 | NGA-WS19-005 |
| NGA-WS19-007 | P2 | M4 | Daily Checkpoint 日结归档 | NGA-WS19-004;NGA-WS19-005 |

### Lane WS20

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS20-006 | P2 | M5 | 桌面端发布兼容性验证 | NGA-WS20-005 |

## G7（L6）

- 并行执行建议：按工作流分 lane 并发执行。

### Lane WS13

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS13-006 | P1 | M3 | 跨文件事务回归与联调 | NGA-WS13-004;NGA-WS13-005 |

### Lane WS15

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS15-006 | P2 | M3 | GC 质量评测与回归基线 | NGA-WS15-001;NGA-WS15-005 |

### Lane WS19

| task_id | priority | phase | title | depends_on |
|---|---|---|---|---|
| NGA-WS19-008 | P1 | M3 | Router 仲裁熔断联动 | NGA-WS19-002;NGA-WS12-005 |

## 最大并行宽度

- 峰值并行层：L2（20 任务）
- 全 AI Agent 团队建议：峰值层按 lane 拆成多个执行池，统一由 Router 做冲突仲裁。
