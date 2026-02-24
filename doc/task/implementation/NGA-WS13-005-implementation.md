# NGA-WS13-005 实施记录（clean_state 保证与恢复票据）

## 任务信息
- 任务ID: `NGA-WS13-005`
- 标题: clean_state 保证与恢复票据
- 状态: 已完成（最小可交付）

## 变更范围
- `system/workspace_transaction.py`
- `apiserver/native_tools.py`
- `tests/test_native_tools_runtime_hardening.py`

## 实施内容
1. 回滚一致性校验增强
- 备份信息增加原编码记录，回滚时按原编码恢复。
- 回滚后增加强校验：
  - 已存在文件：重写后立即重读并校验 hash。
  - 新建文件：删除后校验文件确实不存在。
- 任一回滚校验失败即标记 `clean_state=false`。

2. 失败诊断字段增强
- `WorkspaceTransactionReceipt` 新增 `rollback_failed_files`。
- 异常回滚分支填充 `rolled_back_files` 与 `rollback_failed_files`，并保证 `recovery_ticket` 始终可用。

3. native 层错误元数据增强
- `workspace_txn_apply` 失败消息增加：
  - `rolled_back_files=<count>`
  - `rollback_failed_files=<count>`（仅存在失败回滚时）
- 上层可据此做“是否可立即重试”的稳定判断。

## 测试覆盖
- 回滚成功：`clean_state=true` + `recovery_ticket` 存在 + 文件内容恢复。
- 回滚失败注入：`clean_state=false` + `rollback_failed_files` 命中。
- 失败后立即重试：确认可在清洁状态下成功提交。

## 验证
- `uv --cache-dir .uv_cache run python -m pytest -q tests/test_native_tools_runtime_hardening.py tests/test_workspace_semantic_rebase.py`
- `uv --cache-dir .uv_cache run python -m ruff check system/workspace_transaction.py apiserver/native_tools.py tests/test_native_tools_runtime_hardening.py`

结果：通过。
