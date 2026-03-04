> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS18-001 实施记录（Event Bus 事件模型收敛）

## 任务信息
- Task ID: `NGA-WS18-001`
- Title: Event Bus 事件模型收敛
- 状态: 已完成（进入 review）

## 本次范围（仅 WS18-001）
1. 统一 Event Bus 事件 Envelope（含版本字段）
- `core/event_bus/event_schema.py`
  - 新增 `EVENT_SCHEMA_VERSION=ws18-001-v1`
  - 新增统一构造与归一化：
    - `build_event_envelope`
    - `normalize_event_envelope`
    - `is_event_envelope`
  - 标准事件字段：
    - `event_id`
    - `schema_version`
    - `timestamp`
    - `event_type`
    - `source`
    - `severity`
    - `idempotency_key`
    - `data`

2. EventStore 接入统一 Schema + 回放过滤
- `core/event_bus/event_store.py`
  - `emit(...)` 写入统一 envelope，并保留 `payload` 兼容别名（指向 `data`）。
  - `read_recent(...)` 对 legacy 行与新行统一归一化。
  - 新增 `replay(...)`，支持按 `event_type` / `workflow_id` / `trace_id` 过滤回放。

3. Workflow Outbox 接入统一 Schema（保持旧消费兼容）
- `agents/runtime/workflow_store.py`
  - `enqueue_outbox(...)` 统一写入 envelope 到 `payload_json`。
  - `read_pending_outbox(...)` 自动识别新旧 payload：
    - `payload` 继续返回业务数据（兼容旧调用）
    - 新增 `event_envelope`、`schema_version`、`source`、`severity`、`trace_id` 字段
  - 结果：旧消费链不改业务读取路径，也可逐步迁移到完整 envelope。

4. 测试覆盖
- 新增 `tests/test_core_event_bus_consumers_ws28_029.py`
  - 覆盖 envelope 字段落盘、replay 过滤、legacy 归一化。
- 更新 `tests/test_slo_snapshot_export.py`
  - 覆盖 outbox 读取时 `schema_version` 与 `event_envelope` 字段。

## 验证命令
- `python -m ruff check core/event_bus/event_schema.py core/event_bus/event_store.py agents/runtime/workflow_store.py tests/test_core_event_bus_consumers_ws28_029.py tests/test_slo_snapshot_export.py`
  - 结果: `All checks passed`
- `python -m pytest -q tests/test_canary_rollback_drill.py`
  - 结果: `passed`
- 本地功能烟测（脚本执行）
  - 覆盖 `EventStore.emit/read_recent` 与 `WorkflowStore.enqueue_outbox/read_pending_outbox` 的 ws18 envelope 行为
  - 结果: `WS18_001_SMOKE_OK`

## 环境说明（测试运行器限制）
- 当前环境下，`pytest tmpdir` 在包含 `tmp_path` 用例时可能触发 ACL 清理异常（`PermissionError`，发生在 `sessionfinish cleanup_dead_symlinks`）。
- 本次已将默认 `pytest` 配置改为不固定 `basetemp`，并在 `scripts/run_tests_safe.ps1` 改为每次运行生成唯一 `basetemp`，降低目录复用导致的权限冲突概率。

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `core/event_bus/event_schema.py; core/event_bus/event_store.py; agents/runtime/workflow_store.py; tests/test_core_event_bus_consumers_ws28_029.py; tests/test_slo_snapshot_export.py; doc/task/implementation/NGA-WS18-001-implementation.md`
- `notes`:
  - `event bus records now use ws18-001 envelope (event_id/schema_version/source/severity/idempotency_key/data), event_store replay supports event/trace/workflow filters, and workflow outbox read path normalizes legacy payloads while keeping payload compatibility`

## Date
2026-02-24
