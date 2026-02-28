> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS13-006 实施记录（跨文件事务回归与联调用例）

## 任务信息
- 任务ID: `NGA-WS13-006`
- 标题: 跨文件事务回归与联调
- 状态: 已完成（最小可交付）

## 变更范围
- `tests/test_workspace_txn_e2e_regression.py`（新增）

## 实施内容
1. 合同一致多文件提交成功
- 覆盖合同预检通过后，`workspace_txn_apply` 跨文件原子提交成功路径。

2. 合同不一致 fail-fast
- 覆盖 `contract_checksum mismatch` 阻断路径，验证 fail-fast 且无文件写入。

3. 跨文件失败回滚一致性
- 构造第二文件变更失败，验证事务失败后 `clean_state=true`、`rolled_back_files` 命中，且无半写残留。

4. 回滚后重试成功
- 验证同合同下，失败回滚后立即重试可成功，满足联调恢复性要求。

## 风险闭环
- `R12` 并行盲写前置合同门禁覆盖。
- `R13` 非原子半写通过回滚回归覆盖。

## 验证
- `uv --cache-dir .uv_cache run python -m pytest -q tests/test_workspace_txn_e2e_regression.py tests/test_native_tools_runtime_hardening.py tests/test_agentic_loop_contract_and_mutex.py`
- `uv --cache-dir .uv_cache run python -m ruff check tests/test_workspace_txn_e2e_regression.py`

结果：通过。
