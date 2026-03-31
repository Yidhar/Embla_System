> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS12-004 实施记录（冲突票据与退避机制）

## 任务信息
- 任务ID: NGA-WS12-004
- 标题: 冲突票据与退避机制
- 状态: 已完成（最小可交付）

## 代码改动

### 1) 事务层引入 conflict_ticket 与 backoff_ms
- 文件: `system/workspace_transaction.py`
- 关键点:
1. 新增 `ConflictBackoffConfig`，统一退避参数:
   - `base_ms`（默认 200）
   - `max_ms`（默认 5000）
   - `attempt`（默认 1）
   - `jitter_ratio`（默认 0.25，范围 0~1）
2. 新增 `WorkspaceConflictError`，用于在并发冲突失败时携带:
   - `conflict_ticket`
   - `conflict_signature`
   - `backoff_ms`
   - `conflict_path`
3. `WorkspaceTransactionReceipt` 新增冲突诊断字段:
   - `conflict_ticket`
   - `conflict_signature`
   - `backoff_ms`
   - `conflict_path`
4. 新增冲突签名与票据生成:
   - 签名输入包含 `path/mode/expected_hash/current_hash/incoming_hash/reason`
   - `conflict_ticket` 由签名稳定派生，便于追踪与复现
5. 新增指数退避 + 抖动计算:
   - 基础为 `base_ms * 2^(attempt-1)`，再做 `max_ms` 封顶
   - 抖动使用冲突签名与 attempt 派生的确定性 jitter（可复现）
6. `semantic_rebase` 的冲突失败路径改为抛出 `WorkspaceConflictError`，并在回执失败分支写入冲突诊断字段。
7. `WorkspaceChange` 支持 change 级退避覆盖:
   - `conflict_backoff_base_ms`
   - `conflict_backoff_max_ms`
   - `conflict_backoff_attempt`
   - `conflict_backoff_jitter_ratio`

### 2) native tool 参数透传与失败信息增强
- 文件: `apiserver/native_tools.py`
- 关键点:
1. `workspace_txn_apply` 解析并透传退避配置:
   - 默认构造 `ConflictBackoffConfig`
   - 支持 `changes[i]` 内覆盖（含 `conflict_backoff` 对象或扁平字段）
2. 事务失败时，错误信息追加可诊断元数据:
   - `conflict_ticket=...`
   - `conflict_signature=...`
   - `backoff_ms=...`
   - `conflict_path=...`
3. 成功回执保持无冲突字段（避免误导上层将成功操作当作冲突）。

## 测试覆盖

### 更新测试
- 文件: `tests/test_workspace_semantic_rebase.py`
- 变更:
1. 成功路径断言不携带 `conflict_ticket/backoff_ms`
2. 失败路径断言包含 `conflict_ticket=` 与 `backoff_ms=`

### 新增测试
- 文件: `tests/test_workspace_conflict_backoff.py`
- 用例:
1. `test_workspace_conflict_backoff_is_monotonic_and_capped`
   - 连续冲突（attempt 1..5）下 `backoff_ms` 单调不降，且不超过上限
2. `test_workspace_conflict_ticket_is_reproducible_for_same_signature`
   - 同文件同冲突签名时 `conflict_ticket/conflict_signature` 可复现
3. `test_workspace_txn_success_has_no_conflict_metadata`
   - 成功提交不返回冲突信息

## 验证结果
- 命令:
  - `uv run python -m pytest -q tests/test_workspace_semantic_rebase.py tests/test_workspace_conflict_backoff.py`
- 结果:
  - 5 passed
  - 伴随若干与第三方依赖/pytest cache 权限相关 warning（不影响本任务断言）
