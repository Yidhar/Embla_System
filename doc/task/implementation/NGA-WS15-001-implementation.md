# NGA-WS15-001 实施记录（关键证据字段抽取器）

## 任务信息
- 任务ID: `NGA-WS15-001`
- 标题: 关键证据字段抽取器
- 状态: 已完成（最小可交付）

## 变更范围
- `system/gc_evidence_extractor.py`（新增）
- `system/tool_contract.py`
- `tests/test_gc_evidence_extractor.py`（新增）
- `tests/test_tool_contract.py`

## 实施内容
1. 新增证据抽取模块 `gc_evidence_extractor`
- 统一输出 `GCEvidence`：
  - `trace_ids`
  - `error_codes`
  - `stack_tokens`
  - `paths`
  - `hex_addresses`
- 对外 API：
  - `extract_gc_evidence(payload, content_type, max_items_per_field=...)`
  - `build_gc_fetch_hints(evidence, content_type, max_hints=...)`

2. 抽取规则覆盖文本与 JSON
- `trace_id`：键值模式、行内 token、JSON trace 键递归抽取。
- `error_code`：`error_code/errorCode/errno/status_code`、`ERR_*`、HTTP 4xx/5xx。
- `stack token`：`at ...` 与 Python traceback `File ..., line ..., in ...`。
- `path`：Windows/UNC 路径、Unix 路径（含行列尾缀归一化）。
- `hex address`：`0x...` 与 `addr/address/ptr/pointer=...` 上下文模式。

3. 轻量接入 Tool Contract
- `_generate_fetch_hints(...)` 改为基于 `extract_gc_evidence(...)` 生成 evidence-aware hints。
- 结构化 artifact 分支在落盘后返回更高价值的二次读取提示，供后续 GC/排障链路复用。

## 验证
- `uv --cache-dir .uv_cache run python -m pytest -q tests/test_gc_evidence_extractor.py tests/test_tool_contract.py`
- `uv --cache-dir .uv_cache run python -m ruff check system/gc_evidence_extractor.py system/tool_contract.py tests/test_gc_evidence_extractor.py tests/test_tool_contract.py`

结果：通过。
