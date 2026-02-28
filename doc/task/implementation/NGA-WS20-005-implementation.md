> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS20-005 实施记录（前后端联调回归套件）

## 任务信息
- Task ID: `NGA-WS20-005`
- Title: 前后端联调回归套件
- 状态: 已完成（进入 review）

## 本次范围（仅 WS20-005）
1. 新增联调回归测试套件
- 新增 `tests/test_frontend_bff_regression_ws20_005.py`
- 覆盖三类回归能力：
  - 合同测试（API version/contract headers/deprecation 链路）
  - SSE 协议回归（schema_version/event_ts/tool_result preview）
  - MCP 状态回归（runtime snapshot + task filter）

2. 错误场景回归
- 覆盖非法 native 调用参数：
  - `run_cmd` 缺失 command 时返回 `E_SCHEMA_INPUT_INVALID`
- 覆盖工具结果协议损坏场景：
  - 缺失必要字段时 `_enforce_tool_result_schema` 产出 `E_SCHEMA_OUTPUT_INVALID`

3. 与既有 WS20 测试协同
- 复用并联跑：
  - `tests/test_api_contract_ws20_001.py`
  - `tests/test_sse_event_protocol_ws20_002.py`
  - `tests/test_mcp_status_snapshot.py`
- 形成“合同 + 协议 + 状态 + 错误”一体化回归入口。

## 验证命令
- `.\.venv\Scripts\python.exe -m ruff check tests/test_frontend_bff_regression_ws20_005.py`
  - 结果: `All checks passed!`
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_frontend_bff_regression_ws20_005.py tests/test_api_contract_ws20_001.py tests/test_sse_event_protocol_ws20_002.py tests/test_mcp_status_snapshot.py`
  - 结果: `13 passed, 0 failed`
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_agentserver_deprecation_guard_ws16_002.py tests/test_native_executor_guards.py tests/test_policy_firewall.py tests/test_global_mutex.py tests/test_process_lineage.py tests/test_native_tools_runtime_hardening.py tests/test_agentic_loop_contract_and_mutex.py tests/test_dna_change_audit_ws18_007.py tests/test_immutable_dna_ws18_006.py tests/test_loop_cost_guard_ws18_005.py tests/test_watchdog_daemon_ws18_004.py tests/test_frontend_bff_regression_ws20_005.py tests/test_api_contract_ws20_001.py tests/test_sse_event_protocol_ws20_002.py tests/test_mcp_status_snapshot.py autonomous/tests/test_router_engine_ws19_002.py autonomous/tests/test_event_replay_tool_ws18_003.py autonomous/tests/test_llm_gateway_ws19_003.py autonomous/tests/test_working_memory_manager_ws19_004.py`
  - 结果: `100 passed, 0 failed`

## 交付结果与验收对应
- deliverables“合同测试 + SSE 回归 + 错误场景回归”：已形成统一测试套件并纳入回归链路。
- acceptance“核心链路回归全通过”：WS20 关键链路与跨模块核心链路已全部通过。
- rollback“发布前锁定版本”：该套件可直接作为发布门禁条件固定在 CI。

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `tests/test_frontend_bff_regression_ws20_005.py; tests/test_api_contract_ws20_001.py; tests/test_sse_event_protocol_ws20_002.py; tests/test_mcp_status_snapshot.py; doc/task/implementation/NGA-WS20-005-implementation.md`
- `notes`:
  - `frontend-bff integration regression suite now gates api-contract headers, sse envelope compatibility, mcp runtime snapshot consistency, and schema error scenarios for invalid tool calls/results`

## Date
2026-02-24
