# NGA-WS15-003 实施记录（GC 注入策略改造）

## 任务信息
- 任务ID: `NGA-WS15-003`
- 标题: GC 注入策略改造
- 状态: 已完成（最小可交付）

## 变更范围
- `system/gc_memory_card.py`（新增）
- `apiserver/agentic_tool_loop.py`
- `tests/test_gc_memory_card_injection.py`（新增）

## 实施内容
1. 新增“记忆索引卡片”构建模块
- 从工具结果中优先提取：
  - `narrative_summary`
  - `forensic_artifact_ref/raw_result_ref`
  - `fetch_hints`
- 自动生成 `artifact_reader(...)` 回读建议（`jsonpath/grep/line_range/preview`）。

2. LLM 注入逻辑改造
- `format_tool_results_for_llm(...)` 改为：
  - 有可回读 ref 时输出索引卡片；
  - 无 ref 时保留旧格式输出（向后兼容）。

3. 卡片格式
- 包含 `tool/status`、摘要、证据引用、`fetch_hints` 与 `ref_readback`，满足“索引卡片 + 可回读 ref”目标。

## 验证
- `uv --cache-dir .uv_cache run python -m pytest -q tests/test_gc_memory_card_injection.py tests/test_agentic_loop_contract_and_mutex.py`
- `uv --cache-dir .uv_cache run python -m ruff check apiserver/agentic_tool_loop.py system/gc_memory_card.py tests/test_gc_memory_card_injection.py`

结果：通过。
