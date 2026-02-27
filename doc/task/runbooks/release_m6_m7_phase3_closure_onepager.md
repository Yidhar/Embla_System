# 发布收口一页清单（M6-M7 / Phase3）

文档状态：`phase3_release_closure_active`  
适用范围：`WS21 + WS22`（Sub-Agent Runtime / Scheduler Bridge）  
基准日期：`2026-02-24`

## 1. 当前收口快照

- `WS21` 状态：`done (6/6)`，见 `doc/task/21-ws-phase3-subagent-runtime-and-scaffold.md`
- `WS22` 状态：`done (4/4)`，见 `doc/task/22-ws-phase3-scheduler-bridge-and-rollout.md`
- 长稳基线报告：`scratch/reports/ws22_scheduler_longrun_baseline.json`

## 2. M6-M7 门禁

| 里程碑 | 门禁条件 | 核验命令 | 结论 |
|---|---|---|---|
| `M6` Phase3 执行内核 | Sub-Agent Runtime + Scaffold 事务回滚可用 | `.\.venv\Scripts\python.exe -m pytest -q autonomous/tests/test_subagent_runtime_ws21_002.py autonomous/tests/test_subagent_runtime_eventbus_ws21_003.py autonomous/tests/test_subagent_runtime_chaos_ws21_006.py autonomous/tests/test_subagent_runtime_spec_validation_ws22_005.py autonomous/tests/test_system_agent_subagent_rollout_ws22_006.py autonomous/tests/test_scaffold_engine_ws21_001.py autonomous/tests/test_contract_negotiation_ws21_004.py autonomous/tests/test_scaffold_verify_pipeline_ws21_005.py` | 通过 |
| `M7` Phase3 调度接管 | SystemAgent 桥接 + fail-open + lease 守护 + 长稳基线 | `.\.venv\Scripts\python.exe -m pytest -q autonomous/tests/test_system_agent_subagent_bridge_ws22_001.py autonomous/tests/test_system_agent_lease_guard_ws22_004.py autonomous/tests/test_system_agent_longrun_baseline_ws22_004.py` | 通过 |

## 3. Phase3 放行顺序（T0-T3）

统一入口（推荐）：
`.\.venv\Scripts\python.exe scripts/release_phase3_closure_chain_ws22_004.py`

发布链串接入口（Windows 后端打包前置门禁）：
`.\.venv\Scripts\python.exe scripts/build-win.py --phase3-closure`

全量总入口（M0-M8）：
`.\.venv\Scripts\python.exe scripts/release_closure_chain_full_m0_m7.py`

1. T0 执行 Phase3 回归
`.\.venv\Scripts\python.exe -m pytest -q autonomous/tests/test_subagent_runtime_ws21_002.py autonomous/tests/test_subagent_runtime_eventbus_ws21_003.py autonomous/tests/test_subagent_runtime_chaos_ws21_006.py autonomous/tests/test_subagent_runtime_spec_validation_ws22_005.py autonomous/tests/test_system_agent_subagent_rollout_ws22_006.py autonomous/tests/test_scaffold_engine_ws21_001.py autonomous/tests/test_contract_negotiation_ws21_004.py autonomous/tests/test_scaffold_verify_pipeline_ws21_005.py autonomous/tests/test_system_agent_subagent_bridge_ws22_001.py autonomous/tests/test_system_agent_lease_guard_ws22_004.py autonomous/tests/test_system_agent_longrun_baseline_ws22_004.py`

2. T1 生成或刷新 WS22 长稳报告
`.\.venv\Scripts\python.exe scripts/chaos_ws22_scheduler_longrun.py --rounds 120 --virtual-round-seconds 5 --fail-open-every 15 --lease-renew-every 20`

3. T2 执行 Phase3 闭环门禁校验
`.\.venv\Scripts\python.exe scripts/validate_phase3_closure_gate_ws22_004.py`

4. T3 文档一致性终检
`.\.venv\Scripts\python.exe scripts/validate_doc_consistency_ws16_006.py --strict`

## 4. 放行判定

- 放行条件：`T0-T3` 全通过，且 `scripts/validate_phase3_closure_gate_ws22_004.py` 返回 `passed=true`。
- 链路脚本放行条件：`scripts/release_phase3_closure_chain_ws22_004.py` 返回码为 `0`，且报告 `scratch/reports/ws22_phase3_release_chain_result.json` 中 `passed=true`。
- 当前判定：`Go`（已满足）。
