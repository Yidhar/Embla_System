# NGA-WS12-005 实施记录（Router 仲裁升级路径）

## 任务信息
- 任务ID: `NGA-WS12-005`
- 标题: Router 仲裁升级路径
- 状态: 已完成（最小可交付）

## 变更范围
- `system/router_arbiter.py`（新增）
- `apiserver/agentic_tool_loop.py`
- `tests/test_agentic_loop_contract_and_mutex.py`

## 实施内容
1. 新增 `router_arbiter` 轻量模块
- 固定阈值 `MAX_DELEGATE_TURNS = 3`。
- 仅在 `native + workspace_txn_apply` 且错误文本包含 `workspace transaction failed` 与 `conflict_ticket=` 时计入冲突轮次。
- 输出结构化信号字段：`conflict_ticket`、`delegate_turns`、`freeze`、`hitl`、`escalated`、`reason`。

2. 在工具重试主流程接入仲裁判断
- 在 `_execute_tool_call_with_retry` 的 error 分支中调用 `evaluate_workspace_conflict_retry(...)`。
- 未达阈值：保留原有 retry/backoff。
- 达到阈值：立刻停止继续重试并返回升级信号，避免预算烧穿型活锁。

3. 透传前端可消费字段
- 在结果摘要中增加可选字段：`conflict_ticket`、`delegate_turns`、`freeze`、`hitl`、`router_arbiter`。
- 保持后向兼容（新增字段，不破坏原字段）。

4. 循环级 stop reason 接入
- 检测到 `router_arbiter.escalated=true` 时，`run_agentic_loop` 触发 `router_arbiter_escalation`，终止继续工具重试并进入 summary/stop 决策。

## 验证
- `uv --cache-dir .uv_cache run python -m pytest -q tests/test_agentic_loop_contract_and_mutex.py`
- `uv --cache-dir .uv_cache run python -m ruff check apiserver/agentic_tool_loop.py system/router_arbiter.py tests/test_agentic_loop_contract_and_mutex.py`

结果：通过。
