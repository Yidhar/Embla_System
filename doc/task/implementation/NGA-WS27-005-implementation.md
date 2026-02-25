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
