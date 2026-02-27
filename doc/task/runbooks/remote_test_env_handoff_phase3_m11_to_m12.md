# 远程测试环境交接清单（Phase3：M11 -> M12 历史基线）

最后更新：2026-02-25  
适用分支：`modifier/naga`

## 1. 交接目标

- 在远程测试环境继续推进 `Phase3 Full`。
- 当前基线已到 `M11`（`NGA-WS26-006` 已完成）。
- 当前进入 `M12`（`NGA-WS27-001~006`）推进期。
- 本机补充进展（2026-02-25）：`M0-M12` 全链已通过，`WS27-005/006` 已严格模式校验通过。

## 2. 当前已完成范围（落地状态）

1. `NGA-WS26-001` 写路径强制收敛到 `Scaffold/Txn`
- 代码：`autonomous/system_agent.py`, `autonomous/tools/subagent_runtime.py`
- 配置：`autonomous/config/autonomous_config.yaml`

2. `NGA-WS26-002` rollout/fail-open/lease 指标统一导出
- 代码：`scripts/export_slo_snapshot.py`, `scripts/export_ws26_runtime_snapshot_ws26_002.py`

3. `NGA-WS26-003` fail-open 预算超限自动降级
- 代码：`autonomous/system_agent.py`
- 关键事件：`SubAgentRuntimeAutoDegraded`, `ReleaseGateRejected(gate=fail_open_budget)`

4. `NGA-WS26-004` 锁泄漏清道夫与 fencing 联动
- 代码：`apiserver/agentic_tool_loop.py`
- 关键字段：`_mutex_scavenge_report`, `mutex_scavenge_report`

5. `NGA-WS26-005` double-fork/脱离进程树回收强化
- 代码：`system/process_lineage.py`
- 行为：detached 命令在 root kill 成功时仍执行 signature cleanup

6. `NGA-WS26-006` M11 混沌门禁（本轮完成）
- 门禁评估器：`autonomous/ws26_release_gate.py`
- 混沌报告脚本：`scripts/run_ws26_m11_runtime_chaos_suite_ws26_006.py`
- 门禁校验入口：`scripts/validate_m11_closure_gate_ws26_006.py`
- M11 收口链：`scripts/release_closure_chain_m11_ws26_006.py`
- 全量链扩展：`scripts/release_closure_chain_full_m0_m7.py`（目标域已到 `M0-M11`）

7. `NGA-WS27-001` 72h 长稳 + 磁盘配额压测（首版已落地）
- baseline harness：`autonomous/ws27_longrun_endurance.py`
- 执行入口：`scripts/run_ws27_longrun_endurance_ws27_001.py`
- 说明：当前为“虚拟 72h 等效执行”基线，远程环境仍需补真实墙钟验收记录

8. `NGA-WS27-002` Legacy -> SubAgent Full cutover + 回滚窗（首版已落地）
- cutover 管理脚本：`scripts/manage_ws27_subagent_cutover_ws27_002.py`
- runbook：`doc/task/runbooks/release_m12_cutover_rollback_onepager_ws27_002.md`
- 特性：支持 `plan/apply/rollback/status`，且 `rollback` 在快照缺失时可强制安全回退到 legacy

9. `NGA-WS27-003` OOB 抢修 runbook 演练（首版已落地）
- OOB 演练脚本：`scripts/run_ws27_oob_repair_drill_ws27_003.py`
- runbook：`doc/task/runbooks/release_m12_oob_repair_drill_onepager_ws27_003.md`
- 特性：覆盖快照恢复回滚、快照缺失强制 legacy 降级、OOB bundle 导出校验三条路径

10. `NGA-WS27-004` M0-M12 全量收口链（首版已落地）
- 全量收口脚本：`scripts/release_closure_chain_full_m0_m12.py`
- runbook：`doc/task/runbooks/release_m12_full_chain_m0_m12_onepager_ws27_004.md`
- 特性：复用 `M0-M11` 基础链并串联 `WS27-001/002/003`，输出统一 `M0-M12` 报告

## 3. 关键提交（用于远程环境核对）

1. `6bca116` `feat: add ws27-004 full m0-m12 release closure chain`
2. `7cf7719` `fix: resolve ws27-003 ruff warnings`
3. `8f12416` `docs: record ws27-003 m12 oob drill rollout`
4. `a117d0c` `feat: add ws27-003 oob repair drill harness`
5. `c2e837e` `docs: record ws27-001 and ws27-002 m12 rollout progress`
6. `bd8cd65` `feat: add ws27-002 cutover and rollback manager`
7. `e2e53c4` `feat: add ws27-001 endurance baseline harness and cli`
8. `229b638` `feat: add ws26 m11 closure gate and release chain`
9. `6170cc6` `docs: record ws26-006 m11 closure gate rollout`
10. `978757b` `feat: strengthen detached process cleanup for double-fork scenarios`

## 4. 远程环境启动与验证顺序

1. 环境准备

```powershell
uv sync
```

2. 先跑 WS26 门禁链最小回归（建议）

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  autonomous/tests/test_ws26_release_gate.py `
  tests/test_run_ws26_m11_runtime_chaos_suite_ws26_006.py `
  tests/test_release_closure_chain_m11_ws26_006.py `
  tests/test_release_closure_chain_full_m0_m7.py -p no:tmpdir
```

3. 执行 M11 收口链

```powershell
.\.venv\Scripts\python.exe scripts/release_closure_chain_m11_ws26_006.py
```

4. 仅执行全量链中的 M11 组（远程初次验收建议）

```powershell
.\.venv\Scripts\python.exe scripts/release_closure_chain_full_m0_m7.py `
  --skip-m0-m5 --skip-m6-m7 --skip-m8 --skip-m9 --skip-m10
```

5. 执行 WS27-001（快速演练参数）

```powershell
.\.venv\Scripts\python.exe scripts/run_ws27_longrun_endurance_ws27_001.py `
  --target-hours 0.02 --virtual-round-seconds 6 --artifact-payload-kb 256 `
  --max-total-size-mb 1 --max-single-artifact-mb 1 --max-artifact-count 256 `
  --high-watermark-ratio 0.8 --low-watermark-ratio 0.5 --critical-reserve-ratio 0.1 `
  --normal-priority-every 3 --high-priority-every 8
```

6. 执行 WS27-002 cutover 计划 + 应用 + 状态检查

```powershell
.\.venv\Scripts\python.exe -m scripts.manage_ws27_subagent_cutover_ws27_002 `
  --action plan `
  --runtime-snapshot-report scratch/reports/ws26_runtime_snapshot_ws26_002.json `
  --output scratch/reports/ws27_subagent_cutover_plan_ws27_002.json

.\.venv\Scripts\python.exe -m scripts.manage_ws27_subagent_cutover_ws27_002 `
  --action apply `
  --rollout-percent 100 `
  --disable-fail-open `
  --output scratch/reports/ws27_subagent_cutover_apply_ws27_002.json

.\.venv\Scripts\python.exe -m scripts.manage_ws27_subagent_cutover_ws27_002 `
  --action status `
  --runtime-snapshot-report scratch/reports/ws26_runtime_snapshot_ws26_002.json `
  --output scratch/reports/ws27_subagent_cutover_status_ws27_002.json
```

7. 执行 WS27-003 OOB 抢修演练

```powershell
.\.venv\Scripts\python.exe scripts/run_ws27_oob_repair_drill_ws27_003.py `
  --repo-root . `
  --output scratch/reports/ws27_oob_repair_drill_ws27_003.json `
  --scratch-root scratch/ws27_oob_repair_drill `
  --rollback-window-minutes 180 `
  --oob-allowlist 10.0.0.0/24 bastion.example.com `
  --probe-targets 10.0.0.10 bastion.example.com
```

8. 执行 WS27-004 M0-M12 全量收口链（远程快速验收建议）

```powershell
.\.venv\Scripts\python.exe scripts/release_closure_chain_full_m0_m12.py `
  --quick-mode `
  --skip-m0-m5 --skip-m6-m7 --skip-m8 --skip-m9 --skip-m10
```

## 5. 预期产物路径

1. `scratch/reports/ws26_runtime_snapshot_ws26_002.json`
2. `scratch/reports/ws26_m11_runtime_chaos_ws26_006.json`
3. `scratch/reports/ws26_m11_closure_gate_result.json`
4. `scratch/reports/release_closure_chain_m11_ws26_006_result.json`
5. `scratch/reports/release_closure_chain_full_m0_m7_result.json`
6. `scratch/reports/ws27_72h_endurance_ws27_001.json`
7. `scratch/reports/ws27_subagent_cutover_plan_ws27_002.json`
8. `scratch/reports/ws27_subagent_cutover_apply_ws27_002.json`
9. `scratch/reports/ws27_subagent_cutover_status_ws27_002.json`
10. `scratch/reports/ws27_subagent_cutover_rollback_snapshot_ws27_002.json`
11. `scratch/reports/ws27_oob_repair_drill_ws27_003.json`
12. `scratch/ws27_oob_repair_drill/*/case_snapshot_recovery/repo/scratch/reports/ws27_drill_case1_plan.json`
13. `scratch/ws27_oob_repair_drill/*/case_snapshot_recovery/repo/scratch/reports/ws27_drill_case1_apply.json`
14. `scratch/ws27_oob_repair_drill/*/case_snapshot_recovery/repo/scratch/reports/ws27_drill_case1_rollback.json`
15. `scratch/ws27_oob_repair_drill/*/case_force_legacy_fallback/repo/scratch/reports/ws27_drill_case2_rollback.json`
16. `scratch/ws27_oob_repair_drill/*/case_oob_bundle_export/ws27_drill_oob_bundle.json`
17. `scratch/reports/release_closure_chain_full_m0_m12_result.json`

## 6. 当前缺口与下一阶段任务（M12）

1. `NGA-WS27-001` 72h 长稳耐久脚本与磁盘配额压测（首版已落地；待补“真实 72h 墙钟”验收记录）
2. `NGA-WS27-002` Legacy -> SubAgent Full cutover + 回滚窗（首版已落地；待补远程灰度放量演练记录）
3. `NGA-WS27-003` OOB 抢修 runbook 演练（首版已落地；待补远程环境演练留痕与操作录像）
4. `NGA-WS27-004` `release_closure_chain_full_m0_m12.py`（首版已落地；已完成本机全链通过，待补远程执行记录）
5. `NGA-WS27-005` 文档一致性收口（M12）（已落地；`--strict` 可通过）
6. `NGA-WS27-006` Phase3 Full 放行报告与签署模板（已落地；`--strict` 可通过）

## 7. 重要说明（避免误判）

1. 当前仓库已新增 `WS27-001` 虚拟 72h 等效脚本，但尚无“连续 72h 墙钟执行完成”的远程验收记录；放行前需补齐真实墙钟报告。
2. 如远程环境出现 `scratch` 膨胀、锁文件或权限清理问题，按人工清理流程处理后继续，不在自动脚本中执行破坏性清理。
3. 继续开发时，优先保持“分片提交”节奏（功能提交与文档提交分离）。
4. `doc/task/09-execution-board.csv` 与 `doc/task/99-task-backlog.csv` 现为 `M0-M12` 统一状态源；`doc/task/23-phase3-full-execution-board.csv` 保留为 Phase3 快照视图，用于历史核对。
