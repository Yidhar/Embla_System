# WS19 Brain 核心能力（Meta / Router / Memory）

## 目标

补齐 Brain 目标态认知核心，使任务编排、模型路由与记忆系统形成可解释闭环。

## 任务拆解

### NGA-WS19-001 Meta-Agent 服务骨架落地
- type: feature
- priority: P1
- phase: M3
- owner_role: backend
- scope: meta-agent runtime
- inputs: `doc/11#1`
- depends_on: NGA-WS18-001
- deliverables: 任务拆解、反思、恢复入口
- acceptance: 典型任务可由 Meta-Agent 拆解分发
- rollback: 回退当前 system_agent 单链模式
- status: todo

### NGA-WS19-002 Router 规则引擎与角色路由
- type: feature
- priority: P1
- phase: M3
- owner_role: backend
- scope: router engine
- inputs: `doc/11#2`
- depends_on: NGA-WS19-001
- deliverables: 按任务类型/风险/预算路由角色与模型
- acceptance: 路由决策可解释且可重放
- rollback: 固定路由表兜底
- status: todo

### NGA-WS19-003 LLM Gateway 分层路由与缓存
- type: refactor
- priority: P1
- phase: M3
- owner_role: backend
- scope: llm client
- inputs: `doc/11#3.4`, `doc/09#10`
- depends_on: NGA-WS10-003
- deliverables: 主/次/本地模型分流 + 三段缓存策略
- acceptance: 成本与延迟指标达预期
- rollback: 单模型回退开关
- status: todo

### NGA-WS19-004 Working Memory 窗口管理器
- type: feature
- priority: P1
- phase: M3
- owner_role: backend
- scope: memory manager
- inputs: `doc/11#4.1`
- depends_on: NGA-WS19-003
- deliverables: 双阈值窗口管理与策略回调
- acceptance: token 峰值受控且不丢关键上下文
- rollback: 固定窗口策略
- status: todo

### NGA-WS19-005 Episodic Memory 写入与检索链路
- type: feature
- priority: P1
- phase: M3
- owner_role: backend
- scope: long-term memory
- inputs: `doc/11#4.2,#4.3`
- depends_on: NGA-WS15-002
- deliverables: 向量化归档、检索与回注
- acceptance: 历史经验可稳定召回
- rollback: 降级仅保留短期记忆
- status: todo

### NGA-WS19-006 Semantic Graph 拓扑扫描与更新
- type: feature
- priority: P2
- phase: M3
- owner_role: backend
- scope: semantic graph
- inputs: `doc/11#4.4,#4.5`
- depends_on: NGA-WS19-005
- deliverables: 拓扑节点/关系更新服务
- acceptance: 依赖链查询准确率达标
- rollback: 关闭图谱写入，仅保留检索
- status: todo

### NGA-WS19-007 Daily Checkpoint 日结归档
- type: ops
- priority: P2
- phase: M4
- owner_role: ops
- scope: checkpoint cron
- inputs: `doc/11#7`
- depends_on: NGA-WS19-004,NGA-WS19-005
- deliverables: 24h 总结与次日恢复卡片
- acceptance: 日结任务稳定执行并可审计
- rollback: 手工日结脚本兜底
- status: todo

### NGA-WS19-008 Router 仲裁熔断联动
- type: hardening
- priority: P1
- phase: M3
- owner_role: backend
- scope: router arbiter
- inputs: `doc/11#2.5`, `doc/09#11.3`
- depends_on: NGA-WS19-002,NGA-WS12-005
- deliverables: delegate 上限、冲突冻结、HITL 接管
- acceptance: 超限冲突不进入无限修复循环
- rollback: 人工仲裁强制接管
- status: todo
