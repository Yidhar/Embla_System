# Embla System 文档索引

本目录用于统一归档项目架构、开发 runbook、工具治理与目标态设计文档。

## 文档分层（强制口径）

- `L0-RUNTIME`：当前运行主链与开发基线（可直接指导开发与验收）。
- `L1-TARGET`：目标态/设计态蓝图（指导演进，不等价当前已落地行为）。
- `L2-RUNBOOK`：执行手册与发布闭环流程（流程口径）。
- `L3-ARCHIVE`：历史实施记录与阶段快照（仅用于追溯，不作为当前主链依据）。

分层判定规则：

1. 发生冲突时，优先级 `L0 > L2 > L1 > L3`。
2. `L3` 文档中出现的目录、端口、接口，不代表当前仓库可运行状态。
3. 开发执行默认只用 `L0 + L2`；`L1` 用于方案设计；`L3` 仅用于历史比对。

## 文档清单

1. `doc/00-omni-operator-architecture.md`
   - `L1-TARGET`：Embla System 目标态总蓝图（Phase 3 参考，不等价当前实现）。
2. `doc/01-module-overview.md`
   - `L0-RUNTIME`：当前模块总览、运行链路与关键边界。
3. `doc/02-module-archive.md`
   - `L0-RUNTIME`：模块职责归档、关键文件与风险点。
4. `doc/05-dev-startup-and-index.md`
   - `L0-RUNTIME`：开发启动 runbook、端口基线与排障清单。
5. `doc/06-structured-tool-calls-and-local-first-native.md`
   - `L0-RUNTIME`：结构化工具调用链路与本地优先执行策略。
6. `doc/07-archived-autonomous-agent-sdlc-architecture.md`
   - `L3-ARCHIVE`：历史自治 SDLC 架构与迁移演进记录（非当前主链）。
7. `doc/08-frontend-backend-separation-plan.md`
   - `L0/L1`：前后端边界收敛与分阶段解耦方案（含现状与目标）。
8. `doc/09-tool-execution-specification.md`
   - `L2-RUNBOOK`：工具调用规范、风控门禁与审计模板。
9. `doc/10-brainstem-layer-modules.md`
   - `L1-TARGET`：目标态脑干层模块设计（Phase 2-3 规划）。
10. `doc/11-brain-layer-modules.md`
   - `L1-TARGET`：目标态大脑层模块设计（Phase 3 规划）。
11. `doc/12-limbs-layer-modules.md`
   - `L1-TARGET`：目标态手脚层模块设计（Phase 3 规划）。
12. `doc/13-security-blindspots-and-hardening.md`
   - `L2-RUNBOOK`：安全盲区审计与强制加固基线（覆盖命令混淆、插件隔离、锁泄漏、评测毒化等）。
13. `doc/task/README.md`
    - `L2/L3`：迁移与增量开发任务拆解总览（结构化工作流 + CSV backlog + 历史归档入口）。
14. `doc/task/implementation/README.md`
    - `L3-ARCHIVE`：任务实施记录归档层说明（Implementation 目录统一口径）。

## 当前口径优先级（执行主链）

1. `doc/00-omni-operator-architecture.md`
   - 目标态蓝图与“当前主链”对齐总口径。
2. `doc/task/25-subagent-development-fabric-status-matrix.md`
   - `TARGET_DONE / BRIDGE_DONE / TARGET_PENDING` 强制判定语义。
3. `doc/task/runbooks/subagent_runtime_native_bridge_sequence_and_gate_runbook.md`
   - 内生执行链路、gate 决策和排障路径。
4. `doc/frontend-refactor-plan.md`
   - 数据面板优先（Runtime/MCP/Memory/Workflow）和聚合接口规范。

## 建议阅读路径（按分层）

1. 先读 `L0`：`doc/01-module-overview.md`、`doc/05-dev-startup-and-index.md`、`doc/06-structured-tool-calls-and-local-first-native.md`。
2. 再读 `L2`：`doc/task/runbooks/INDEX.md` 与 `doc/09-tool-execution-specification.md`。
3. 涉及演进方案时补读 `L1`：`doc/00-omni-operator-architecture.md`、`doc/10/11/12-*`。
4. 涉及历史追溯时才进入 `L3`：`doc/07-archived-autonomous-agent-sdlc-architecture.md`、`doc/task/implementation/`。
