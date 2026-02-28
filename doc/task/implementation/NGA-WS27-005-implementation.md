> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS27-005 实施记录（M12：文档一致性收口）

## 任务信息
- 任务ID: `NGA-WS27-005`
- 标题: 文档一致性收口（`00/10/11/12/13 + task`）
- 状态: 已完成（首版）

## 变更范围

1. M12 文档一致性专项校验脚本
- 文件: `scripts/validate_m12_doc_consistency_ws27_005.py`
- 变更:
  - 复用 `system.doc_consistency.validate_execution_board_consistency(...)` 执行 board/evidence 一致性检查。
  - 新增 M12 专项校验项：
    - 核心架构文档存在性（`00/10/11/12/13` + `23-phase3` 任务清单）
    - `WS27-001~004` 实施记录存在性
    - `WS27-002~004` runbook 存在性
    - `23-phase3` 快照中的 `WS27-001~004`“已落地”标记完整性
  - 输出统一报告：`scratch/reports/ws27_m12_doc_consistency_ws27_005.json`

2. 自动化回归
- 文件: `tests/test_ws27_005_m12_doc_consistency.py`
- 变更:
  - 覆盖全部条件满足时的通过路径。
  - 覆盖缺失 runbook + 缺失快照标记时的失败路径。
  - 覆盖 CLI `--strict` 失败返回非零路径。

3. 执行 runbook
- 文件: `doc/task/runbooks/release_m12_doc_consistency_onepager_ws27_005.md`
- 变更:
  - 固化执行命令、判定标准、失败排查入口与报告路径。

4. 任务快照更新
- 文件: `doc/task/23-phase3-full-target-task-list.md`
- 变更:
  - 新增 `NGA-WS27-005` 首版落地说明与代码锚点。

## 验证命令

1. WS27-005 定向回归
- `python3 -m pytest -q tests/test_ws27_005_m12_doc_consistency.py -p no:tmpdir`

2. 代码规范
- `python3 -m ruff check scripts/validate_m12_doc_consistency_ws27_005.py tests/test_ws27_005_m12_doc_consistency.py`

3. 本地执行（严格模式）
- `python3 scripts/validate_m12_doc_consistency_ws27_005.py --strict --output scratch/reports/ws27_m12_doc_consistency_ws27_005.json`

## 结果摘要

- `NGA-WS27-005` 已形成可执行、可回归、可审计的 M12 文档一致性校验入口。
- 该脚本可直接作为 `WS27-006` 放行报告生成的前置输入之一。

## 补充更新（2026-02-25）

为适配当前自主运行 agent 架构，本轮补充了 Prompt 层任务排期协议（TSP-v1）对齐：

1. Prompt 批量重构（4 文件）
- `system/prompts/conversation_style_prompt.txt`
- `system/prompts/conversation_analyzer_prompt.txt`
- `system/prompts/tool_dispatch_prompt.txt`
- `system/prompts/agentic_tool_prompt.txt`
- 统一引入 `T0 发现 -> T1 实施 -> T2 验证 -> T3 证据` 的排期语义与交付口径。

2. 新增 runbook
- `doc/task/runbooks/prompt_task_scheduling_protocol_tsp_v1.md`
- 固化 TSP-v1 字段定义、状态流转、Prompt 职责分层与回退策略。

3. 文档索引更新
- `doc/task/README.md`
- 新增 TSP-v1 runbook 入口，便于后续任务排期复用。

## 补充推进进度（2026-02-26）

当前阶段围绕 Prompt 治理继续推进到“可一键同步 DNA”的可执行状态：

1. 新增 DNA 同步工具
- `scripts/update_immutable_dna_manifest_ws23_003.py`
- 支持审批票据、manifest 更新、可选 gate 复验、严格失败返回码。

2. 新增自动化回归
- `tests/test_update_immutable_dna_manifest_ws23_003.py`
- 覆盖成功、缺票据失败、`skip_verify` 三条路径。

3. 文档与 runbook 对齐
- `doc/task/implementation/NGA-WS23-003-implementation.md`
- `doc/task/runbooks/release_m8_phase3_closure_onepager_ws23_006.md`
- `doc/task/runbooks/prompt_task_scheduling_protocol_tsp_v1.md`

4. 进度状态
- Prompt 批量重构（TSP-v1）：已完成
- DNA manifest 门禁闭环（含一键同步工具）：已完成
- 现阶段可直接进入下一批 prompt 实战样本回归与调度行为压测
