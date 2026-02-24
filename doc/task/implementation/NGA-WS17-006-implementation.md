# NGA-WS17-006 实施记录（混沌演练：double-fork 与磁盘压力）

## 任务信息
- 任务ID: `NGA-WS17-006`
- 标题: 混沌演练：double-fork 与磁盘压力
- 状态: 已完成（最小可交付）

## 变更范围
- `tests/test_chaos_runtime_storage.py`（新增）

## 实施内容
1. double-fork 幽灵链回收演练
- 场景：根进程已消失，但存在脱离进程树的后台幽灵进程。
- 方法：通过 monkeypatch 模拟 `ProcessLineageRegistry` 的 `_kill_pid_tree` 与进程列表，验证 fencing 回收时签名清理路径能继续回收幽灵链。
- 断言：`reap_by_fencing_epoch` 成功、running 集合清空、状态持久化为 `killed`，且原因包含 `signature_killed` 统计。

2. ENOSPC 磁盘压力一致性演练
- 场景：artifact 写入 `.dat` 过程中触发 `No space left on device`。
- 方法：对 `artifact_store.open` 注入 ENOSPC 异常，验证 store 失败时不污染 metadata 与历史可读 artifact。
- 断言：`store_attempt/store_success/artifact_count` 指标一致、磁盘 metadata 未破坏、baseline artifact 可继续读取。

## 设计取舍
- 本任务按 QA 演练定位，仅新增测试，不改核心实现，避免引入功能副作用。

## 验证
- `uv --cache-dir .uv_cache run python -m pytest -q tests/test_chaos_runtime_storage.py tests/test_process_lineage.py tests/test_artifact_store_policy.py`
- `uv --cache-dir .uv_cache run python -m ruff check tests/test_chaos_runtime_storage.py`

结果：通过。
