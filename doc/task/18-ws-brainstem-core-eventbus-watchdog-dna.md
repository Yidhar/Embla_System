# WS18 Brainstem 核心能力（Event Bus / Watchdog / Immutable DNA）

## 目标

补齐 Brainstem 目标态核心守护能力，使控制面具备可靠事件驱动、资源干预与不可变策略约束。

## 任务拆解

### NGA-WS18-001 Event Bus 事件模型收敛
- type: feature
- priority: P1
- phase: M2
- owner_role: backend
- scope: event schema
- inputs: `doc/10#1`
- depends_on: NGA-WS10-001
- deliverables: 统一事件类型、负载 schema、版本字段
- acceptance: 关键事件可被统一消费与重放
- rollback: 保留旧事件适配层
- status: done

### NGA-WS18-002 Outbox/Inbox 可靠投递整合
- type: hardening
- priority: P1
- phase: M2
- owner_role: backend
- scope: workflow store + event bus
- inputs: `doc/07#2.4`, `doc/10#1.3`
- depends_on: NGA-WS18-001
- deliverables: 幂等投递、重试补偿、去重逻辑
- acceptance: 注入故障后事件不丢不重
- rollback: 手工重放脚本
- status: done

### NGA-WS18-003 Event Replay 与恢复路径
- type: ops
- priority: P1
- phase: M2
- owner_role: ops
- scope: replay tooling
- inputs: `doc/10#1.3`
- depends_on: NGA-WS18-002
- deliverables: 指定窗口重放工具与审计记录
- acceptance: 恢复场景可按 trace 复现链路
- rollback: 只读回放模式
- status: done

### NGA-WS18-004 Watchdog 资源监控器落地
- type: feature
- priority: P1
- phase: M2
- owner_role: infra
- scope: watchdog daemon
- inputs: `doc/10#2`
- depends_on: NGA-WS10-002
- deliverables: CPU/RAM/IO/成本采集与阈值配置
- acceptance: 超阈值告警与干预动作可触发
- rollback: 降级为仅告警
- status: done

### NGA-WS18-005 Loop Detector 与成本熔断联动
- type: hardening
- priority: P1
- phase: M2
- owner_role: backend
- scope: loop/cost guard
- inputs: `doc/10#2`, `doc/09#10`
- depends_on: NGA-WS18-004
- deliverables: 连续失败检测与任务熔断
- acceptance: 死循环场景被自动中断
- rollback: 手动仲裁兜底
- status: done

### NGA-WS18-006 Immutable DNA 注入与校验
- type: hardening
- priority: P1
- phase: M2
- owner_role: security
- scope: dna loader/injector
- inputs: `doc/10#3`
- depends_on: NGA-WS10-003
- deliverables: DNA hash 校验、注入顺序固定化
- acceptance: 非授权变更被拒绝并审计
- rollback: 回退到最后已签名版本
- status: done

### NGA-WS18-007 DNA 变更审计与审批流程
- type: ops
- priority: P2
- phase: M3
- owner_role: security
- scope: audit + approval
- inputs: `doc/10#3.4`
- depends_on: NGA-WS18-006
- deliverables: 变更审批记录与追踪报表
- acceptance: DNA 变更可追溯到责任人和工单
- rollback: 冻结 DNA 写入窗口
- status: done

### NGA-WS18-008 Brainstem 守护进程打包与托管
- type: ops
- priority: P2
- phase: M4
- owner_role: infra
- scope: deployment/service supervision
- inputs: `doc/10`, `doc/05`
- depends_on: NGA-WS18-004,NGA-WS18-006
- deliverables: 守护进程部署模板与自恢复策略
- acceptance: 异常退出可自动拉起并保留状态
- rollback: 回退现有轻量运行模式
- status: done
