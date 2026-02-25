# 发布收口一页清单（M8 / WS23）

文档状态：`m8_release_closure_active`  
适用范围：`NGA-WS23-001 ~ NGA-WS23-006`（Brainstem 控制面独立化）  
基准日期：`2026-02-25`

## 1. 当前收口快照

- `WS23-001`：Brainstem Supervisor 独立入口 + 健康探针已落地。
- `WS23-002`：Watchdog 阈值动作已桥接 `ReleaseGateRejected(gate=watchdog)` 调度拒绝链。
- `WS23-003`：Immutable DNA 门禁已接入发布预检链（`T0A`）。
- `WS23-004`：KillSwitch OOB 冻结/探测预案导出脚本已落地。
- `WS23-005`：Workflow outbox -> Brainstem 事件桥接已落地并具备 smoke 报告。
- `WS23-006`：M8 门禁链脚本与本 runbook 已接入。

## 2. M8 门禁执行顺序（T0-T6）

统一入口（推荐）：
`.\.venv\Scripts\python.exe scripts/release_closure_chain_m8_ws23_006.py`

全量总入口（M0-M8，兼容脚本名）：
`.\.venv\Scripts\python.exe scripts/release_closure_chain_full_m0_m7.py`

1. T0 执行 WS23 目标回归
`.\.venv\Scripts\python.exe -m pytest -q tests/test_brainstem_supervisor_entry_ws23_001.py autonomous/tests/test_system_agent_watchdog_gate_ws23_002.py tests/test_ws23_003_immutable_dna_gate.py tests/test_export_killswitch_oob_bundle_ws23_004.py tests/test_brainstem_event_bridge_ws23_005.py autonomous/tests/test_system_agent_outbox_bridge_ws23_005.py -p no:tmpdir`

2. T1 生成 Brainstem Supervisor 干运行报告
`.\.venv\Scripts\python.exe scripts/run_brainstem_supervisor_ws23_001.py --mode ensure --dry-run --state-file scratch/runtime/brainstem_supervisor_state_ws23_001.json --output scratch/reports/brainstem_supervisor_entry_ws23_001.json`

3. T2 执行 Immutable DNA 门禁校验
`.\.venv\Scripts\python.exe scripts/validate_immutable_dna_gate_ws23_003.py --output scratch/reports/immutable_dna_gate_ws23_003_result.json`

4. T3 导出 KillSwitch OOB 预案
`.\.venv\Scripts\python.exe scripts/export_killswitch_oob_bundle_ws23_004.py --oob-allowlist 10.0.0.0/24 bastion.example.com --probe-targets 10.0.0.10 bastion.example.com --dns-allow --output scratch/reports/killswitch_oob_bundle_ws23_004.json`

5. T4 运行 outbox->Brainstem 桥接 smoke
`.\.venv\Scripts\python.exe scripts/run_outbox_brainstem_bridge_smoke_ws23_005.py --output scratch/reports/outbox_brainstem_bridge_ws23_005.json`

6. T5 执行 M8 闭环门禁
`.\.venv\Scripts\python.exe scripts/validate_m8_closure_gate_ws23_006.py --output-json scratch/reports/ws23_m8_closure_gate_result.json`

7. T6 文档一致性终检
`.\.venv\Scripts\python.exe scripts/validate_doc_consistency_ws16_006.py --strict`

## 3. 放行判定

- 放行条件：
  - `T0-T6` 全通过；
  - `scripts/validate_m8_closure_gate_ws23_006.py` 返回 `passed=true`；
  - `scratch/reports/ws23_m8_closure_gate_result.json` 中 `checks.*` 全为 `true`。
- 链路脚本放行条件：
  - `scripts/release_closure_chain_m8_ws23_006.py` 返回码 `0`；
  - `scratch/reports/release_closure_chain_m8_ws23_006_result.json` 中 `passed=true`。

## 4. 归档产物

- `scratch/reports/release_closure_chain_m8_ws23_006_result.json`
- `scratch/reports/ws23_m8_closure_gate_result.json`
- `scratch/reports/brainstem_supervisor_entry_ws23_001.json`
- `scratch/reports/immutable_dna_gate_ws23_003_result.json`
- `scratch/reports/killswitch_oob_bundle_ws23_004.json`
- `scratch/reports/outbox_brainstem_bridge_ws23_005.json`

