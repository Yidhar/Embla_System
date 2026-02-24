# WS16 迁移收敛与兼容清理

## 目标

在保证线上可运行的前提下，完成过渡态收敛与弃用清理，避免长期双轨成本。

## 任务拆解

### NGA-WS16-001 迁移资产清单与依赖盘点
- type: migration
- priority: P0
- phase: M0
- owner_role: backend
- scope: modules/endpoints/configs
- inputs: `doc/01`, `doc/07`
- depends_on: -
- deliverables: 迁移清单（调用方、频率、风险等级）
- acceptance: 清单覆盖核心服务与工具链
- rollback: 无（分析任务）
- status: todo

### NGA-WS16-002 AgentServer 弃用路径 Phase 2 设计
- type: migration
- priority: P1
- phase: M4
- owner_role: backend
- scope: `agentserver/` deprecation
- inputs: `doc/01#6`
- depends_on: NGA-WS16-001
- deliverables: 删除顺序、替代链路、回退策略
- acceptance: 不新增对 agentserver 的新依赖
- rollback: 兼容开关保留一版周期
- status: todo

### NGA-WS16-003 MCP 状态占位接口收敛
- type: migration
- priority: P1
- phase: M4
- owner_role: backend
- scope: `/mcp/status` 等接口语义一致性
- inputs: `doc/01#4.2`
- depends_on: NGA-WS10-001
- deliverables: 占位接口替换为真实状态或明确弃用
- acceptance: 前端展示与真实状态一致
- rollback: 前端降级显示兼容文案
- status: todo

### NGA-WS16-004 配置迁移脚本与版本化
- type: migration
- priority: P1
- phase: M4
- owner_role: ops
- scope: config schema upgrade
- inputs: `doc/05`, `doc/07`
- depends_on: NGA-WS16-001
- deliverables: config migration script + version marker
- acceptance: 旧配置可无损升级
- rollback: 自动备份并支持一键恢复
- status: todo

### NGA-WS16-005 兼容双栈灰度与下线开关
- type: ops
- priority: P1
- phase: M4
- owner_role: ops
- scope: rollout flags
- inputs: `doc/07`, `doc/09`
- depends_on: NGA-WS16-003,NGA-WS16-004
- deliverables: dual-stack flags + 下线门禁
- acceptance: 灰度过程可观测、可回退
- rollback: 回切旧栈 SLA 内完成
- status: todo

### NGA-WS16-006 文档与Runbook 同步收口
- type: migration
- priority: P2
- phase: M4
- owner_role: docs
- scope: docs/runbooks
- inputs: 全 doc 目录
- depends_on: NGA-WS16-005
- deliverables: 迁移后文档一致性修订
- acceptance: 无冲突口径与失效路径
- rollback: 变更记录可追溯
- status: todo
