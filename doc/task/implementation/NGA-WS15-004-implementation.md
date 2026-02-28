> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS15-004 实施记录（GC 预算守门与回路防抖）

## 任务信息
- 任务ID: `NGA-WS15-004`
- 标题: GC 预算守门与回路防抖
- 状态: 已完成（最小可交付）

## 变更范围
- `system/gc_budget_guard.py`（新增）
- `apiserver/agentic_tool_loop.py`
- `tests/test_gc_budget_guard.py`（新增）

## 实施内容
1. 新增 `GCBudgetGuard`
- 基于短窗口重复失败指纹做防抖。
- 指纹由 `tool_name + artifact_ref + hint + normalized_error_text` 组成。
- 默认阈值：`repeat_threshold=3`、`window_size=6`（支持配置读取和 clamp）。

2. 主循环接入
- 在每轮执行后观察 GC 相关结果，更新 guard 计数。
- 命中阈值后触发：
  - `stop_reason=gc_budget_guard_hit`
  - `guardrail` 事件（携带指纹、阈值、计数等）
  - 前端 `tool_results` 摘要补充 `gc_budget_guard/guard_hit` 字段。

3. 进展判定
- 普通成功会重置重复计数。
- `gc_reader_bridge` 的“建议型成功”不视为进展，避免被误判清零。

## 验证
- `uv --cache-dir .uv_cache run python -m pytest -q tests/test_gc_budget_guard.py tests/test_agentic_loop_contract_and_mutex.py`
- `uv --cache-dir .uv_cache run python -m ruff check apiserver/agentic_tool_loop.py system/gc_budget_guard.py tests/test_gc_budget_guard.py`

结果：通过。
