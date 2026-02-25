# M10 Event/GC 收口一页式执行清单（NGA-WS25-006）

## 1. 目标

- 目标任务：`NGA-WS25-006`
- 里程碑：`M10`
- 范围：Event Bus Topic/Replay/Cron-Alert + 关键证据保真 + 质量基线门禁

## 2. 执行顺序

```bash
python scripts/release_closure_chain_m10_ws25_006.py
```

若分步执行，按以下顺序：

```bash
python -m pytest -q autonomous/tests/test_topic_event_bus_ws25_001.py autonomous/tests/test_cron_alert_producer_ws25_002.py autonomous/tests/test_topic_event_bus_replay_idempotency_ws25_003.py autonomous/tests/test_ws25_event_gc_quality_baseline.py tests/test_run_event_gc_quality_baseline_ws25_005.py tests/test_tool_contract.py tests/test_episodic_memory.py -p no:tmpdir
python scripts/run_event_gc_quality_baseline_ws25_005.py --output scratch/reports/ws25_event_gc_quality_baseline.json
python scripts/validate_m10_closure_gate_ws25_006.py --event-gc-quality-report scratch/reports/ws25_event_gc_quality_baseline.json --output-json scratch/reports/ws25_m10_closure_gate_result.json
python scripts/validate_doc_consistency_ws16_006.py --strict
```

## 3. 全量链路接入

```bash
python scripts/release_closure_chain_full_m0_m7.py --m10-output scratch/reports/release_closure_chain_m10_ws25_006_result.json
```

## 4. 出口条件

- `scratch/reports/ws25_event_gc_quality_baseline.json` 中 `passed=true`
- `scratch/reports/ws25_m10_closure_gate_result.json` 中 `passed=true`
- `scratch/reports/release_closure_chain_m10_ws25_006_result.json` 中 `passed=true`
- 文档快照含 `NGA-WS25-003/004/005/006` 已落地记录
