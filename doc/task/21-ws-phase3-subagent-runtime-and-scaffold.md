# WS21 Phase 3 - Sub-Agent Runtime + Scaffold Engine

## 目标

把 Phase 3 最核心的“多子代理协作执行链”从文档目标态推进到可运行代码，优先解决并行盲写与非原子散落风险。

## 任务拆解

### NGA-WS21-001 Scaffold Engine v1（已完成）
- type: feature
- priority: P0
- phase: M6
- owner_role: backend
- scope: `autonomous/scaffold_engine.py`
- inputs: `doc/12#8`, `doc/13#盲区5`
- deliverables:
  - contract gate + checksum 校验
  - 多文件事务写入与失败回滚收据
  - scaffold_fingerprint 追踪字段
- acceptance:
  - 校验失败时 fail-fast 且无文件污染
  - verify 失败时自动回滚并输出恢复票据
- status: done

### NGA-WS21-002 Sub-Agent Runtime v1（已完成）
- type: feature
- priority: P0
- phase: M6
- owner_role: backend
- scope: `autonomous/tools/subagent_runtime.py`
- inputs: `doc/12#8.2,#8.3,#8.4`
- deliverables:
  - 子任务依赖调度（dependency-aware）
  - role worker 分发与失败快停
  - 统一进入 ScaffoldEngine 原子提交
- acceptance:
  - 依赖顺序可验证
  - 未提供契约时并行写入被拦截
- status: done

### NGA-WS21-003 Runtime/Event Bus 事件联动
- type: hardening
- priority: P1
- phase: M6
- owner_role: backend
- scope: runtime telemetry
- inputs: `doc/10#1`, `doc/11#8`
- deliverables: goal/task/scaffold 生命周期事件上报与可回放 trace
- acceptance: 任一失败链路可用 trace_id 回放到任务级
- status: done

### NGA-WS21-004 Contract Negotiation 协商前置器
- type: hardening
- priority: P1
- phase: M6
- owner_role: backend
- scope: runtime preflight
- inputs: `doc/12#8.4`, `doc/13#盲区4`
- deliverables: Frontend/Backend 子任务在执行前交换字段契约并签名
- acceptance: 契约不一致在执行前中止，不进入编译/写入循环
- status: done

### NGA-WS21-005 Scaffold Verify Pipeline
- type: feature
- priority: P1
- phase: M6
- owner_role: qa
- scope: scaffold verify_fn
- inputs: `doc/09#11`, `doc/task/17-ws-quality-release-and-ops-readiness.md`
- deliverables: lint/test/smoke 可插拔校验链与失败分级策略
- acceptance: 任一 Gate 失败时自动回滚并生成诊断摘要
- status: done

### NGA-WS21-006 Runtime Chaos & Long-run Test
- type: qa
- priority: P1
- phase: M7
- owner_role: qa
- scope: tests + system tests
- inputs: `doc/10#2`, `doc/13`
- deliverables: 并发冲突、锁切换、杀进程恢复、日志轮转等混沌回归集
- acceptance: 关键链路 24h 回归无死锁/脏写/假死
- status: done

## 当前进度快照（2026-02-24）

- 已完成：6/6（NGA-WS21-001 ~ NGA-WS21-006）
- 进行中：无
- 下一优先级：进入 WS22（Phase 3 调度面整合与灰度接管）
