> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS27-006 实施记录（M12：Phase3 Full 放行报告与签署模板）

## 任务信息
- 任务ID: `NGA-WS27-006`
- 标题: Phase3 Full 放行报告与签署模板
- 状态: 已完成（首版）
- 状态: 已完成（含 WS27-001 墙钟验收可选硬门禁）

## 变更范围

1. 放行报告与签署模板生成脚本
- 文件: `scripts/generate_phase3_full_release_report_ws27_006.py`
- 变更:
  - 新增 `run_generate_phase3_full_release_report_ws27_006(...)`，聚合读取下列报告：
    - `WS27-004` 全量收口报告
    - `WS27-005` 文档一致性报告
    - `WS27-001` 虚拟耐久报告 + 墙钟验收报告
    - `WS27-002/003` 分项执行报告
  - 统一输出放行 JSON 报告：
    - `scratch/reports/phase3_full_release_report_ws27_006.json`
  - 同步输出 Markdown 签署模板：
    - `scratch/reports/phase3_full_release_signoff_ws27_006.md`
  - 支持 `--strict`（检查失败时返回非零）。
  - 支持 `--require-wallclock-acceptance`：
    - 关闭时：墙钟报告仅展示，不纳入强制门禁。
    - 开启时：墙钟报告纳入强制门禁，适用于正式签署。

2. 一键签署收口链（补充）
- 文件: `scripts/release_phase3_full_signoff_chain_ws27_006.py`
- 变更:
  - 新增 `WS27-004 -> WS27-005 -> WS27-006` 的单命令收口链。
  - 支持 `--require-wallclock-acceptance` 向下透传至 `WS27-006` 步骤。
  - 支持 `--quick-mode`、`--skip-m0-m11`、`--skip-full-chain`、`--skip-doc-consistency`、`--skip-release-report`。
  - 产出统一链路报告：`scratch/reports/release_phase3_full_signoff_chain_ws27_006_result.json`。

3. 自动化回归
- 文件: `tests/test_ws27_006_phase3_release_report.py`
- 变更:
  - 覆盖全部输入通过时 `PASS` 路径与模板内容校验。
  - 覆盖输入报告缺失时失败路径（含缺失清单）。
  - 覆盖启用 `require_wallclock_acceptance=True` 且墙钟报告缺失时失败路径。
  - 覆盖 CLI `--strict` 非零返回码路径。

- 文件: `tests/test_release_phase3_full_signoff_chain_ws27_006.py`
- 变更:
  - 覆盖一键链全步骤通过路径。
  - 覆盖默认失败即停路径。
  - 覆盖 `--require-wallclock-acceptance` 透传路径。

4. 执行 runbook
- 文件: `doc/task/runbooks/release_m12_phase3_full_signoff_onepager_ws27_006.md`
- 变更:
  - 新增一键链推荐命令，保留手工分步模式。
  - 固化正式签署必须启用 `--require-wallclock-acceptance`。

4. 任务快照更新
- 文件: `doc/task/23-phase3-full-target-task-list.md`
- 变更:
  - 新增 `NGA-WS27-006` 首版落地说明、产物路径与回归锚点。

## 验证命令

1. WS27-006 定向回归
- `python3 -m pytest -q tests/test_ws27_006_phase3_release_report.py -p no:tmpdir`
- `python3 -m pytest -q tests/test_release_phase3_full_signoff_chain_ws27_006.py -p no:tmpdir`

2. 代码规范
- `python3 -m ruff check scripts/generate_phase3_full_release_report_ws27_006.py scripts/release_phase3_full_signoff_chain_ws27_006.py tests/test_ws27_006_phase3_release_report.py tests/test_release_phase3_full_signoff_chain_ws27_006.py`

3. 本地执行（一键链 + 墙钟硬门禁）
- `python3 scripts/release_phase3_full_signoff_chain_ws27_006.py --require-wallclock-acceptance`

## 结果摘要

- `NGA-WS27-006` 已提供可审计的放行报告聚合器与可直接签署的模板产物。
- 该能力将 `M12` 分散证据收敛到单一判定域，并支持“预览模式/正式签署模式”双轨门禁。
- 新增一键签署收口链后，本机可通过单命令完成 `WS27-004~006` 的串行闭环。
