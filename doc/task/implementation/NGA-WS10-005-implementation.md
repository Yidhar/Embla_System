# NGA-WS10-005 实施记录（风险门禁与审批钩子收敛）

## 任务信息
- Task ID: `NGA-WS10-005`
- Title: 风险门禁与审批钩子收敛
- 状态: 已完成（进入 review）

## 本次范围（仅 WS10-005）
1. 风险门禁判定器落地（Agentic Loop 入口统一）
- `apiserver/agentic_tool_loop.py`
  - 新增风险错误码：
    - `E_RISK_APPROVAL_REQUIRED`
    - `E_RISK_POLICY_BLOCKED`
  - 新增高风险映射与审批策略默认值：
    - `write_repo -> on-request`
    - `deploy -> on-request`
    - `secrets -> always`
    - `self_modify -> always`
  - 新增 `_evaluate_risk_gate`：
    - 统一解析 `risk_level + approvalPolicy + approval_granted`
    - 高风险策略禁用（`never/disabled/...`）直接阻断
    - `secrets/self_modify` 默认要求显式审批（未审批即阻断）
  - 在 `_execute_tool_call_with_retry` 执行前接入风险门禁：
    - 阻断时返回结构化错误并附带 `approval_hook`
    - 阻断错误不进入重试链路（避免无效重试）

2. 审批钩子在回执模板中结构化输出
- `apiserver/agentic_tool_loop.py`
  - `tool_receipt` 新增 `approval` 区块：
    - `required/policy/granted`
  - `risk_items` 纳入审批相关标记：
    - `approval_hook:<policy>`
    - `approval_required_gate`
    - `risk_policy_block_gate`
  - `format_tool_results_for_llm` 新增审批行：
    - `approval.required/policy/granted`

3. native 参数白名单兼容审批字段
- `system/policy_firewall.py`
  - 在 `run_cmd/write_file/workspace_txn_apply` 的严格参数白名单中增加：
    - `approvalPolicy`
    - `approval_policy`
    - `approval_granted`
    - `approved`

4. 回归测试补齐（WS10-005）
- 新增 `tests/test_risk_gate_ws10_005.py`
  - 写仓高风险默认审批钩子注入
  - 高风险 `approvalPolicy=never` 阻断
  - `secrets` 未显式审批阻断
  - `secrets` 显式审批后放行
- 更新 `tests/test_policy_firewall.py`
  - 覆盖审批字段在 `run_cmd` 下的白名单兼容

## 验证命令
- `.\.venv\Scripts\python.exe -m ruff check apiserver/agentic_tool_loop.py system/policy_firewall.py tests/test_risk_gate_ws10_005.py tests/test_policy_firewall.py tests/test_tool_receipt_ws10_004.py`
  - 结果: `All checks passed`
- `powershell -ExecutionPolicy Bypass -File scripts/run_tests_safe.ps1 tests/test_risk_gate_ws10_005.py tests/test_policy_firewall.py tests/test_tool_receipt_ws10_004.py tests/test_agentic_loop_contract_and_mutex.py tests/test_global_mutex.py tests/test_native_executor_guards.py tests/test_process_lineage.py tests/test_native_tools_runtime_hardening.py tests/test_gc_memory_card_injection.py`
  - 结果: `69 passed`

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `apiserver/agentic_tool_loop.py; system/policy_firewall.py; tests/test_risk_gate_ws10_005.py; tests/test_policy_firewall.py; doc/task/implementation/NGA-WS10-005-implementation.md`
- `notes`:
  - `risk gate now normalizes approval hooks by risk_level, blocks disabled-policy high-risk calls and unapproved secrets/self_modify calls, and exposes approval state in tool_receipt + llm injection`

## Date
2026-02-24
