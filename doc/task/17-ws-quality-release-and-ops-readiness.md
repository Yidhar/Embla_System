# WS17 质量、发布与运维就绪

## 目标

建立“可发布、可回滚、可演练”的交付闭环，防止测试毒化与高风险回归。

## 任务拆解

### NGA-WS17-001 测试基线只读隔离
- type: qa
- priority: P0
- phase: M1
- owner_role: qa
- scope: test directory governance
- inputs: `doc/13#R5`
- depends_on: -
- deliverables: golden suite 只读保护策略
- acceptance: 被测任务无法直接改写裁判测试
- rollback: 人工审批白名单改写通道
- status: done

### NGA-WS17-002 Anti-Test-Poisoning 检查器
- type: hardening
- priority: P0
- phase: M1
- owner_role: qa
- scope: CI guards
- inputs: `doc/13#R5`
- depends_on: NGA-WS17-001
- deliverables: “assert 弱化/恒真断言”检测规则
- acceptance: 测试毒化样例可稳定拦截
- rollback: 规则降级为告警并人工审阅
- status: review

### NGA-WS17-003 Clean Checkout 双轨验证
- type: qa
- priority: P1
- phase: M2
- owner_role: qa
- scope: CI pipeline
- inputs: `doc/13#R5`
- depends_on: NGA-WS17-001
- deliverables: workspace run + clean checkout run
- acceptance: 双轨结果一致方可合并
- rollback: 失败自动阻断合并
- status: done

### NGA-WS17-004 混沌演练：锁泄漏与切主
- type: qa
- priority: P1
- phase: M5
- owner_role: qa
- scope: chaos suite
- inputs: `doc/13#R3`
- depends_on: NGA-WS14-003,NGA-WS14-004
- deliverables: kill -9 注入与恢复脚本
- acceptance: 锁在 TTL 内回收，系统持续可用
- rollback: 回退单实例模式
- status: done

### NGA-WS17-005 混沌演练：ReDoS 与 logrotate
- type: qa
- priority: P1
- phase: M5
- owner_role: qa
- scope: sleep watch chaos
- inputs: `doc/13#R6`
- depends_on: NGA-WS14-007,NGA-WS14-008
- deliverables: regex 压力 + logrotate 场景脚本
- acceptance: 不假死、不打爆 CPU
- rollback: 降级为预定义规则监听
- status: done

### NGA-WS17-006 混沌演练：double-fork 与磁盘压力
- type: qa
- priority: P1
- phase: M5
- owner_role: qa
- scope: runtime + storage chaos
- inputs: `doc/13#R15,R16`
- depends_on: NGA-WS14-006,NGA-WS11-004
- deliverables: detached 进程与 ENOSPC 场景回归
- acceptance: 旧进程可回收，核心数据库不损坏
- rollback: 开启保守限流策略
- status: done

### NGA-WS17-007 Canary 与自动回滚收敛
- type: ops
- priority: P1
- phase: M5
- owner_role: ops
- scope: release controller
- inputs: `doc/07#2.5`
- depends_on: NGA-WS17-003
- deliverables: canary 阈值、回滚策略、演练记录
- acceptance: canary 异常可自动回滚
- rollback: 手工回滚 runbook
- status: done

### NGA-WS17-008 SLO/告警看板上线
- type: ops
- priority: P2
- phase: M5
- owner_role: ops
- scope: observability
- inputs: `doc/10`, `doc/11`, `doc/12`
- depends_on: NGA-WS11-006,NGA-WS14-010
- deliverables: 错误率/延迟/队列深度/磁盘水位/锁状态面板
- acceptance: 告警阈值与值班流程联动
- rollback: 保留旧监控入口
- status: done
