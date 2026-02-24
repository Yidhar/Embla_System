# WS10 Tool Contract 与 I/O 统一封装

## 目标

把 Native 与 MCP 两条执行链统一到同一 Tool Contract，避免字段漂移、审计缺失和行为不一致。

## 任务拆解

### NGA-WS10-001 统一 Tool Contract 字段模型
- type: refactor
- priority: P0
- phase: M0
- owner_role: backend
- scope: `apiserver/agentic_tool_loop.py`, `apiserver/native_tools.py`, `mcpserver/*`
- inputs: `doc/09`, `doc/12`
- depends_on: -
- deliverables: 统一的请求/回执字段定义（含 trace/risk/scope/hash/ref）
- acceptance: native_call 与 mcp_call 返回字段一致性检查通过
- rollback: 保留旧字段兼容映射开关
- status: todo

### NGA-WS10-002 注入调用上下文元数据
- type: feature
- priority: P0
- phase: M0
- owner_role: backend
- scope: 调用入口与 tool dispatcher
- inputs: `doc/09#4`, `doc/12#1.4`
- depends_on: NGA-WS10-001
- deliverables: `call_id/trace_id/session_id/fencing_epoch/risk_level` 注入
- acceptance: 任意工具调用日志可回溯完整上下文
- rollback: 仅记录不强校验模式
- status: todo

### NGA-WS10-003 建立输入/输出 schema 强校验
- type: hardening
- priority: P0
- phase: M1
- owner_role: backend
- scope: schema validator 与错误分级
- inputs: `doc/09`, `doc/10`
- depends_on: NGA-WS10-001
- deliverables: schema 校验器、错误码、拒绝策略
- acceptance: 非法参数/输出在网关层被拒绝并审计
- rollback: 校验失败降级为告警模式（仅短期）
- status: todo

### NGA-WS10-004 统一工具回执模板与审计记录
- type: feature
- priority: P1
- phase: M1
- owner_role: backend
- scope: tool receipt, event log
- inputs: `doc/09#8`
- depends_on: NGA-WS10-002
- deliverables: 标准化回执（风险、预算、结果、后续建议）
- acceptance: 回执模板在关键工具链全覆盖
- rollback: 回执字段兼容旧版本解析
- status: todo

### NGA-WS10-005 风险门禁与审批钩子收敛
- type: hardening
- priority: P1
- phase: M1
- owner_role: security
- scope: risk gate, approval hook
- inputs: `doc/10`, `doc/13`
- depends_on: NGA-WS10-003
- deliverables: 风险等级到门禁策略映射
- acceptance: write/deploy/secrets 类调用按策略阻断或审批
- rollback: 仅降级为人工审批兜底
- status: todo

### NGA-WS10-006 兼容开关与灰度发布策略
- type: migration
- priority: P1
- phase: M2
- owner_role: ops
- scope: feature flags, staged rollout
- inputs: `doc/07`, `doc/09`
- depends_on: NGA-WS10-001,NGA-WS10-003
- deliverables: 新旧 contract 双栈灰度开关
- acceptance: 灰度期间无大规模调用失败回归
- rollback: 一键切回旧 contract
- status: todo
