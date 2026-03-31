# WS20 前后端边界与 BFF 迁移

文档状态：`archived_lane_ws20`  
状态对齐日期：`2026-02-27`

## 目标

按现有前后端边界文档推进接口收敛，降低兼容复杂度并提升联调效率。

## 任务拆解

### NGA-WS20-001 API 契约冻结与版本策略
- type: migration
- priority: P1
- phase: M1
- owner_role: backend
- scope: apiserver contracts
- inputs: `doc/04`, `doc/08`
- depends_on: NGA-WS10-001
- deliverables: API versioning + deprecation policy
- acceptance: 新旧接口兼容窗口明确
- rollback: 旧版本路由保留
- status: archived

### NGA-WS20-002 SSE 事件协议统一
- type: feature
- priority: P1
- phase: M2
- owner_role: backend
- scope: stream events
- inputs: `doc/01#4.1`, `doc/04`
- depends_on: NGA-WS10-004
- deliverables: `tool_calls/tool_results/round_*` 事件字段统一
- acceptance: 前端消费无需多分支适配
- rollback: SSE 兼容适配器
- status: archived

### NGA-WS20-003 前端模块按域解耦
- type: refactor
- priority: P2
- phase: M3
- owner_role: frontend
- scope: frontend/src modules
- inputs: `doc/08`
- depends_on: NGA-WS20-001
- deliverables: chat/tools/settings/ops 模块边界拆分
- acceptance: 模块依赖关系清晰且可独立测试
- rollback: 分支级回退
- status: archived

### NGA-WS20-004 MCP 状态展示与真实后端对齐
- type: migration
- priority: P1
- phase: M4
- owner_role: frontend
- scope: mcp status ui
- inputs: `doc/01#4.2`, `doc/16`
- depends_on: NGA-WS16-003
- deliverables: UI 状态来源切换到真实状态接口
- acceptance: UI 与后台状态一致率达标
- rollback: 回切占位展示
- status: archived

### NGA-WS20-005 前后端联调回归套件
- type: qa
- priority: P1
- phase: M4
- owner_role: qa
- scope: e2e integration
- inputs: `doc/05`, `doc/08`
- depends_on: NGA-WS20-002,NGA-WS20-004
- deliverables: 合同测试 + SSE 回归 + 错误场景回归
- acceptance: 核心链路回归全通过
- rollback: 发布前锁定版本
- status: archived

### NGA-WS20-006 桌面端发布兼容性验证
- type: qa
- priority: P2
- phase: M5
- owner_role: qa
- scope: electron release checks
- inputs: `doc/05`, `doc/08`
- depends_on: NGA-WS20-005
- deliverables: 不同配置与网络场景兼容报告
- acceptance: 关键平台可稳定运行
- rollback: 暂停升级并回退前一稳定包
- status: archived
