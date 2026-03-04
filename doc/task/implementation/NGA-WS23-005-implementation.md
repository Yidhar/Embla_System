> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS23-005 实施记录（Workflow outbox -> Brainstem 事件桥接）

## 1. 背景

`SystemAgent` 原有 outbox 分发链路只处理业务事件与去重状态，缺少一层可复用、可审计的 Brainstem 事件桥接。
这会导致 M8 期间无法稳定抽取 outbox 关键上下文（`outbox_id/workflow_id/trace_id/session_id`）进入脑干层观测链。

## 2. 实施内容

1. 新增桥接适配器
   - 新增 `system/brainstem_event_bridge.py`。
   - 提供 `build_brainstem_bridge_payload()`，将 outbox 行数据标准化为桥接 payload。
   - 固化桥接事件类型：`BrainstemEventBridged`。

2. 接入 SystemAgent outbox 分发主链
   - 在 `agents/pipeline.py::_dispatch_single_outbox_event()` 中，业务处理前先发射桥接事件。
   - 保留原分发语义：
     - dedup 命中仍走 `OutboxDedupHit`；
     - 桥接后继续业务处理与 `OutboxDispatched/Retry/DeadLetter`。

3. 新增 smoke + 回归覆盖
   - 新增 `scripts/run_outbox_brainstem_bridge_smoke_ws23_005.py`，产出 `NGA-WS23-005` 报告。
   - 新增 `tests/test_brainstem_event_bridge_ws23_005.py`（链路级）。
   - 新增 `tests/test_brainstem_event_bridge_ws23_005.py`（适配器单元）。

## 3. 变更文件

- `system/brainstem_event_bridge.py`
- `agents/pipeline.py`
- `scripts/run_outbox_brainstem_bridge_smoke_ws23_005.py`
- `tests/test_brainstem_event_bridge_ws23_005.py`
- `tests/test_brainstem_event_bridge_ws23_005.py`
- `doc/task/23-phase3-full-target-task-list.md`

## 4. 验证记录

```bash
.\.venv\Scripts\python.exe -m pytest -q tests/test_brainstem_event_bridge_ws23_005.py tests/test_brainstem_event_bridge_ws23_005.py -p no:tmpdir
```

## 5. 结果

- Outbox 关键事件在业务分发前即可桥接到脑干事件流，支持后续 replay 与审计扩展。
- M8 门禁可直接引用 `outbox_brainstem_bridge_ws23_005.json` 作为 WS23-005 证据产物。

