> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS27-003 实施记录（M12：OOB 抢修 Runbook + 演练记录）

## 任务信息
- 任务ID: `NGA-WS27-003`
- 标题: OOB 抢修 Runbook + 演练记录
- 状态: 已完成（首版）

## 变更范围

1. OOB 抢修演练脚本
- 文件: `scripts/run_ws27_oob_repair_drill_ws27_003.py`
- 变更:
  - 新增 `run_ws27_oob_repair_drill_ws27_003(...)`，统一编排并产出 JSON 报告。
  - 演练覆盖三条关键恢复路径：
    - `snapshot_based_rollback_recovery`：调用 `WS27-002` 的 `plan -> apply -> rollback`，验证快照回滚恢复闭环。
    - `force_legacy_fallback_without_snapshot`：模拟快照缺失，验证 `rollback` 安全降级到 legacy。
    - `oob_bundle_export_validation`：复用 `WS23-004` 的 OOB bundle 导出，校验 freeze/probe 计划可用性。
  - 默认报告路径：
    - `scratch/reports/ws27_oob_repair_drill_ws27_003.json`

2. 自动化回归
- 文件: `tests/test_run_ws27_oob_repair_drill_ws27_003.py`
- 变更:
  - 覆盖函数路径执行与报告落盘校验。
  - 覆盖 CLI smoke（参数解析、执行返回码、报告文件输出）。

3. 执行 runbook
- 文件: `doc/task/runbooks/release_m12_oob_repair_drill_onepager_ws27_003.md`
- 变更:
  - 固化远程环境的演练命令、判定标准与产物路径。
  - 明确三条恢复路径的验收检查点，便于 `M12` 收口链追溯。

4. 任务快照更新
- 文件:
  - `doc/task/23-phase3-full-target-task-list.md`
  - `doc/task/runbooks/remote_test_env_handoff_phase3_m11_to_m12.md`
- 变更:
  - 将 `NGA-WS27-003` 标记为“首版已落地”，并补充代码锚点、关键回归与远程产物路径。

## 验证命令

1. WS27-003 定向回归
- `python3 -m pytest -q tests/test_run_ws27_oob_repair_drill_ws27_003.py -p no:tmpdir`

2. M12 当前最小联合回归（WS27-001/002/003）
- `python3 -m pytest -q autonomous/tests/test_ws27_longrun_endurance_ws27_001.py tests/test_run_ws27_longrun_endurance_ws27_001.py tests/test_manage_ws27_subagent_cutover_ws27_002.py tests/test_run_ws27_oob_repair_drill_ws27_003.py -p no:tmpdir`

## 结果摘要

- `NGA-WS27-003` 已具备可执行、可回归、可审计的首版 OOB 抢修演练链路。
- 报告中同时覆盖“快照恢复”和“快照缺失安全降级”两类核心回退场景。
- 可作为后续 `NGA-WS27-004`（M0-M12 全量收口链）中的 M12/OOB 演练输入项。
