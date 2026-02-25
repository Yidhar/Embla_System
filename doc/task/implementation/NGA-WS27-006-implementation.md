# NGA-WS27-006 实施记录（M12：Phase3 Full 放行报告与签署模板）

## 任务信息
- 任务ID: `NGA-WS27-006`
- 标题: Phase3 Full 放行报告与签署模板
- 状态: 已完成（首版）

## 变更范围

1. 放行报告与签署模板生成脚本
- 文件: `scripts/generate_phase3_full_release_report_ws27_006.py`
- 变更:
  - 新增 `run_generate_phase3_full_release_report_ws27_006(...)`，聚合读取下列报告：
    - `WS27-004` 全量收口报告
    - `WS27-005` 文档一致性报告
    - `WS27-001/002/003` 分项执行报告
  - 统一输出放行 JSON 报告：
    - `scratch/reports/phase3_full_release_report_ws27_006.json`
  - 同步输出 Markdown 签署模板：
    - `scratch/reports/phase3_full_release_signoff_ws27_006.md`
  - 支持 `--strict`（检查失败时返回非零）。

2. 自动化回归
- 文件: `tests/test_ws27_006_phase3_release_report.py`
- 变更:
  - 覆盖全部输入通过时 `PASS` 路径与模板内容校验。
  - 覆盖输入报告缺失时失败路径（含缺失清单）。
  - 覆盖 CLI `--strict` 非零返回码路径。

3. 执行 runbook
- 文件: `doc/task/runbooks/release_m12_phase3_full_signoff_onepager_ws27_006.md`
- 变更:
  - 固化 `WS27-004 + WS27-005` 后的签署报告生成命令与判定标准。

4. 任务快照更新
- 文件: `doc/task/23-phase3-full-target-task-list.md`
- 变更:
  - 新增 `NGA-WS27-006` 首版落地说明、产物路径与回归锚点。

## 验证命令

1. WS27-006 定向回归
- `python3 -m pytest -q tests/test_ws27_006_phase3_release_report.py -p no:tmpdir`

2. 代码规范
- `python3 -m ruff check scripts/generate_phase3_full_release_report_ws27_006.py tests/test_ws27_006_phase3_release_report.py`

3. 本地执行（严格模式）
- `python3 scripts/generate_phase3_full_release_report_ws27_006.py --strict --output-json scratch/reports/phase3_full_release_report_ws27_006.json --output-markdown scratch/reports/phase3_full_release_signoff_ws27_006.md`

## 结果摘要

- `NGA-WS27-006` 已提供可审计的放行报告聚合器与可直接签署的模板产物。
- 该能力将 `M12` 分散证据收敛到单一判定域，支持本机端到端放行闭环。
