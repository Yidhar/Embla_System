# M12 一页式执行清单（WS27-003：OOB 抢修 Runbook 演练）

适用任务：`NGA-WS27-003`  
默认分支：`当前 Embla 开发分支`

## 1. 目标

- 在远程环境演练“SubAgent cutover 后异常”场景下的 OOB 抢修路径。
- 验证三条恢复链路均可执行、可回退、可审计：
  - 快照恢复回退闭环
  - 快照缺失时重置到安全基线
  - OOB bundle 导出与验证

## 2. 关键脚本

- 主脚本：`scripts/run_ws27_oob_repair_drill_ws27_003.py`
- 依赖脚本（cutover/rollback）：`scripts/manage_ws27_subagent_cutover_ws27_002.py`
- 依赖脚本（OOB bundle）：`scripts/export_killswitch_oob_bundle_ws23_004.py`
- 默认报告输出：`scratch/reports/ws27_oob_repair_drill_ws27_003.json`

## 3. 推荐执行顺序

1. 先准备 WS26 运行时快照（建议）

```powershell
.\.venv\Scripts\python.exe scripts/export_ws26_runtime_snapshot_ws26_002.py `
  --output scratch/reports/ws26_runtime_snapshot_ws26_002.json
```

2. 执行 WS27-003 OOB 抢修演练

```powershell
.\.venv\Scripts\python.exe scripts/run_ws27_oob_repair_drill_ws27_003.py `
  --repo-root . `
  --output scratch/reports/ws27_oob_repair_drill_ws27_003.json `
  --scratch-root scratch/ws27_oob_repair_drill `
  --rollback-window-minutes 180 `
  --oob-allowlist 10.0.0.0/24 bastion.example.com `
  --probe-targets 10.0.0.10 bastion.example.com
```

3. 检查主报告关键字段

- `passed=true`
- `checks.snapshot_recovery_path=true`
- `checks.safe_baseline_without_snapshot_path=true`
- `checks.oob_bundle_validation_path=true`

## 4. 预期产物

1. `scratch/reports/ws27_oob_repair_drill_ws27_003.json`
2. `scratch/ws27_oob_repair_drill/*/case_snapshot_recovery/repo/scratch/reports/ws27_drill_case1_plan.json`
3. `scratch/ws27_oob_repair_drill/*/case_snapshot_recovery/repo/scratch/reports/ws27_drill_case1_apply.json`
4. `scratch/ws27_oob_repair_drill/*/case_snapshot_recovery/repo/scratch/reports/ws27_drill_case1_rollback.json`
5. `scratch/ws27_oob_repair_drill/*/case_safe_baseline_without_snapshot/repo/scratch/reports/ws27_drill_case2_rollback.json`
6. `scratch/ws27_oob_repair_drill/*/case_oob_bundle_export/ws27_drill_oob_bundle.json`

## 5. 判定标准

- 主报告 `passed=true` 且三项 `checks` 全部为 `true`。
- `case_results` 中 `C1/C2/C3` 均 `passed=true`：
  - `C1`：回滚后配置应恢复到 apply 前快照。
  - `C2`：无快照回滚时 `rollback_mode=safe_baseline_without_snapshot`。
  - `C3`：`freeze_plan.validation_ok=true` 且 `probe_plan.validation_ok=true`。

## 6. 风险与说明

- 该脚本用于“可重复演练”与“流程验证”，并非真实云主机故障注入。
- 放行签署仍需结合 `WS27-001` 真实 72h 墙钟验收报告与 `WS27-004` 全量收口链结果。
