# NGA-WS12-001/002 实施记录

## 任务信息
- 任务ID: NGA-WS12-001, NGA-WS12-002
- 标题: file_ast_skeleton 分层读取、定向 chunk 读取
- 优先级: P0
- 阶段: M1
- 状态: ✅ 已完成

## 代码改动

### 1) file_ast_skeleton（WS12-001）
- 文件: `apiserver/native_tools.py`
- 工具: `file_ast_skeleton`
- 能力:
  1. 读取文件后输出 skeleton 视图（imports/symbols）。
  2. 按语言扩展名做轻量符号识别（`.py/.ts/.js/.cs`）。
  3. 对大文件输出 skeleton-only 提示，避免默认全量正文回读。

### 2) file_ast_chunk_read（WS12-002）
- 文件: `apiserver/native_tools.py`
- 工具: `file_ast_chunk_read`
- 能力:
  1. 按 `start_line/end_line` 读取目标片段。
  2. 支持 `context_before/context_after` 最小上下文窗口。
  3. 输出带行号且标记目标区间 (`>>`)。

### 3) 工具协议接入
- 文件: `apiserver/agentic_tool_loop.py`
- 变更:
  1. `native_call` schema 增加 `file_ast_skeleton/file_ast_chunk_read`。
  2. 增加 `context_before/context_after` 参数定义。

## 验证
- 新增测试:
  - `tests/test_native_tools_artifact_and_guard.py::test_file_ast_skeleton_and_chunk_read`
- 定向测试命令:
  - `uv run python -m pytest -q tests/test_tool_contract.py tests/test_native_tools_artifact_and_guard.py`
- 结果: ✅ 17 passed

## 完成时间
2026-02-24
