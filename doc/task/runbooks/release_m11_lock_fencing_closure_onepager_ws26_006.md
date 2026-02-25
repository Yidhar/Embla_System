# M11 锁与运行时混沌收口一页式执行清单（NGA-WS26-006）

## 1. 目标

- 目标任务：`NGA-WS26-006`
- 里程碑：`M11`
- 范围：fail-open 预算降级 + 锁泄漏清道夫/fencing + logrotate/sleep_watch + double-fork 回收

## 2. 执行顺序

```bash
python scripts/release_closure_chain_m11_ws26_006.py
```

若分步执行，按以下顺序：

```bash
python -m pytest -q autonomous/tests/test_system_agent_fail_open_budget_ws26_003.py autonomous/tests/test_ws26_release_gate.py tests/test_agentic_loop_contract_and_mutex.py tests/test_chaos_lock_failover.py tests/test_chaos_sleep_watch.py tests/test_process_lineage.py tests/test_export_ws26_runtime_snapshot_ws26_002.py -p no:tmpdir
python scripts/export_ws26_runtime_snapshot_ws26_002.py --output scratch/reports/ws26_runtime_snapshot_ws26_002.json
python scripts/run_ws26_m11_runtime_chaos_suite_ws26_006.py --output scratch/reports/ws26_m11_runtime_chaos_ws26_006.json
python scripts/validate_m11_closure_gate_ws26_006.py --runtime-snapshot-report scratch/reports/ws26_runtime_snapshot_ws26_002.json --m11-chaos-report scratch/reports/ws26_m11_runtime_chaos_ws26_006.json --output-json scratch/reports/ws26_m11_closure_gate_result.json
python scripts/validate_doc_consistency_ws16_006.py --strict
```

## 3. 全量链路接入

```bash
python scripts/release_closure_chain_full_m0_m7.py --m11-output scratch/reports/release_closure_chain_m11_ws26_006_result.json
```

## 4. 出口条件

- `scratch/reports/ws26_runtime_snapshot_ws26_002.json` 中 `passed=true`
- `scratch/reports/ws26_m11_runtime_chaos_ws26_006.json` 中 `passed=true`
- `scratch/reports/ws26_m11_closure_gate_result.json` 中 `passed=true`
- `scratch/reports/release_closure_chain_m11_ws26_006_result.json` 中 `passed=true`
- 文档快照含 `NGA-WS26-003/004/005/006` 已落地记录
