# WS22 Phase 3 - Scheduler Bridge & Gradual Takeover


> Migration Note (archived/legacy)
> 文中 `autonomous/*` 路径属于历史实现标识；当前实现请优先使用 `agents/*`、`core/*` 与 `config/autonomous_runtime.yaml`。

## 目标

把 `Sub-Agent Runtime` 从“可独立运行”推进到“SystemAgent 主链可灰度接管”，并保证租约、事件与回滚语义不退化。

## 任务拆解

### NGA-WS22-001 SystemAgent 调度桥接（已完成）
- type: feature
- priority: P0
- phase: M7
- owner_role: backend
- scope: `agents/pipeline.py`
- inputs: `doc/11#1,#2`, `doc/12#8`
- deliverables:
  - `SystemAgent` 可切换为 `Sub-Agent Runtime` 驱动的子任务执行模式
  - 保留 legacy 执行路径与 `fail_open` 降级
  - 子任务执行结果回写父任务 `TaskApproved/TaskRejected`
- acceptance:
  - 开启开关后可稳定完成一轮任务并进入 `ReleaseCandidate`
  - `fail_open` 时能自动退回 legacy 路径且不丢主事件
- status: done

### NGA-WS22-002 子任务元数据与事件同步（已完成）
- type: hardening
- priority: P0
- phase: M7
- owner_role: backend
- scope: `agents/pipeline.py`, `agents/runtime/mini_loop.py`
- inputs: `doc/10#1`, `doc/11#8`
- deliverables:
  - 子任务事件链：`SubTaskDispatching/SubTaskExecutionCompleted/SubTaskApproved/SubTaskRejected`
  - Runtime 事件携带 `workflow_id/trace_id/session_id`
  - 父任务事件中回写 `subagent_runtime_id` 与失败子任务摘要
- acceptance:
  - 可按 `trace_id + workflow_id` 回放到子任务级别
  - 父子任务事件可关联且无跳号
- status: done

### NGA-WS22-003 Scaffold/Contract 桥接到发布门禁
- type: hardening
- priority: P1
- phase: M7
- owner_role: backend
- scope: `agents/pipeline.py`, `autonomous/scaffold_engine.py`（archived/legacy）
- inputs: `doc/12#8.4`, `doc/09#11`
- deliverables:
  - 当 `scaffold_result/negotiation_result` 失败时，统一映射到发布门禁拒绝路径
  - 增加 contract/scaffold 指标埋点（失败率、冲突票据、回滚率）
- acceptance:
  - Contract/Scaffold 失败不再“静默失败”，必须进入可审计拒绝链路
- status: done

### NGA-WS22-004 调度层混沌与 Lease 守护
- type: qa
- priority: P1
- phase: M7
- owner_role: qa
- scope: `tests`
- inputs: `doc/10#2`, `doc/11#6`
- deliverables:
  - 子任务链路的 lease 丢失、fail_open、重试预算、事件重放混沌回归
  - 关键长任务场景（>10min）稳定性基线
- acceptance:
  - 关键场景下无未捕获异常、无状态污染、无事件丢失
- status: done
- progress:
  - 已覆盖：lease 丢失 + fail_open、无 fail_open 显式失败、max_subtasks 上限、dispatch 后 lease 丢失恢复路径、40 分片压力下的子任务上限守门
  - 已补齐：`NGA-WS22-004` 长稳等效基线（`virtual_elapsed_seconds=600`）与统计报告落盘
  - 已补齐：Sub-Agent 子任务规范校验（重复 `subtask_id`、坏依赖、自依赖、空指令）并进入 `runtime` 拒绝链路
  - 已补齐：`rollout_percent(0-100)` 灰度接管决策与任务级 `runtime_mode` 强制覆盖（支持渐进接管）
  - 报告位置：`scratch/reports/ws22_scheduler_longrun_baseline.json`
  - 实施记录：`doc/task/implementation/NGA-WS22-004-implementation.md`

## 当前进度快照（2026-02-24）

- 已完成：4/4（NGA-WS22-001, NGA-WS22-002, NGA-WS22-003, NGA-WS22-004）
- 口径说明：上述 `4/4` 仅覆盖本文件主任务；`NGA-WS22-005/006` 为后续扩展补齐项，实施记录见 `doc/task/implementation/NGA-WS22-005-implementation.md` 与 `doc/task/implementation/NGA-WS22-006-implementation.md`。
- 进行中：无
- 下一步重点：M7 收口验证与发布门禁联调
