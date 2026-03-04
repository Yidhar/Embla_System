> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS25-001 实施记录（Topic 化 Event Bus 抽象层）

## 1. 背景

此前 `EventStore` 主要是 JSONL 追加日志模式，缺少：

1. Topic 维度订阅能力；
2. Topic 维度持久化与序号回放；
3. 统一的死信记录入口。

为推进 M10（Event Bus 全量化），本任务先落地 Topic Event Bus v1。

## 2. 实施内容

1. 新增 Topic Event Bus 核心
   - 文件：`autonomous/event_log/topic_event_bus.py`
   - 提供能力：
     - `publish(topic, payload, ...)`
     - `subscribe(pattern, handler, ...)`
     - `unsubscribe(...)`
     - `replay(topic_pattern, from_seq, to_seq, limit)`
     - `list_topics()`
     - `get_dead_letters()/retry_dead_letter()`

2. 持久化模型
   - SQLite 表：
     - `topic_event`（按 `seq` 自增序号持久化事件）
     - `dead_letter_event`（订阅失败记录）
   - 同时镜像写入 JSONL（兼容既有读取路径）。

3. EventStore 接入 TopicBus
   - 文件：`autonomous/event_log/event_store.py`
   - `emit()` 改为走 TopicBus 发布；
   - 保留 `read_recent()/replay()` 的 JSONL 兼容行为；
   - 新增：
     - `publish()`
     - `subscribe()/unsubscribe()`
     - `replay_by_topic()`
     - `list_topics()`

4. 主题归类规则
   - 新增 `infer_event_topic()`：
     - 将事件类型映射到 `system/log/cron/agent/tool/...` 主题前缀。

## 3. 变更文件

- `autonomous/event_log/topic_event_bus.py`
- `autonomous/event_log/event_store.py`
- `autonomous/event_log/__init__.py`
- `tests/test_topic_event_bus_ws25_001.py`
- `tests/test_system_agent_topic_bus_ws25_001.py`
- `doc/task/23-phase3-full-target-task-list.md`
- `doc/00-omni-operator-architecture.md`

## 4. 验证记录

```bash
.\.venv\Scripts\python.exe -m pytest -q tests/test_topic_event_bus_ws25_001.py tests/test_event_store_ws18_001.py tests/test_event_replay_tool_ws18_003.py
```

并对 SystemAgent 主路径做兼容回归：

```bash
.\.venv\Scripts\python.exe -m pytest -q tests/test_system_agent_outbox_bridge_ws23_005.py tests/test_system_agent_release_flow.py tests/test_system_agent_watchdog_gate_ws23_002.py
```

## 5. 结果

- 事件已可按 topic 发布、订阅并持久化；
- 历史 JSONL 回放链路保持兼容；
- 为 WS25-002（Cron/Alert 事件生产者接入）与 WS25-003（Replay 幂等强化）提供可扩展底座。
