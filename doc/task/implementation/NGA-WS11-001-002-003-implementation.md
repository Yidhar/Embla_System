# NGA-WS11-001/002/003 实施记录

## 任务信息
- 任务ID: NGA-WS11-001, NGA-WS11-002, NGA-WS11-003
- 标题: Artifact 元数据模型、artifact_reader、os_bash(fetch_hints)
- 优先级: P0
- 阶段: M1
- 状态: ✅ 001/002 已完成；🟡 003 已进入可用态（review）

## 代码改动

### 1) Artifact 持久化主链接入（WS11-001）
- 文件: `system/tool_contract.py`
- 变更:
  1. `build_tool_result_with_artifact()` 增加 `priority` 参数。
  2. 结构化大输出走真实 Artifact Store 落盘，不再返回占位 ref。
  3. 写入失败时返回可读 preview 并标记 `artifact_persist_failed=true`，避免主链路中断。
  4. 新增 `source_tool/source_call_id/source_trace_id` 元数据写入。

### 2) artifact_reader 二次读取工具（WS11-002）
- 文件: `apiserver/native_tools.py`
- 变更:
  1. 新增 native 工具 `artifact_reader`。
  2. 支持模式:
     - `preview`
     - `line_range`
     - `grep`
     - `jsonpath`（支持 `$..key` 与 `$.a.b[0]` 简化路径）
  3. 输出包含 artifact 元数据（type/size/ttl/access/fetch_hints）。

### 3) os_bash 结果封装与 fetch_hints（WS11-003）
- 文件: `apiserver/native_tools.py`
- 变更:
  1. `os_bash` 作为 `run_cmd` 别名接入。
  2. 对 JSON/CSV/XML stdout 自动识别并调用 `build_tool_result_with_artifact()`。
  3. 返回 `raw_result_ref + fetch_hints + display_preview` 的统一文本回执。

## 验证
- 新增测试:
  - `tests/test_native_tools_artifact_and_guard.py::test_artifact_reader_jsonpath_roundtrip`
  - `tests/test_tool_contract.py::test_large_json_artifact_roundtrip`
- 定向测试命令:
  - `uv run python -m pytest -q tests/test_tool_contract.py tests/test_native_tools_artifact_and_guard.py`
- 结果: ✅ 17 passed

## 已知边界
1. `jsonpath` 为简化实现，不覆盖完整 JSONPath 语法。
2. `WS11-003` 当前为 native 执行链路可用态，后续可继续扩展到更多执行器。

## 完成时间
2026-02-24
