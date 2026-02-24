# NGA-WS10-004 实施记录（统一工具回执模板与审计记录）

## 任务信息
- Task ID: `NGA-WS10-004`
- Title: 统一工具回执模板与审计记录
- 状态: 已完成（进入 review）

## 本次范围（仅 WS10-004）
1. Tool Receipt 标准模板落地
- `apiserver/agentic_tool_loop.py`
  - 新增 `_normalize_receipt_next_steps`、`_build_default_receipt_next_steps`
  - 新增 `_build_tool_receipt`，统一输出:
    - `risk`: `risk_level` / `execution_scope` / `requires_global_mutex` / `risk_items`
    - `budget`: `estimated_token_cost` / `budget_remaining`
    - `result`: `status` / `error_code` / `has_artifact` / `forensic_artifact_ref`
    - `next_steps`: 规范化或自动补齐默认建议
  - 新增 `_attach_tool_receipt`，确保结果行统一附带 `tool_receipt`

2. 执行链路全覆盖注入
- `apiserver/agentic_tool_loop.py`
  - `_execute_tool_call_with_retry` 在 schema enforce 后注入回执
  - `execute_tool_calls` 异常分支统一注入回执
  - `_build_validation_results` 的协议校验错误行统一注入回执
  - `_build_gc_reader_suggestion_result` 建议桥接行统一注入回执

3. 前端摘要与 LLM 注入对齐
- `apiserver/agentic_tool_loop.py`
  - `_summarize_results_for_frontend`:
    - 优先透传 `tool_receipt`
    - 若缺失则基于 `tool_call + result` 回填
  - `format_tool_results_for_llm`:
    - 增加 `[tool_receipt]` 文本区块，输出 risk/budget/result/next_steps 关键字段

4. 回归测试补齐（WS10-004）
- 新增 `tests/test_tool_receipt_ws10_004.py`
  - 错误路径默认 next steps + 风险项校验
  - 成功路径默认 next steps 校验
  - `_execute_tool_call_with_retry` 回执注入校验
  - `_summarize_results_for_frontend` 回填回执校验
  - `format_tool_results_for_llm` 回执区块注入校验

## 验证命令
- `.\.venv\Scripts\python.exe -m ruff check apiserver/agentic_tool_loop.py tests/test_tool_receipt_ws10_004.py`
  - 结果: `All checks passed`
- `powershell -ExecutionPolicy Bypass -File scripts/run_tests_safe.ps1 tests/test_tool_receipt_ws10_004.py tests/test_agentic_tool_loop_metadata.py tests/test_agentic_loop_contract_and_mutex.py tests/test_gc_memory_card_injection.py`
  - 结果: `18 passed`
- `powershell -ExecutionPolicy Bypass -File scripts/run_tests_safe.ps1 tests/test_native_executor_guards.py tests/test_policy_firewall.py tests/test_global_mutex.py tests/test_process_lineage.py tests/test_native_tools_runtime_hardening.py tests/test_agentic_loop_contract_and_mutex.py`
  - 结果: `56 passed`

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `apiserver/agentic_tool_loop.py; tests/test_tool_receipt_ws10_004.py; tests/test_agentic_tool_loop_metadata.py; tests/test_agentic_loop_contract_and_mutex.py; tests/test_gc_memory_card_injection.py; doc/task/implementation/NGA-WS10-004-implementation.md`
- `notes`:
  - `tool receipt template now covers retry/validation/gc-bridge/error branches, frontend summaries always carry receipt (or backfilled receipt), and llm injection includes standardized risk-budget-result-next_steps block`

## Date
2026-02-24
