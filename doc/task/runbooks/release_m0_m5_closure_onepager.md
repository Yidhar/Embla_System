# 发布收口一页清单（M0-M5）

文档状态：`release_closure_active`  
适用范围：`doc/task` 当前执行板（76/76 done）  
基准日期：`2026-02-24`

## 1. 当前收口快照

- 任务执行板：`doc/task/09-execution-board.csv` -> `done=76`, `review=0`
- 风险台账：`doc/task/08-risk-closure-ledger.md` -> `R1-R16 全部 done`
- 文档一致性：`python scripts/validate_doc_consistency_ws16_006.py --strict` -> `0 issue`

## 2. M0-M5 门禁对账

| 里程碑 | 出场条件（来源：`01-program-roadmap-and-milestones.md`） | 当前证据 | 结论 |
|---|---|---|---|
| M0 | 任务模型完整、契约边界收敛、关键风险有归属 | `WS10/WS16` 全 done；`99-task-backlog.csv` + `09-execution-board.csv` 完整 | 通过 |
| M1 | `raw_result_ref` 可读、KillSwitch OOB、Artifact 配额保护 | `WS11-002/003/004/005` done；`WS14-009/010` done；`tests/test_native_tools_artifact_and_guard.py`、`tests/test_native_tools_ws11_003.py`、`tests/test_native_executor_guards.py` 通过 | 通过 |
| M2 | file_ast 并发治理、Sub-Agent 契约门禁、Double-Fork 回收 | `WS12-*`、`WS13-*`、`WS14-006` done；`tests/test_agentic_loop_contract_and_mutex.py`、`tests/test_workspace_txn_e2e_regression.py`、`tests/test_process_lineage.py` 通过 | 通过 |
| M3 | GC 证据链与预算守门生效 | `WS15-*`、`WS19-001..006/008` done；`tests/test_gc_*`、`autonomous/tests/test_working_memory_manager_ws19_004.py`、`autonomous/tests/test_router_arbiter_guard_ws19_008.py` 通过 | 通过 |
| M4 | 迁移收尾、兼容回退窗口、弃用路径审计 | `WS16-001..006` done；`WS20-004` done；`WS18-008` done；`tests/test_contract_rollout_ws16_005.py`、`tests/test_agentserver_deprecation_guard_ws16_002.py`、`tests/test_mcp_status_snapshot.py` 通过 | 通过 |
| M5 | 混沌演练、Canary 回滚、SLO/Runbook 完整 | `WS17-*`、`WS20-006` done；`tests/test_chaos_lock_failover.py`、`tests/test_chaos_sleep_watch.py`、`tests/test_chaos_runtime_storage.py`、`tests/test_canary_rollback_drill.py`、`tests/test_slo_snapshot_export.py`、`tests/test_desktop_release_compat_ws20_006.py` 通过 | 通过 |

## 3. 发布前执行顺序（T0-T5）

统一入口（推荐）：
`.\.venv\Scripts\python.exe scripts/release_closure_chain_m0_m5.py`

全量总入口（含 Phase3 M6-M7）：
`.\.venv\Scripts\python.exe scripts/release_closure_chain_full_m0_m7.py`

CI 接入（DoD）：
`.github/workflows/dod-check.yml` 已默认在 PR/Push 触发 `quick-mode`（`workflow_dispatch` 支持 `full/skip`）。

1. T0 基线校验  
   `python scripts/validate_doc_consistency_ws16_006.py --strict`
2. T1 安全与运行时回归  
   `python -m pytest -q tests/test_native_executor_guards.py tests/test_policy_firewall.py tests/test_global_mutex.py tests/test_process_lineage.py tests/test_native_tools_runtime_hardening.py tests/test_agentic_loop_contract_and_mutex.py -p no:tmpdir`
3. T2 契约与证据链回归  
   `python -m pytest -q tests/test_tool_contract.py tests/test_tool_schema_validation.py tests/test_native_tools_artifact_and_guard.py tests/test_native_tools_ws11_003.py tests/test_gc_budget_guard.py tests/test_gc_reader_bridge.py tests/test_gc_memory_card_injection.py -p no:tmpdir`
4. T3 API/BFF 与迁移回归  
   `python -m pytest -q tests/test_api_contract_ws20_001.py tests/test_sse_event_protocol_ws20_002.py tests/test_frontend_bff_regression_ws20_005.py tests/test_mcp_status_snapshot.py tests/test_contract_rollout_ws16_005.py tests/test_doc_consistency_ws16_006.py tests/test_sync_risk_verify_mapping_ws16_006.py tests/test_sync_risk_closure_ledger_ws16_006.py -p no:tmpdir`
5. T4 Autonomous 核心回归  
   `python -m pytest -q autonomous/tests/test_event_store_ws18_001.py autonomous/tests/test_workflow_store.py autonomous/tests/test_meta_agent_runtime_ws19_001.py autonomous/tests/test_router_engine_ws19_002.py autonomous/tests/test_llm_gateway_ws19_003.py autonomous/tests/test_working_memory_manager_ws19_004.py autonomous/tests/test_daily_checkpoint_ws19_007.py autonomous/tests/test_router_arbiter_guard_ws19_008.py autonomous/tests/test_event_replay_tool_ws18_003.py autonomous/tests/test_system_agent_release_flow.py -p no:tmpdir`
6. T5 发布运行工单产物  
   `python scripts/export_slo_snapshot.py`  
   `python scripts/desktop_release_compat_ws20_006.py --strict`  
   `python scripts/canary_rollback_drill.py --dry-run`

## 4. 非阻断项与注意事项

- 非阻断告警：`litellm` 相关 `DeprecationWarning/PydanticDeprecatedSince20`（当前不影响功能正确性）。
- Windows ACL 风险：若出现临时目录拒绝访问，按运维流程手工清理后重跑，不在自动流程中强制删除。

## 5. 放行判定

- 放行条件：`T0-T5` 全通过，且 `M0-M5` 结论全部为“通过”。
- 链路脚本放行条件：`scripts/release_closure_chain_m0_m5.py` 返回码为 `0`，且报告 `scratch/reports/release_closure_chain_m0_m5_result.json` 中 `passed=true`。
- 当前判定：`Go`（满足放行条件）。

补充：Phase3（`M6-M7`）收口请执行 `doc/task/runbooks/release_m6_m7_phase3_closure_onepager.md`。
