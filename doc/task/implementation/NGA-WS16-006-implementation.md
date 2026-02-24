# NGA-WS16-006 实施记录（文档与 Runbook 同步收口）

## 任务信息
- Task ID: `NGA-WS16-006`
- Title: 文档与Runbook 同步收口
- 状态: 已完成（进入 review）

## 本次范围（仅 WS16-006）
1. 文档一致性校验能力
- 新增 `system/doc_consistency.py`
  - `validate_execution_board_consistency(...)`：
    - 扫描 `doc/task/09-execution-board.csv` 中 `review/done` 行
    - 解析 `evidence_link`（支持 `path::selector` / `path:line`）
    - 校验证据路径是否存在
  - 输出结构化 `ConsistencyReport`（error/warn 计数与明细）

2. 校验脚本与运维入口
- 新增 `scripts/validate_doc_consistency_ws16_006.py`
  - `--strict`：存在 error 时非零退出
  - `--output`：报告 JSON 落盘

3. 自动化测试
- 新增 `tests/test_doc_consistency_ws16_006.py`
  - 正常 evidence 路径通过
  - 缺失路径报错
  - `review` 行缺 evidence 报错

4. 文档入口同步
- 更新 `doc/task/README.md`
  - 新增一致性校验命令入口
  - 补充 `runbooks/` 目录说明
- 修复并重建 `doc/task/_CHECKLIST.md`
  - 修正格式与目录清单，纳入 `implementation/` 与 `runbooks/`
- 新增 runbook：
  - `doc/task/runbooks/migration_doc_sync_ws16_006.md`

5. 风险闭环映射增量收口（本轮补充）
- `system/doc_consistency.py`
  - 新增 `risk_ledger_file` 支持，校验 `risk_ids -> verify_for_risks` 映射完整性
  - 校验 `verify_for_risks` 中 task_id 必须存在于执行板
- 新增 `scripts/sync_risk_verify_mapping_ws16_006.py`
  - 自动回填/清理执行板 `verify_for_risks`
- 扩展 `tests/test_doc_consistency_ws16_006.py`
  - 增加风险映射缺失/缺项/完整场景覆盖
- 新增 `tests/test_sync_risk_verify_mapping_ws16_006.py`
  - 覆盖映射回填与 CSV 结构保持

## 验证命令
- `.\.venv\Scripts\python.exe -m ruff check system/doc_consistency.py scripts/validate_doc_consistency_ws16_006.py scripts/sync_risk_verify_mapping_ws16_006.py tests/test_doc_consistency_ws16_006.py tests/test_sync_risk_verify_mapping_ws16_006.py doc/task/README.md`
  - 结果: `All checks passed!`
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_doc_consistency_ws16_006.py tests/test_sync_risk_verify_mapping_ws16_006.py`
  - 结果: `passed`
- `.\.venv\Scripts\python.exe scripts/sync_risk_verify_mapping_ws16_006.py`
  - 结果: `verify_for_risks` 自动回填/清理完成
- `.\.venv\Scripts\python.exe scripts/validate_doc_consistency_ws16_006.py --strict`
  - 结果: `error_count=0`（当前执行板证据路径有效）

## 交付结果与验收对应
- deliverables“迁移后文档一致性修订”：已形成可执行校验脚本 + runbook + 目录入口同步。
- acceptance“无冲突口径与失效路径”：`--strict` 校验当前任务板通过。
- rollback“变更记录可追溯”：通过分片提交与报告输出可追溯。

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `system/doc_consistency.py; scripts/validate_doc_consistency_ws16_006.py; tests/test_doc_consistency_ws16_006.py; doc/task/README.md; doc/task/_CHECKLIST.md; doc/task/runbooks/migration_doc_sync_ws16_006.md; doc/task/implementation/NGA-WS16-006-implementation.md`
- `notes`:
  - `doc/runbook sync closure now provides strict execution-board evidence validation, parser normalization for selector-based paths, and a standard runbook-driven closure workflow`

## Date
2026-02-24
