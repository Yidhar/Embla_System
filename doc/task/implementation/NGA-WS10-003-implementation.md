> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS10-003 实施记录（输入/输出 Schema 强校验）

## 任务信息
- 任务ID: `NGA-WS10-003`
- 标题: 建立输入/输出 schema 强校验
- 状态: 已完成（进入 review）

## 变更范围
- `apiserver/agentic_tool_loop.py`
- `tests/test_tool_schema_validation.py`（新增）
- 关联回归: `tests/test_agentic_tool_loop_metadata.py`

## 实施内容
1. 输入 schema 校验（gateway preflight）
- 新增错误码：
  - `E_SCHEMA_INPUT_INVALID`
  - `E_SCHEMA_OUTPUT_INVALID`
- 新增 native 工具名归一化与支持集校验：
  - alias 归一化（如 `exec -> run_cmd`）
  - 不支持工具在调度层直接拒绝
- 对关键高风险工具增加参数约束：
  - `run_cmd` 必须包含 `command/cmd`
  - `write_file` 必须包含 `path/file_path + content`
  - `workspace_txn_apply` 必须包含非空 `changes[]` 且每项具备 `path/content`
  - `artifact_reader` 必须包含 `artifact_id/raw_result_ref`
  - `sleep_and_watch` 必须包含 `log_file/path + pattern/regex`
  - `live2d_action` 限制为受控 action 枚举

2. 输出 schema 校验（gateway post-check）
- 在 `_execute_tool_call_with_retry()` 中加入统一结果结构校验：
  - 必须是对象
  - 必须包含 `status/service_name/tool_name/result`
  - `status` 必须属于允许集合（`success/ok/error/timeout/blocked`）
- 违规则返回标准错误回执并打上 `error_code=E_SCHEMA_OUTPUT_INVALID`。

3. 审计与拒绝策略
- 输入/输出校验失败统一进入 validation 错误链路，不执行或不继续传播非法结构。
- 校验拒绝带错误码，便于日志检索和后续告警聚合。

## 验证结果
1. 新增测试（`tests/test_tool_schema_validation.py`）
- 输入缺参会被 `E_SCHEMA_INPUT_INVALID` 拒绝。
- alias 工具名可归一并通过校验。
- 输出缺失 `status` 会被 `E_SCHEMA_OUTPUT_INVALID` 拦截。
- 非对象输出会被 `E_SCHEMA_OUTPUT_INVALID` 拦截。

2. 回归测试
- `tests/test_agentic_tool_loop_metadata.py`
- `tests/test_agentic_loop_contract_and_mutex.py`
- `tests/test_native_tools_runtime_hardening.py`
- `tests/test_workspace_txn_e2e_regression.py`

## 结论
- 非法参数/输出已在网关层拒绝并返回带错误码的结构化反馈。
- 为 `WS10-005` 风险门禁与审批策略收敛提供稳定输入基础。

