> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS15-005 实施记录（证据回读自动化链路）

## 任务信息
- 任务ID: `NGA-WS15-005`
- 标题: 证据回读自动化链路
- 状态: 已完成（最小可交付）

## 变更范围
- `system/gc_reader_bridge.py`（新增）
- `apiserver/agentic_tool_loop.py`
- `tests/test_gc_reader_bridge.py`（新增）

## 实施内容
1. 新增 GC Reader Bridge
- `build_gc_reader_followup_plan(...)` 从结果中解析：
  - `forensic_artifact_ref/raw_result_ref`
  - `fetch_hints`
  - `truncated` 与 tagged block
- 自动生成 `artifact_reader` follow-up call，并生成降级建议字符串。

2. 自动回读执行
- 在主工具执行后触发自动 follow-up。
- 限流：每轮最多 1 次（优先 error + line_range 场景）。
- 失败不阻塞主链路：追加结构化建议结果（包含建议调用）。

3. 策略细节
- 触发条件：有 ref 且预览不足，或 `status=error`（聚焦根因）。
- hint 优先级：`line_range` > `grep` > `jsonpath` > `preview`。

## 验证
- `uv --cache-dir .uv_cache run python -m pytest -q tests/test_gc_reader_bridge.py tests/test_gc_memory_card_injection.py tests/test_tool_contract.py`
- `uv --cache-dir .uv_cache run python -m ruff check apiserver/agentic_tool_loop.py system/gc_reader_bridge.py tests/test_gc_reader_bridge.py`

结果：通过。
