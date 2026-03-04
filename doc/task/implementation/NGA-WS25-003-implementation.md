> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS25-003 实施记录（Replay 幂等锚点与去重策略强化）

## 1. 背景

`WS25-001/002` 已打通 Topic Event Bus 与 Cron/Alert 生产路径，但 replay 仍缺少“可持久化幂等锚点”：

1. 重放重复执行时可能重复触发订阅副作用；
2. 失败重放缺少可追踪的游标恢复点；
3. `EventStore` 侧没有统一暴露 replay 幂等控制接口。

本任务目标：让 replay 在“可重试”的同时“可去重”，并保持现有 JSONL 兼容链路不受影响。

## 2. 实施内容

1. TopicEventBus 增加 Replay 幂等元数据
   - 文件：`autonomous/event_log/topic_event_bus.py`
   - 新增持久化表：
     - `replay_anchor`：保存每个 `anchor_id` 的 `last_seq/topic_pattern`
     - `replay_dedupe`：按 `anchor_id + subscription_pattern + dedupe_key` 去重
   - 新增类型：
     - `ReplayDispatchResult`

2. 增加 replay 幂等执行入口
   - 新增 `replay_dispatch(anchor_id, topic_pattern, from_seq, to_seq, limit)`：
     - 按锚点推进重放窗口；
     - 命中 dedupe 记录则跳过重复投递；
     - 订阅失败时保留重试点（锚点回退到失败事件前一位）；
     - 输出扫描/投递/去重/失败统计。
   - 新增锚点管理：
     - `get_replay_anchor()`
     - `reset_replay_anchor(clear_dedupe=...)`

3. EventStore 暴露幂等重放接口
   - 文件：`autonomous/event_log/event_store.py`
   - 新增透传方法：
     - `replay_dispatch()`
     - `get_replay_anchor()`
     - `reset_replay_anchor()`
   - 保持原 `emit/read_recent/replay/replay_by_topic` 行为兼容。

4. 对外导出扩展
   - 文件：`autonomous/event_log/__init__.py`
   - 导出 `ReplayDispatchResult`，供运行时与测试直接引用。

## 3. 变更文件

- `autonomous/event_log/topic_event_bus.py`
- `autonomous/event_log/event_store.py`
- `autonomous/event_log/__init__.py`
- `tests/test_topic_event_bus_replay_idempotency_ws25_003.py`
- `doc/task/23-phase3-full-target-task-list.md`
- `doc/00-omni-operator-architecture.md`
- `doc/task/implementation/NGA-WS25-003-implementation.md`

## 4. 验证记录

```bash
.\.venv\Scripts\python.exe -m pytest -q tests/test_topic_event_bus_ws25_001.py tests/test_cron_alert_producer_ws25_002.py tests/test_topic_event_bus_replay_idempotency_ws25_003.py tests/test_event_store_ws18_001.py tests/test_event_replay_tool_ws18_003.py
```

SystemAgent 兼容回归：

```bash
.\.venv\Scripts\python.exe -m pytest -q tests/test_system_agent_topic_bus_ws25_001.py tests/test_system_agent_cron_alert_ws25_002.py tests/test_system_agent_release_flow.py tests/test_system_agent_outbox_bridge_ws23_005.py
```

## 5. 结果

- Replay 具备持久化锚点与订阅级去重能力；
- 重放失败可回退重试，成功事件不会重复触发副作用；
- M10 事件链路下一步可转入 `WS25-004`（关键证据字段保真）。
