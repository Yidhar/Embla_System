# Task 拆解总览（迁移 + 增量开发）

文档状态：执行规划（基于当前 As-Is 与目标态文档）  
最后更新：2026-02-25

## 1. 目标

在不打断当前可运行链路（Phase 0）的前提下，按可落地增量方式推进到目标态能力，并把安全盲区治理（R1-R16）纳入主线任务。

## 2. 使用方式

1. 先阅读 `01-program-roadmap-and-milestones.md` 获取里程碑顺序。
2. 再按工作流文档领取任务包（WS10-WS20）。
3. 每个任务必须满足 `00-task-unit-spec.md` 的最小字段与 DoD。
4. 风险闭环使用 `90-risk-traceability-matrix.md` 做验收映射。
5. 若需机器导入或批量排期，使用 `99-task-backlog.csv`。
6. 排期执行优先参考 `02-sprint-plan-ai-agents.md`、`03-p0-shortest-path-onepager.md`、`04-parallel-execution-groups.md`。
7. 细分派工与执行卡片参考 `05-sprint-assignment-matrix.md`、`06-task-unit-subtask-packages.md`。
8. 执行启动与风控闭环参考 `07-execution-launch-playbook.md`、`08-risk-closure-ledger.md`、`09-execution-board.csv`。
9. 文档一致性收口先执行 `python scripts/sync_risk_verify_mapping_ws16_006.py`，再执行 `python scripts/sync_risk_closure_ledger_ws16_006.py --apply`，再执行 `python scripts/sync_task_backlog_status.py --apply`，最后执行 `python scripts/validate_doc_consistency_ws16_006.py --strict`。

## 3. 文档清单

1. `doc/task/00-task-unit-spec.md`
   - 任务单元标准结构、状态机、依赖规则。
2. `doc/task/01-program-roadmap-and-milestones.md`
   - 全局里程碑、阶段目标、入场/出场条件。
3. `doc/task/10-ws-tool-contract-and-io.md`
   - Tool Contract、调用链一致性、I/O 统一封装。
4. `doc/task/11-ws-artifact-and-evidence-pipeline.md`
   - Artifact Store、artifact_reader、配额与保真链路。
5. `doc/task/12-ws-file-ast-and-concurrency.md`
   - 巨型文件治理、语义重基、并发活锁治理。
6. `doc/task/13-ws-subagent-contract-and-scaffold-txn.md`
   - Contract Gate、Scaffold 事务化、并行协作治理。
7. `doc/task/14-ws-brainstem-security-and-runtime-guards.md`
   - Policy Firewall、Mutex/Fencing、KillSwitch OOB、Sleep Watch。
8. `doc/task/15-ws-brain-memory-gc-and-tokenomics.md`
   - GC 证据链、记忆注入、Token 预算守门。
9. `doc/task/16-ws-migration-and-compat-cleanup.md`
   - 迁移收敛、弃用清理、兼容策略。
10. `doc/task/17-ws-quality-release-and-ops-readiness.md`
    - 测试基线、防毒化、混沌演练、发布治理。
11. `doc/task/18-ws-brainstem-core-eventbus-watchdog-dna.md`
    - Event Bus、Watchdog、Immutable DNA 的核心能力补齐。
12. `doc/task/19-ws-brain-core-meta-router-memory.md`
    - Meta/Router/Memory 三大认知核心增量落地。
13. `doc/task/20-ws-frontend-bff-and-boundary-migration.md`
    - 前后端边界、BFF 协议与桌面端联调迁移。
14. `doc/task/90-risk-traceability-matrix.md`
    - 风险 R1-R16 与任务 ID 的双向追踪。
15. `doc/task/99-task-backlog.csv`
    - 结构化任务清单（适合导入项目管理系统）。
16. `doc/task/02-sprint-plan-ai-agents.md`
    - 76 任务自动 Sprint 拆分（按依赖层级 L0-L6 分配 S1-S7）。
17. `doc/task/03-p0-shortest-path-onepager.md`
    - P0 止血最短路径一页执行清单（含波次与 Exit 条件）。
18. `doc/task/04-parallel-execution-groups.md`
    - 按依赖层与工作流 lane 的可并行任务组编排。
19. `doc/task/05-sprint-assignment-matrix.md`
    - Sprint 到执行池（Pool）的分配矩阵，含跨池同步点与 Sprint Gate。
20. `doc/task/06-task-unit-subtask-packages.md`
    - 任务类型标准子任务包与 76 任务逐条映射（可直接派发 Agent 卡片）。
21. `doc/task/07-execution-launch-playbook.md`
    - 按 5 条执行指令落地的启动手册（P0 W1-W5、Sprint S1-S7、lane 并行、M0-M5 门禁、风险闭环）。
22. `doc/task/08-risk-closure-ledger.md`
    - Critical/High 风险闭环台账（实现任务 + 验证任务 + 证据）。
23. `doc/task/09-execution-board.csv`
    - 可直接执行/流转的任务看板数据（已将 W1 任务置为 `in_progress`）。
24. `doc/task/implementation/`
    - 各任务波次实施记录与验证证据归档（按任务 ID 命名）。
25. `doc/task/runbooks/`
    - 运行手册与故障恢复步骤（按任务场景维护）。
26. `doc/task/runbooks/release_m0_m5_closure_onepager.md`
    - 发布收口一页清单（M0-M5 门禁、执行顺序、放行判定）。
27. `doc/task/21-ws-phase3-subagent-runtime-and-scaffold.md`
    - Phase 3 新增工作流：Sub-Agent Runtime + Scaffold Engine 增量落地（WS21）。
28. `doc/task/22-ws-phase3-scheduler-bridge-and-rollout.md`
    - Phase 3 调度接管工作流：SystemAgent 桥接、事件同步、灰度接管（WS22）。
29. `doc/task/runbooks/release_m6_m7_phase3_closure_onepager.md`
    - Phase 3（M6-M7）发布收口一页清单（WS21/WS22 门禁、长稳基线、闭环放行）。
30. `scripts/release_phase3_closure_chain_ws22_004.py`
    - Phase 3 发布脚本链统一入口（串行执行 T0-T3：回归、长稳、门禁、文档一致性）。
31. `scripts/release_closure_chain_m0_m5.py`
    - M0-M5 发布收口脚本链统一入口（串行执行 T0-T5：基线、回归、工单产物）。
32. `scripts/release_closure_chain_full_m0_m7.py`
    - M0-M8 全量发布收口统一入口（兼容脚本名，串行执行 M0-M5 + M6-M7 + M8 门禁链）。
33. `scripts/render_release_closure_summary.py`
    - 发布收口报告摘要生成器（汇总 M0-M8/M0-M5/M6-M7/M8 结果并输出 Markdown）。
34. `scripts/sync_task_backlog_status.py`
    - 将 `99-task-backlog.csv` 的 `status` 字段从 `09-execution-board.csv` 同步对齐。
35. `doc/task/23-phase3-full-target-task-list.md`
    - 从 M7 到 Phase3 Full 的增量任务清单（M8-M12、lane 并行、依赖分组、门禁定义）。
36. `scripts/release_closure_chain_m8_ws23_006.py`
    - M8 发布收口脚本链统一入口（串行执行 T0-T6：WS23 回归、产物生成、门禁、文档一致性）。
37. `scripts/validate_m8_closure_gate_ws23_006.py`
    - M8 闭环门禁校验入口（汇总 WS23-001/003/004/005 报告 + 文档 + runbook）。
38. `scripts/run_outbox_brainstem_bridge_smoke_ws23_005.py`
    - WS23-005 outbox->Brainstem 桥接 smoke 产物生成脚本。
39. `autonomous/ws23_release_gate.py`
    - WS23 M8 门禁评估器（报告规则、文档规则、runbook 规则）。
40. `doc/task/runbooks/release_m8_phase3_closure_onepager_ws23_006.md`
    - M8 发布收口一页清单（T0-T6 执行顺序、放行条件、产物归档）。
41. `doc/task/runbooks/prompt_task_scheduling_protocol_tsp_v1.md`
    - Prompt 层任务排期协议（TSP-v1）：统一 `T0->T1->T2->T3` 执行语义、证据路径与回退口径。
42. `doc/task/24-ws-prompt-routing-injection-policy.md`
    - Prompt 路由注入与多职能 Agent 注入时机设计讨论稿（阶段/风险/证据/失败触发模型）。
43. `scripts/update_immutable_dna_manifest_ws23_003.py`
    - WS23-003 DNA manifest 一键同步工具（更新 manifest + 可选 gate 复验 + 报告落盘）。
44. `doc/task/25-subagent-development-fabric-status-matrix.md`
    - 子代理开发执行面分层状态矩阵（区分 `BRIDGE_DONE` 与 `TARGET_DONE`，并标注文档噪音与统一判定口径）。

## 4. 任务状态约定

- `todo`：未开始
- `in_progress`：执行中
- `blocked`：被外部依赖阻塞
- `review`：开发完成待验证
- `done`：通过验收与回归
- `deferred`：暂缓，需记录原因与回收条件

## 5. 约束

1. 所有高风险任务必须带回滚方案与演练记录。
2. 任何跨模块任务必须明确依赖与接口契约。
3. 迁移任务禁止一次性大爆炸切换，必须支持灰度与回退。
