# NGA-WS15-002 实施记录（叙事摘要与证据引用分离）

## 任务信息
- 任务ID: `NGA-WS15-002`
- 标题: 叙事摘要与证据引用分离
- 状态: 已完成（最小可交付）

## 变更范围
- `system/tool_contract.py`
- `apiserver/native_tools.py`
- `apiserver/agentic_tool_loop.py`
- `tests/test_tool_contract.py`

## 实施内容
1. `ToolResultEnvelope` 新增分离字段
- `narrative_summary`: 面向上下文压缩与叙事展示
- `forensic_artifact_ref`: 面向证据回读与排障追踪

2. 保持向后兼容
- 保留历史字段：`display_preview`、`raw_result_ref`。
- 通过 `__post_init__` 做兼容映射：
  - `narrative_summary <-> display_preview`
  - `forensic_artifact_ref <-> raw_result_ref`

3. 结果构建链路接入
- `build_tool_result_with_artifact(...)` 在结构化大输出下同时返回 `narrative_summary` 与 `forensic_artifact_ref`。
- 小输出场景保持原行为，新增字段自动与旧字段一致。

4. 读取与协议透传
- `artifact_reader` 支持 `forensic_artifact_ref` 入参。
- `agentic_tool_loop` 的 native tool schema 增加 `forensic_artifact_ref` 字段声明。
- `native_tools` 输出中显式展示 `[narrative_summary]` 与 `[forensic_artifact_ref]`。

## 验证
- `uv --cache-dir .uv_cache run python -m pytest -q tests/test_tool_contract.py`
- `uv --cache-dir .uv_cache run python -m ruff check system/tool_contract.py apiserver/native_tools.py apiserver/agentic_tool_loop.py tests/test_tool_contract.py`

结果：通过。
