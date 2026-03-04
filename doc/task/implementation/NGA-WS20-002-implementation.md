> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS20-002 实施记录（SSE 事件协议统一）

## 任务信息
- Task ID: `NGA-WS20-002`
- Title: SSE 事件协议统一
- 状态: 已完成（进入 review）

## 本次范围（仅 WS20-002）
1. SSE 统一事件信封
- `apiserver/agentic_tool_loop.py`
  - `_format_sse_event` 统一注入：
    - `schema_version = ws20-002-v1`
    - `event_ts`（毫秒时间戳）
  - 所有 loop 侧事件（`tool_calls/tool_results/round_*` 等）自动继承统一信封字段

2. `tool_calls` 字段稳定化
- `apiserver/agentic_tool_loop.py`
  - 新增 `_build_tool_call_descriptions`
  - 输出统一字段（即使为空也保留）：
    - `agentType/service_name/tool_name/message/call_id/risk_level/execution_scope/requires_global_mutex`

3. `tool_results` 摘要统一预览字段
- `apiserver/agentic_tool_loop.py`
  - `_summarize_results_for_frontend` 新增始终可用的 `preview`
  - 保留 legacy/new 合同字段兼容（`result` / `narrative_summary`）

4. 前端事件类型同步
- `frontend/src/utils/encoding.ts`
  - `StreamChunk` 增加 `schema_version`、`event_ts`
  - `calls/results` 类型与后端统一协议对齐（稳定键 + 可选兼容键）

5. 协议回归测试
- 新增 `tests/test_llm_stream_json_protocol_ws28_035.py`
  - 事件信封版本字段校验
  - `tool_calls` 标准字段校验
  - `tool_results.preview` 稳定字段校验

## 验证命令
- `.\.venv\Scripts\python.exe -m ruff check apiserver/agentic_tool_loop.py tests/test_llm_stream_json_protocol_ws28_035.py`
  - 结果: `All checks passed`
- `powershell -ExecutionPolicy Bypass -File scripts/run_tests_safe.ps1 tests/test_llm_stream_json_protocol_ws28_035.py tests/test_tool_receipt_ws10_004.py tests/test_risk_gate_ws10_005.py tests/test_gc_memory_card_injection.py tests/test_contract_rollout_ws16_005.py tests/test_agentic_loop_contract_and_mutex.py`
  - 结果: `28 passed`
- `cd frontend; npx eslint src/utils/encoding.ts`
  - 结果: `passed`
  - 说明: `npm run lint` 在当前仓库会触发 ESLint formatter `RangeError: Invalid string length`（历史问题），因此对变更文件执行定向 lint。

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `apiserver/agentic_tool_loop.py; frontend/src/utils/encoding.ts; tests/test_llm_stream_json_protocol_ws28_035.py; doc/task/implementation/NGA-WS20-002-implementation.md`
- `notes`:
  - `sse protocol now carries schema_version+event_ts envelope, tool_calls payload is key-stable, and tool_results always includes preview for frontend single-branch rendering`

## Date
2026-02-24
