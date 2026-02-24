# WS13 Sub-Agent 契约门禁与脚手架事务化

## 目标

消除并行盲写与跨文件半写损坏态，建立可回退、可验证的多代理协作执行链。

## 任务拆解

### NGA-WS13-001 设计 Contract Gate 契约模型
- type: feature
- priority: P0
- phase: M2
- owner_role: backend
- scope: sub-agent runtime
- inputs: `doc/12#8.3,#8.4`, `doc/13#R12`
- depends_on: NGA-WS10-001
- deliverables: `contract_id + checksum + schema` 协议
- acceptance: FE/BE 都能读取同一契约上下文
- rollback: 不一致时 fail-fast 阻断
- status: todo

### NGA-WS13-002 并行分析前契约协商门禁
- type: hardening
- priority: P0
- phase: M2
- owner_role: backend
- scope: runtime flow control
- inputs: `doc/12#8.3`
- depends_on: NGA-WS13-001
- deliverables: 未达成契约不进入并行 analyze
- acceptance: 契约错配在 scaffold 前被拦截
- rollback: 降级为串行模式
- status: todo

### NGA-WS13-003 Scaffold contract-aware 生成
- type: feature
- priority: P1
- phase: M2
- owner_role: backend
- scope: scaffold engine
- inputs: `doc/12#8.3`
- depends_on: NGA-WS13-002
- deliverables: build_scaffold 强制绑定 contract_id
- acceptance: 生成补丁携带契约指纹
- rollback: 回退至模板最小集
- status: todo

### NGA-WS13-004 Workspace Transaction 管理器
- type: hardening
- priority: P0
- phase: M2
- owner_role: backend
- scope: execution bridge
- inputs: `doc/12#8.3,#8.4`, `doc/13#R13`
- depends_on: NGA-WS13-003
- deliverables: `begin/apply_all/verify/commit/rollback`
- acceptance: 任一文件失败触发全量回滚
- rollback: 强制只读预演模式
- status: todo

### NGA-WS13-005 clean_state 保证与恢复票据
- type: hardening
- priority: P1
- phase: M2
- owner_role: backend
- scope: rollback diagnostics
- inputs: `doc/12#8.4`
- depends_on: NGA-WS13-004
- deliverables: `clean_state=true` 回执与恢复 ticket
- acceptance: 失败后工作区可直接重试
- rollback: 快照回滚兜底
- status: todo

### NGA-WS13-006 跨文件事务回归与联调用例
- type: qa
- priority: P1
- phase: M3
- owner_role: qa
- scope: e2e tests
- inputs: `doc/13#R12,R13`
- depends_on: NGA-WS13-004,NGA-WS13-005
- deliverables: FE/BE 合同一致性 + 事务失败恢复测试
- acceptance: 关键场景回归全通过
- rollback: 暂时禁用自动并行，改人工串行
- status: todo
