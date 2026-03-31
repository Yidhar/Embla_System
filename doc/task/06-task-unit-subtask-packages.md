# 06 任务单元再细分（标准子任务包 + 逐任务映射）

生成时间：2026-02-23  
输入基线：`doc/task/99-task-backlog.csv`（76 任务）

## 子任务包模板

| Package | 适用 type | 标准子任务拆解 | 最小产物 |
|---|---|---|---|
| `PKG-FEAT-5` | feature | 需求澄清 -> 接口定义 -> 实现 -> 测试 -> 文档 | 代码 + 单测 + 变更记录 |
| `PKG-HARD-6` | hardening | 威胁建模 -> 防护实现 -> 负向测试 -> 审计日志 -> 回滚路径 -> 压测 | 防护报告 + 负测通过 + 回滚演练 |
| `PKG-MIG-6` | migration | 资产盘点 -> 迁移脚本 -> 双栈灰度 -> 兼容验证 -> 回退演练 -> 下线收口 | 迁移日志 + 回退记录 + 兼容报告 |
| `PKG-QA-5` | qa | 场景建模 -> 基线准备 -> 执行 -> 缺陷收敛 -> 报告与门禁 | 测试报告 + gate 结果 |
| `PKG-OPS-5` | ops | 指标定义 -> 告警规则 -> Runbook -> 演练 -> 值班交接 | 仪表板 + 告警 + runbook |
| `PKG-REF-5` | refactor | 现状基线 -> 重构 -> 行为对齐 -> 性能回归 -> 文档更新 | 重构 diff + 回归报告 |

## 逐任务映射（76）

| task_id | sprint | priority | type | package | pool | 子任务数 | 最小验收锚点 |
|---|---|---|---|---|---|---:|---|
| NGA-WS10-001 | S1 | P0 | refactor | `PKG-REF-5` | POOL-01 Contract-Gateway | 5 | native/mcp 回执字段一致 |
| NGA-WS16-001 | S1 | P0 | migration | `PKG-MIG-6` | POOL-07 Migration-Compat | 6 | 核心调用链覆盖盘点 |
| NGA-WS17-001 | S1 | P0 | qa | `PKG-QA-5` | POOL-08 QA-Release | 5 | golden suite 只读可执行 |
| NGA-WS10-002 | S2 | P0 | feature | `PKG-FEAT-5` | POOL-01 Contract-Gateway | 5 | trace/risk/scope 全链路可追溯 |
| NGA-WS10-003 | S2 | P0 | hardening | `PKG-HARD-6` | POOL-01 Contract-Gateway | 6 | 非法调用网关拦截并审计 |
| NGA-WS11-001 | S2 | P0 | feature | `PKG-FEAT-5` | POOL-02 Artifact-Evidence | 5 | 每个 ref 可查询元数据 |
| NGA-WS12-001 | S2 | P0 | feature | `PKG-FEAT-5` | POOL-03 AST-Concurrency | 5 | 大文件默认不全量回读 |
| NGA-WS13-001 | S2 | P0 | feature | `PKG-FEAT-5` | POOL-04 SubAgent-Scaffold | 5 | contract_id+checksum 生效 |
| NGA-WS16-002 | S2 | P1 | migration | `PKG-MIG-6` | POOL-07 Migration-Compat | 6 | 不新增 agentserver 依赖 |
| NGA-WS16-003 | S2 | P1 | migration | `PKG-MIG-6` | POOL-07 Migration-Compat | 6 | 前端状态与真实状态一致 |
| NGA-WS16-004 | S2 | P1 | migration | `PKG-MIG-6` | POOL-07 Migration-Compat | 6 | 旧配置可无损升级 |
| NGA-WS17-002 | S2 | P0 | hardening | `PKG-HARD-6` | POOL-08 QA-Release | 6 | 毒化样例可拦截 |
| NGA-WS17-003 | S2 | P1 | qa | `PKG-QA-5` | POOL-08 QA-Release | 5 | 双轨一致才可合并 |
| NGA-WS18-001 | S2 | P1 | feature | `PKG-FEAT-5` | POOL-09 Brainstem-Core | 5 | 关键事件可统一消费重放 |
| NGA-WS20-001 | S2 | P1 | migration | `PKG-MIG-6` | POOL-11 Frontend-BFF | 6 | 兼容窗口明确 |
| NGA-WS10-004 | S3 | P1 | feature | `PKG-FEAT-5` | POOL-01 Contract-Gateway | 5 | 关键工具回执模板全覆盖 |
| NGA-WS10-005 | S3 | P1 | hardening | `PKG-HARD-6` | POOL-01 Contract-Gateway | 6 | 高风险动作按策略阻断/审批 |
| NGA-WS10-006 | S3 | P1 | migration | `PKG-MIG-6` | POOL-01 Contract-Gateway | 6 | 新旧 contract 双栈灰度可回退 |
| NGA-WS11-002 | S3 | P0 | feature | `PKG-FEAT-5` | POOL-02 Artifact-Evidence | 5 | ref 可按模式二次读取 |
| NGA-WS11-004 | S3 | P0 | hardening | `PKG-HARD-6` | POOL-02 Artifact-Evidence | 6 | 72h 压测无 ENOSPC 雪崩 |
| NGA-WS12-002 | S3 | P0 | feature | `PKG-FEAT-5` | POOL-03 AST-Concurrency | 5 | 编辑只拉目标区域 |
| NGA-WS13-002 | S3 | P0 | hardening | `PKG-HARD-6` | POOL-04 SubAgent-Scaffold | 6 | 契约不一致 fail-fast |
| NGA-WS14-001 | S3 | P0 | hardening | `PKG-HARD-6` | POOL-05 Security-Runtime | 6 | 混淆命令被拦截 |
| NGA-WS14-003 | S3 | P0 | hardening | `PKG-HARD-6` | POOL-05 Security-Runtime | 6 | kill-9 注入后锁自动回收 |
| NGA-WS14-007 | S3 | P0 | hardening | `PKG-HARD-6` | POOL-05 Security-Runtime | 6 | 灾难正则不拖垮宿主 |
| NGA-WS15-001 | S3 | P1 | feature | `PKG-FEAT-5` | POOL-06 Memory-GC | 5 | 关键字段召回可测 |
| NGA-WS16-005 | S3 | P1 | ops | `PKG-OPS-5` | POOL-07 Migration-Compat | 5 | 灰度可回退 |
| NGA-WS17-007 | S3 | P1 | ops | `PKG-OPS-5` | POOL-08 QA-Release | 5 | canary 异常自动回滚 |
| NGA-WS18-002 | S3 | P1 | hardening | `PKG-HARD-6` | POOL-09 Brainstem-Core | 6 | 事件不丢不重 |
| NGA-WS18-004 | S3 | P1 | feature | `PKG-FEAT-5` | POOL-09 Brainstem-Core | 5 | 超阈值可告警干预 |
| NGA-WS18-006 | S3 | P1 | hardening | `PKG-HARD-6` | POOL-09 Brainstem-Core | 6 | 非授权变更被拒绝 |
| NGA-WS19-001 | S3 | P1 | feature | `PKG-FEAT-5` | POOL-10 Brain-Core | 5 | 任务可拆解分发 |
| NGA-WS19-003 | S3 | P1 | refactor | `PKG-REF-5` | POOL-10 Brain-Core | 5 | 成本与时延指标达标 |
| NGA-WS20-003 | S3 | P2 | refactor | `PKG-REF-5` | POOL-11 Frontend-BFF | 5 | 模块边界清晰可测 |
| NGA-WS20-004 | S3 | P1 | migration | `PKG-MIG-6` | POOL-11 Frontend-BFF | 6 | UI 与后台状态一致 |
| NGA-WS11-003 | S4 | P0 | feature | `PKG-FEAT-5` | POOL-02 Artifact-Evidence | 5 | 超大结构化输出带检索提示 |
| NGA-WS11-005 | S4 | P1 | hardening | `PKG-HARD-6` | POOL-02 Artifact-Evidence | 6 | 高水位下核心数据库可写 |
| NGA-WS11-006 | S4 | P1 | ops | `PKG-OPS-5` | POOL-02 Artifact-Evidence | 5 | ref 命中率与回收统计可视化 |
| NGA-WS12-003 | S4 | P1 | hardening | `PKG-HARD-6` | POOL-03 AST-Concurrency | 6 | 轻度冲突可自动重基 |
| NGA-WS13-003 | S4 | P1 | feature | `PKG-FEAT-5` | POOL-04 SubAgent-Scaffold | 5 | 补丁绑定 contract_id |
| NGA-WS14-002 | S4 | P0 | hardening | `PKG-HARD-6` | POOL-05 Security-Runtime | 6 | python/sh encoded 入口阻断 |
| NGA-WS14-004 | S4 | P1 | hardening | `PKG-HARD-6` | POOL-05 Security-Runtime | 6 | 无永久悬挂锁 |
| NGA-WS14-005 | S4 | P0 | hardening | `PKG-HARD-6` | POOL-05 Security-Runtime | 6 | 按 lineage 递归清理 |
| NGA-WS14-008 | S4 | P1 | hardening | `PKG-HARD-6` | POOL-05 Security-Runtime | 6 | rotate 后可唤醒 |
| NGA-WS14-009 | S4 | P0 | hardening | `PKG-HARD-6` | POOL-05 Security-Runtime | 6 | 熔断时 OOB 通道可用 |
| NGA-WS15-002 | S4 | P1 | feature | `PKG-FEAT-5` | POOL-06 Memory-GC | 5 | 摘要不改写原证据 |
| NGA-WS16-006 | S4 | P2 | migration | `PKG-MIG-6` | POOL-07 Migration-Compat | 6 | 迁移后口径一致 |
| NGA-WS18-003 | S4 | P1 | ops | `PKG-OPS-5` | POOL-09 Brainstem-Core | 5 | 可按 trace 重放恢复 |
| NGA-WS18-005 | S4 | P1 | hardening | `PKG-HARD-6` | POOL-09 Brainstem-Core | 6 | 死循环场景自动中断 |
| NGA-WS18-007 | S4 | P2 | ops | `PKG-OPS-5` | POOL-09 Brainstem-Core | 5 | 变更责任可追溯 |
| NGA-WS18-008 | S4 | P2 | ops | `PKG-OPS-5` | POOL-09 Brainstem-Core | 5 | 异常退出可自恢复 |
| NGA-WS19-002 | S4 | P1 | feature | `PKG-FEAT-5` | POOL-10 Brain-Core | 5 | 路由决策可解释可回放 |
| NGA-WS19-004 | S4 | P1 | feature | `PKG-FEAT-5` | POOL-10 Brain-Core | 5 | token 峰值受控 |
| NGA-WS20-002 | S4 | P1 | feature | `PKG-FEAT-5` | POOL-11 Frontend-BFF | 5 | 前端消费无需多分支 |
| NGA-WS12-004 | S5 | P1 | hardening | `PKG-HARD-6` | POOL-03 AST-Concurrency | 6 | 无无界重试活锁 |
| NGA-WS13-004 | S5 | P0 | hardening | `PKG-HARD-6` | POOL-04 SubAgent-Scaffold | 6 | 多文件提交原子化 |
| NGA-WS14-006 | S5 | P0 | hardening | `PKG-HARD-6` | POOL-05 Security-Runtime | 6 | 切主后无幽灵写入 |
| NGA-WS14-010 | S5 | P1 | ops | `PKG-OPS-5` | POOL-05 Security-Runtime | 5 | OOB 可完成 disarm/recover |
| NGA-WS15-003 | S5 | P1 | refactor | `PKG-REF-5` | POOL-06 Memory-GC | 5 | 注入索引卡片+ref |
| NGA-WS17-004 | S5 | P1 | qa | `PKG-QA-5` | POOL-08 QA-Release | 5 | TTL 回收验证通过 |
| NGA-WS17-005 | S5 | P1 | qa | `PKG-QA-5` | POOL-08 QA-Release | 5 | 不假死不打爆 CPU |
| NGA-WS19-005 | S5 | P1 | feature | `PKG-FEAT-5` | POOL-10 Brain-Core | 5 | 历史经验稳定召回 |
| NGA-WS20-005 | S5 | P1 | qa | `PKG-QA-5` | POOL-11 Frontend-BFF | 5 | 核心链路回归全通过 |
| NGA-WS12-005 | S6 | P1 | feature | `PKG-FEAT-5` | POOL-03 AST-Concurrency | 5 | 冲突超限自动升级仲裁 |
| NGA-WS12-006 | S6 | P1 | qa | `PKG-QA-5` | POOL-03 AST-Concurrency | 5 | 30k 行与并发冲突指标达标 |
| NGA-WS13-005 | S6 | P1 | hardening | `PKG-HARD-6` | POOL-04 SubAgent-Scaffold | 6 | 失败后 clean_state=true |
| NGA-WS15-004 | S6 | P1 | hardening | `PKG-HARD-6` | POOL-06 Memory-GC | 6 | 避免误判重试循环 |
| NGA-WS15-005 | S6 | P1 | feature | `PKG-FEAT-5` | POOL-06 Memory-GC | 5 | 中段根因可自动定位 |
| NGA-WS17-006 | S6 | P1 | qa | `PKG-QA-5` | POOL-08 QA-Release | 5 | 幽灵回收且数据库不损坏 |
| NGA-WS17-008 | S6 | P2 | ops | `PKG-OPS-5` | POOL-08 QA-Release | 5 | 值班告警链路完整 |
| NGA-WS19-006 | S6 | P2 | feature | `PKG-FEAT-5` | POOL-10 Brain-Core | 5 | 依赖链查询准确 |
| NGA-WS19-007 | S6 | P2 | ops | `PKG-OPS-5` | POOL-10 Brain-Core | 5 | 日结稳定可审计 |
| NGA-WS20-006 | S6 | P2 | qa | `PKG-QA-5` | POOL-11 Frontend-BFF | 5 | 关键平台稳定运行 |
| NGA-WS13-006 | S7 | P1 | qa | `PKG-QA-5` | POOL-04 SubAgent-Scaffold | 5 | 事务失败自动回滚通过 |
| NGA-WS15-006 | S7 | P2 | qa | `PKG-QA-5` | POOL-06 Memory-GC | 5 | 召回误删时延指标达标 |
| NGA-WS19-008 | S7 | P1 | hardening | `PKG-HARD-6` | POOL-10 Brain-Core | 6 | 超限冲突不无限循环 |

## 执行约束

1. `P0` 任务不限制包类型，但必须额外附加“负向测试 + 回滚演练”两个子任务。
2. 所有 `migration` 任务必须包含“灰度 + 回退”两条证据。
3. 所有 `qa/ops` 任务必须落仪表板或 runbook 链接。

