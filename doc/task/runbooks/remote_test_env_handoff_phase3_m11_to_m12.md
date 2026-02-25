# 远程测试环境交接清单（Phase3：M11 已完成，M12 待启动）

最后更新：2026-02-25  
适用分支：`modifier/naga`

## 1. 交接目标

- 在远程测试环境继续推进 `Phase3 Full`。
- 当前基线已到 `M11`（`NGA-WS26-006` 已完成）。
- 下一阶段从 `M12`（`NGA-WS27-001~006`）启动。

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

## 3. 关键提交（用于远程环境核对）

1. `229b638` `feat: add ws26 m11 closure gate and release chain`
2. `6170cc6` `docs: record ws26-006 m11 closure gate rollout`
3. `978757b` `feat: strengthen detached process cleanup for double-fork scenarios`
4. `4389b7f` `feat: wire lock scavenger scan into global mutex execution path`
5. `784a60a` `feat: enforce scaffold txn write path and fail-open guardrails`

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

## 5. 预期产物路径

1. `scratch/reports/ws26_runtime_snapshot_ws26_002.json`
2. `scratch/reports/ws26_m11_runtime_chaos_ws26_006.json`
3. `scratch/reports/ws26_m11_closure_gate_result.json`
4. `scratch/reports/release_closure_chain_m11_ws26_006_result.json`
5. `scratch/reports/release_closure_chain_full_m0_m7_result.json`

## 6. 当前缺口与下一阶段任务（M12）

1. `NGA-WS27-001` 72h 长稳耐久脚本与磁盘配额压测（未落地）
2. `NGA-WS27-002` Legacy -> SubAgent Full cutover + 回滚窗（未落地）
3. `NGA-WS27-003` OOB 抢修 runbook 演练（未落地）
4. `NGA-WS27-004` `release_closure_chain_full_m0_m12.py`（未落地）
5. `NGA-WS27-005` 文档一致性收口（M12）（未落地）
6. `NGA-WS27-006` Phase3 Full 放行报告与签署模板（未落地）

## 7. 重要说明（避免误判）

1. 当前仓库不存在“真实 72h 墙钟执行”的验收脚本；现有 long-run 基线主要是 `WS22` 的等效演练，不可替代 `WS27-001`。
2. 如远程环境出现 `scratch` 膨胀、锁文件或权限清理问题，按人工清理流程处理后继续，不在自动脚本中执行破坏性清理。
3. 继续开发时，优先保持“分片提交”节奏（功能提交与文档提交分离）。
