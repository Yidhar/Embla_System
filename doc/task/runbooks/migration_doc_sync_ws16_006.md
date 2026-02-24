# WS16-006 Runbook: 迁移文档与 Runbook 同步收口

## 1. 目标
- 保证 `doc/task` 任务板、实施记录、runbook、代码证据路径口径一致。
- 在每轮分片提交后自动校验失效证据路径，避免“任务已 review 但证据失效”。

## 2. 校验入口
- 校验脚本：`scripts/validate_doc_consistency_ws16_006.py`
- 风险映射同步脚本：`scripts/sync_risk_verify_mapping_ws16_006.py`
- 核心校验模块：`system/doc_consistency.py`

## 3. 标准执行步骤
1. 更新 `doc/task/09-execution-board.csv`（任务状态/证据链接/notes）。
2. 落地实现记录：`doc/task/implementation/NGA-XXX-implementation.md`。
3. 如涉及运维动作，补充 `doc/task/runbooks/*.md`。
4. 同步风险验证映射（回填/清理 `verify_for_risks`）：

```bash
python scripts/sync_risk_verify_mapping_ws16_006.py
```

5. 执行一致性校验：

```bash
python scripts/validate_doc_consistency_ws16_006.py --strict
```

## 4. 输出解读
- 输出字段：
  - `checked_rows`: 本次检查的 `review/done` 任务数
  - `error_count`: 失效证据路径数量
  - `warn_count`: 可疑证据项数量
  - `issues[]`: `task_id/field/evidence_item/normalized_path`

## 5. 失败处理
1. `review/done task requires evidence_link`
   - 补齐执行板 `evidence_link` 字段。
2. `evidence path does not exist`
   - 修复路径，或补充缺失文件并更新 evidence。
3. `unable to parse evidence item path`
   - 调整 evidence 为标准 `path` 或 `path::selector` 格式。
4. `review/done task with risk_ids requires verify_for_risks`
   - 先执行 `sync_risk_verify_mapping_ws16_006.py` 回填，再复跑 `--strict`。
5. `missing mapped verification task(s)`
   - 检查 `08-risk-closure-ledger.md` 的 `verification_tasks` 映射与执行板任务状态。

## 6. 值班门禁建议
1. 提交前本地执行 `--strict`。
2. CI 增加轻量门禁，仅对 `doc/task/09-execution-board.csv` 变更触发。
3. 如需审计落盘，附加 `--output logs/autonomous/doc_consistency_report.json`。

## 7. 回滚策略
1. 若文档收口引入冲突，回退本轮 `doc/task` 变更提交。
2. 以最近一次通过 `--strict` 的执行板版本为基线恢复。
3. 重新执行校验并再提交。

## 8. 最后更新
- 2026-02-24
