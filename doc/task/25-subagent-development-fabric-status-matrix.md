# 25 子代理开发执行面分层状态矩阵（Target vs Bridge）


> Migration Note (archived/legacy)
> 文中 `autonomous/*` 路径属于历史实现标识；当前实现请优先使用 `agents/*`、`core/*` 与 `config/autonomous_runtime.yaml`。

文档状态：执行对齐（Consistency Baseline）  
最后更新：2026-02-26  
适用范围：`Sub-Agent Runtime / Scaffold Engine / Execution Bridge / SystemAgent rollout`

---

## 1. 目标

解决以下口径混淆：

1. “子代理能力可用”与“目标态子代理完成”不是同一件事。
2. legacy `CLI Adapter` 属于兼容桥接，不应被解读为目标态完成。
3. `WS21/WS22/WS27` 的实施完成记录与 `00` 蓝图中的目标态描述，需要统一判定语义。

---

## 2. 判定语义（强制）

本文统一使用三类状态：

1. `TARGET_DONE`
- 含义：达到 `doc/00-omni-operator-architecture.md` 与 `doc/12-limbs-layer-modules.md` 的目标态定义。
- 必要条件：执行面内生可控（进程级/契约级/审计级），不依赖外部黑盒代理作为最终执行核心。

2. `BRIDGE_DONE`
- 含义：桥接/过渡方案已工程化可运行，具备回归与门禁证据。
- 说明：可上线运行，不等价于目标态完成。

3. `TARGET_PENDING`
- 含义：目标态尚未达成，可能仅有设计或局部实现。

---

## 3. 子代理能力分层矩阵（2026-02-26）

| 能力项 | 目标态定义（预定设定） | 当前实现 | 状态 | 代码锚点 | 验证证据 |
|---|---|---|---|---|---|
| Sub-Agent Runtime 依赖调度 | FE/BE/Ops 子任务依赖感知编排 + 统一执行门禁 | 已具备依赖调度、子任务规范校验、fail-fast | `BRIDGE_DONE` | `agents/runtime/mini_loop.py` | `tests/test_subagent_contract.py`, `tests/test_subagent_contract.py` |
| Contract Gate（协商前置） | FE/BE 并行前冻结 `contract_id + checksum` | 已具备协商前置与 mismatch 拒绝链 | `BRIDGE_DONE` | `agents/runtime/mini_loop.py`, `system/subagent_contract.py` | `tests/test_subagent_contract.py`, `tests/test_subagent_contract.py` |
| Scaffold 原子提交 | 多文件补丁事务化提交 + verify 失败回滚 | 已具备事务提交、verify pipeline、回滚票据 | `BRIDGE_DONE` | `autonomous/scaffold_engine.py`（archived/legacy）, `autonomous/scaffold_verify_pipeline.py`（archived/legacy） | `tests/test_workspace_txn_e2e_regression.py`, `tests/test_workspace_txn_e2e_regression.py`, `tests/test_workspace_txn_e2e_regression.py` |
| SystemAgent 调度桥接 | 主链可灰度接管 Runtime，失败可回退 | 已切到 subagent-only；保留 `runtime_mode` 遥测与 fail-open 预算阻断，不再回退 legacy CLI | `BRIDGE_DONE` | `agents/pipeline.py` | `tests/test_agent_runtime_session_ws30_002.py`, `tests/test_manage_ws27_subagent_cutover_ws27_002.py`, `tests/test_run_ws26_m11_runtime_chaos_suite_ws26_006.py` |
| M12 Full Cutover 运营能力 | 可执行全量切换与回滚窗 | 已具备 `plan/apply/status/rollback` 管理脚本 | `BRIDGE_DONE` | `scripts/manage_ws27_subagent_cutover_ws27_002.py` | `tests/test_manage_ws27_subagent_cutover_ws27_002.py`, `doc/task/implementation/NGA-WS27-002-implementation.md` |
| FE/BE/Ops 子代理执行面（内生） | 非黑盒的内生子代理进程执行器，具备统一可控审计 | 已切到内生 `NativeExecutionBridge`，并落地 FE/BE/Ops 角色专用执行器 v1（路径策略 + strict 门禁 + 审计回执） | `BRIDGE_DONE` | `agents/pipeline.py`, `agents/tool_loop.py` | `tests/test_run_ws28_execution_governance_gate_ws28_021.py`, `tests/test_agent_roles_ws30_005.py`, `tests/test_run_ws28_execution_governance_gate_ws28_021.py` |
| Execution Bridge 终态 | 子代理输出到执行动作的内建可审计桥，不依赖外部黑盒 | 已落地 `SubTaskExecutionBridgeReceipt + SubTaskExecutionCompleted`，并完成旧别名事件退役 | `BRIDGE_DONE` | `agents/tool_loop.py`, `agents/runtime/mini_loop.py`, `agents/pipeline.py` | `tests/test_core_event_bus_consumers_ws28_029.py`, `tests/test_run_ws28_execution_governance_gate_ws28_021.py` |
| Brainstem 控制面独立化（P0） | 脑干守护链路独立进程可启动、可心跳、可健康探针 | `WS23-001` 入口已补齐 `daemon` 模式与心跳快照契约（仍未到目标态“不可变脑干进程部署”） | `BRIDGE_DONE` | `scripts/run_brainstem_supervisor_ws23_001.py`, `system/brainstem_supervisor.py` | `tests/test_brainstem_supervisor_entry_ws23_001.py`, `tests/test_brainstem_supervisor_ws18_008.py` |

---

## 4. 当前明确结论

1. 当前“开发任务子代理”已完成的是：`Runtime + Contract + Scaffold + Rollout + Native Execution Bridge` 的桥接执行闭环。
2. 当前未完成的是：`Frontend/Backend/Ops` 角色专用执行器的深层能力（语义级工具链/角色特化执行器）与目标态脑干进程独立化（当前仅完成独立入口与心跳契约）。
3. 因此“WS21/WS22/WS27 + WS28-013 已完成”代表桥接闭环进一步收敛，不等同于 Phase3 目标态全部达成。

---

## 5. 主要文档噪音与修订建议

### 5.1 噪音点 A：WS22 进度读法

现状：

1. `doc/task/22-ws-phase3-scheduler-bridge-and-rollout.md` 写 `4/4` 完成，指的是该文档内的 `001~004` 主任务。
2. `NGA-WS22-005/006` 属于后续扩展补齐，记录在 `doc/task/implementation/`。

建议：

1. 在 WS22 文档中显式标注“`4/4` 不含扩展项 005/006”。
2. 统一通过本文件矩阵判断“桥接完成 vs 目标态完成”。

### 5.2 噪音点 B：事件命名历史遗留（已收口）

现状：

1. 主事件已切到 `SubTaskExecutionCompleted`。
2. `SubTaskCliExecutionCompleted` 兼容别名已退役，报表应统一使用主事件。

建议：

1. 保持 `SubTaskExecutionCompleted` 为主语义，禁止新增“CLI”事件命名依赖。
2. 发布门禁脚本统一切到主事件字段，旧字段仅保留历史报告离线兼容。

### 5.3 噪音点 C：旧版目标文档时间戳

现状：

1. `doc/11-brain-layer-modules.md` 与 `doc/12-limbs-layer-modules.md` 仍为 2026-02-22 口径。
2. 部分 “当前实现映射” 已与最新实现快照存在偏差。

建议：

1. 后续做一次 `11/12` 文档的 As-Is 对齐刷新，确保与 `doc/00` 矩阵同源。

---

## 6. 关联文档（单一阅读路径）

建议按以下顺序阅读，避免交叉误读：

1. `doc/00-omni-operator-architecture.md`（总蓝图与阶段边界）
2. `doc/task/25-subagent-development-fabric-status-matrix.md`（本文，状态判定基线）
3. `doc/task/23-phase3-full-execution-board.csv`（WS23-WS27 实时状态）
4. `doc/task/21-ws-phase3-subagent-runtime-and-scaffold.md`（Runtime/Scaffold 主任务）
5. `doc/task/22-ws-phase3-scheduler-bridge-and-rollout.md`（调度桥接与灰度接管）
6. `doc/task/implementation/NGA-WS22-005-implementation.md`、`doc/task/implementation/NGA-WS22-006-implementation.md`
7. `doc/task/implementation/NGA-WS27-002-implementation.md`（M12 full cutover）
8. `doc/task/implementation/NGA-WS28-019-implementation.md`（脑干守护进程存活探测与自愈重启）
9. `doc/task/implementation/NGA-WS28-020-implementation.md`（脑干控制面托管入口标准化）
10. `doc/task/implementation/NGA-WS28-021-phaseb-implementation.md`（语义工具链守卫与治理可观测）
11. `doc/task/implementation/NGA-WS28-021-phasecd-implementation.md`（语义策略 `.spec` 外置与门禁闭环）

---

## 7. WS28 下一步任务卡（Target Pending 收口）

### NGA-WS28-019 脑干守护进程真实存活探测与自愈重启

- type: `hardening`
- priority: `P0`
- status: `done`（2026-02-27）
- scope: 修复“状态显示 running 但子进程已死”的假存活窗口
- code anchors:
  - `system/brainstem_supervisor.py`
  - `scripts/run_brainstem_supervisor_ws23_001.py`
- tests:
  - `tests/test_brainstem_supervisor_ws18_008.py`
  - `tests/test_brainstem_supervisor_entry_ws23_001.py`
  - `tests/test_manage_brainstem_control_plane_ws28_017.py`
  - `tests/test_api_server_brainstem_bootstrap_ws28_018.py`

### NGA-WS28-020 脑干控制面托管入口标准化（启动/停止/状态）

- type: `ops`
- priority: `P0`
- status: `done`（2026-02-27）
- scope: 将托管入口与 runbook/全链验收保持同源，确保新环境首启可重复
- code anchors:
  - `scripts/manage_brainstem_control_plane_ws28_017.py`
  - `scripts/release_closure_chain_full_m0_m12.py`
  - `doc/task/runbooks/release_m12_full_chain_m0_m12_onepager_ws27_004.md`
- tests:
  - `tests/test_manage_brainstem_control_plane_ws28_017.py`
  - `tests/test_release_closure_chain_full_m0_m12.py`

### NGA-WS28-021 FE/BE/Ops 角色专用执行器 v2（语义级）

- type: `feature`
- priority: `P1`
- status: `done`（2026-02-28）
- scope: 在现有路径策略/strict 门禁基础上，补语义级工具链与更细粒度策略
- expected anchors:
  - `agents/tool_loop.py`
  - `agents/pipeline.py`
  - `agents/runtime/mini_loop.py`
- progress snapshot:
  - 已完成 Phase A：`role_executor_policy` 从任务 contract 侧透传为标准事件字段（`SubTaskDispatching` / `SubTaskExecutionCompleted`），不再依赖手填 metadata。
  - 已完成 Phase B：执行桥新增 FE/BE/Ops 语义工具链守卫（semantic toolchain guard），并将结构化拒绝原因（`reason_code/category/severity/violations/policy_source`）接入 `SubTaskExecutionCompleted/SubTaskRejected` 事件与 `/v1/ops/runtime/posture`、`/v1/ops/incidents/latest` 聚合视图。
  - 已完成 Phase C：语义守卫策略外置为 `.spec`（`policy/role_executor_semantic_guard.spec`），`execution_bridge` 按 spec 加载并支持任务 contract 覆盖。
  - 已完成 Phase D：`M0-M12` 全链新增 `m12_execution_governance` 门禁组，治理 critical 与预算超限可直接阻断收口链；同时对 `role_executor_semantic_guard.spec` 执行低成本发布门禁（存在性/schema/角色完整性+hash）。
  - 已完成收口 E：`release signoff` 接入 governance `reason_code` 的 `hard/soft` 分层策略表，不再只依赖固定预算阈值。
  - 已完成收口 F：`role_executor_semantic_guard.spec` 纳入受控变更链（`ACL + 审批票据 + 审计 ledger`），并纳入 `WS28-021` 门禁校验。

### NGA-WS28-022~025 待办拆卡（#4/#6/#7/#9）

- 状态：`active`（2026-02-27）
- 任务单：`doc/task/implementation/NGA-WS28-022-025-executable-cards.md`
- 说明：
  - `WS28-022`（#7）Immutable DNA 运行时注入：`done`，实施记录 `doc/task/implementation/NGA-WS28-022-implementation.md`。
  - `WS28-023`（#9）真实 MCP agent 隔离联调：`done`，实施记录 `doc/task/implementation/NGA-WS28-023-implementation.md`。
  - `WS28-024`（#4）Brainstem Supervisor 接入主启动链：`done`，实施记录 `doc/task/implementation/NGA-WS28-024-implementation.md`。
  - `WS28-025`（#6）Watchdog Daemon 常驻化：`done`，实施记录 `doc/task/implementation/NGA-WS28-025-implementation.md`。
