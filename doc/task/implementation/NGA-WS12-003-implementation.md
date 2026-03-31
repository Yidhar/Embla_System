> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS12-003 实施记录（semantic_rebase）

## 任务信息
- 任务ID: NGA-WS12-003
- 标题: 语义重基（semantic_rebase）
- 优先级: P1
- 阶段: M2
- 状态: ✅ 已完成（最小可交付）

## 代码改动

### 1) 事务层接入保守 semantic rebase
- 文件: `system/workspace_transaction.py`
- 关键点:
  1. `WorkspaceChange` 新增并发基线字段:
     - `original_file_hash`（兼容 expected hash 语义）
     - `expected_file_hash`（别名）
     - `original_content`（3-way 重基基线文本）
     - `semantic_rebase`（默认 true）
  2. `WorkspaceTransactionReceipt` 新增 `semantic_rebased_files`，记录自动重基成功文件。
  3. `apply_all` 写入流程新增 hash 校验与分支:
     - hash 一致: 正常 apply；
     - hash 不一致: 进入 semantic rebase 路径；
     - overwrite 模式仅在“非重叠行级改动”时自动合并；
     - append 在 hash 冲突下按最新内容追加并计入重基路径。
  4. 失败策略为保守 hard-fail:
     - 缺少 `original_content`、`original_content` hash 不匹配、行级改动重叠、索引映射失败，均直接失败并触发事务回滚。
  5. 错误文本包含 `path/expected_hash/current_hash/reason`，便于诊断。

### 2) workspace_txn_apply 参数透传与回执增强
- 文件: `apiserver/native_tools.py`
- 关键点:
  1. 在 `workspace_txn_apply` 解析每个 change 时接入:
     - `original_file_hash`
     - `expected_hash` / `expected_file_hash`（别名，最终合并到事务层 hash 字段）
     - `original_content`
     - `semantic_rebase`（支持 call 级默认值 + change 级覆盖）
  2. 回执新增:
     - `[semantic_rebased_files] <N>`
     - `[semantic_rebase_paths]`（存在时输出具体文件）

### 3) 新增测试
- 文件: `tests/test_workspace_semantic_rebase.py`
- 用例:
  1. `test_workspace_txn_apply_semantic_rebase_merges_non_overlapping_conflict`
     - 验证轻度冲突（不同行）自动重基成功。
  2. `test_workspace_txn_apply_semantic_rebase_fails_on_overlapping_conflict_without_pollution`
     - 验证深冲突（同一行）硬失败，且工作区文件保持并发方版本，不被污染。

## 验证
- 命令:
  - `.venv\Scripts\python.exe -m pytest -q tests/test_workspace_semantic_rebase.py`
- 结果:
  - ✅ 2 passed

## 边界与已知限制
1. 当前自动重基仅支持基于 `original_content` 的行级 3-way 合并，不做 AST 级语义分析。
2. 若调用方仅提供 hash、未提供 `original_content`，overwrite 冲突会保守失败（避免不安全猜测合并）。
3. 判定策略偏保守，边界接触/重叠区域会优先视为冲突失败。
