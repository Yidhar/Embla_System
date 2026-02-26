# M12 一页式执行清单（WS27-004：M0-M12 全量收口链）

适用任务：`NGA-WS27-004`  
默认分支：`modifier/naga`

## 1. 目标

- 提供 `M0-M12` 一体化收口入口，统一串联：
  - 既有 `M0-M11` 发布门禁链
  - `M12` 的 `WS27-001/002/003` 执行与验收报告
- 输出单一可审计报告：`scratch/reports/release_closure_chain_full_m0_m12_result.json`

## 2. 关键脚本

- 全量收口入口：`scripts/release_closure_chain_full_m0_m12.py`
- 基础链（复用）：`scripts/release_closure_chain_full_m0_m7.py`（目标域已到 `M0-M11`）
- M12 子步骤脚本：
  - `scripts/manage_brainstem_control_plane_ws28_017.py`
  - `scripts/run_ws27_longrun_endurance_ws27_001.py`
  - `scripts/manage_ws27_subagent_cutover_ws27_002.py`
  - `scripts/run_ws27_oob_repair_drill_ws27_003.py`

## 3. 推荐执行顺序

1. 快速验收（远程首跑建议）

```powershell
.\.venv\Scripts\python.exe scripts/release_closure_chain_full_m0_m12.py `
  --quick-mode `
  --skip-m0-m5 --skip-m6-m7 --skip-m8 --skip-m9 --skip-m10
```

2. 全量执行（正式收口）

```powershell
.\.venv\Scripts\python.exe scripts/release_closure_chain_full_m0_m12.py
```

3. 若需仅验证 M12（已具备 M0-M11 远程证据时）

```powershell
.\.venv\Scripts\python.exe scripts/release_closure_chain_full_m0_m12.py `
  --skip-m0-m11 --quick-mode
```

4. 脑干托管入口单独验收（与全链同源脚本）

```bash
./.venv/bin/python scripts/manage_brainstem_control_plane_ws28_017.py \
  --action start \
  --output scratch/reports/ws28_brainstem_control_plane_start_ws28_017.json \
  --strict

./.venv/bin/python scripts/manage_brainstem_control_plane_ws28_017.py \
  --action status \
  --output scratch/reports/ws28_brainstem_control_plane_status_ws28_017.json \
  --strict
```

5. 脑干托管入口清理（可选）

```bash
./.venv/bin/python scripts/manage_brainstem_control_plane_ws28_017.py --action stop
```

## 4. 预期产物

1. `scratch/reports/release_closure_chain_full_m0_m12_result.json`
2. `scratch/reports/release_closure_chain_full_m0_m7_result.json`
3. `scratch/reports/ws27_72h_endurance_ws27_001.json`
4. `scratch/reports/ws28_brainstem_control_plane_start_ws28_017.json`
5. `scratch/reports/ws28_brainstem_control_plane_status_ws28_017.json`
6. `scratch/reports/ws27_subagent_cutover_plan_ws27_002.json`
7. `scratch/reports/ws27_subagent_cutover_apply_ws27_002.json`
8. `scratch/reports/ws27_subagent_cutover_status_ws27_002.json`
9. `scratch/reports/ws27_subagent_cutover_rollback_snapshot_ws27_002.json`
10. `scratch/reports/ws27_oob_repair_drill_ws27_003.json`
11. `scratch/reports/ws28_execution_governance_gate_ws28_021.json`
12. `scratch/reports/ws28_execution_governance_runtime_posture_ws28_021.json`
13. `scratch/reports/ws28_execution_governance_incidents_ws28_021.json`

## 5. 判定标准

- 主报告 `passed=true` 且 `failed_groups=[]`。
- `group_results` 至少包含：
  - `m0_m11`（未跳过时）
  - `m12_brainstem_control_plane`
  - `m12_endurance`
  - `m12_cutover`
  - `m12_oob_repair`
  - `m12_execution_governance`
- `m12_brainstem_control_plane` 检查项必须通过：
  - `start_passed=true`
  - `status_passed=true`
  - `start_spawn_or_already_running=true`
  - `heartbeat_gate=true`
  - `launcher_pid_alive=true`
  - `manager_state_exists=true`
  - `state_file_consistent=true`
  - `heartbeat_file_consistent=true`
- `m12_cutover` 检查项必须全部通过：
  - `subagent_runtime_enabled=true`
  - `rollout_percent_is_full=true`
  - `runtime_snapshot_ready=true`
  - `rollback_snapshot_exists=true`
- `m12_execution_governance` 检查项必须通过：
  - `runtime_governance_status_not_critical=true`
  - `incidents_governance_status_not_critical=true`
  - `critical_governance_issue_count_zero=true`
  - `governance_warning_ratio_within_budget=true`
  - `governance_rejection_ratio_within_budget=true`

## 6. 风险与说明

- `quick_mode` 仅用于快速回归，不替代正式放行验收。
- `WS27-001` 真实 72h 墙钟验收仍需远程环境单独补齐，不能仅依赖 quick-mode 等效执行。
