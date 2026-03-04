> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS25-002 实施记录（Cron/Alert 事件生产者接入 Event Bus）


> Migration Note (archived/legacy)
> 文中 `autonomous/*` 路径属于历史实现标识；当前实现请优先使用 `agents/*`、`core/*` 与 `config/autonomous_runtime.yaml`。

## 1. 背景

`WS25-001` 已完成 Topic Event Bus 核心，但缺少可直接驱动总线的标准生产者。
本任务目标是补齐 Cron/Alert 两类事件生产入口，使其进入统一 topic 持久化链路。

## 2. 实施内容

1. 新增生产者模块
   - 文件：`autonomous/event_log/cron_alert_producer.py`（archived/legacy）
   - `CronEventProducer`：
     - 支持 schedule 注册、到期触发、周期续约；
     - 事件发布到 `cron.*` 主题。
   - `AlertEventProducer`：
     - 支持按 `alert_key + severity` 去重窗口；
     - 事件发布到 `alert.*` 主题。

2. 接入 SystemAgent 主链路
   - 文件：`agents/pipeline.py`
   - 初始化阶段挂载：
     - `self.cron_event_producer`
     - `self.alert_event_producer`
   - `run_cycle()` 开始时触发 cron due 事件（`cron.system_agent.cycle`）。
   - watchdog 门禁评估时写入 `alert.watchdog` 主题事件。

3. 主题持久化与回放验证
   - 基于 `EventStore.publish(...)` 进入 TopicBus（SQLite + JSONL mirror）；
   - 可通过 `replay_by_topic("cron.*"/"alert.*")` 回放验证。

## 3. 变更文件

- `autonomous/event_log/cron_alert_producer.py`（archived/legacy）
- `autonomous/event_log/__init__.py`（archived/legacy）
- `agents/pipeline.py`
- `tests/test_core_event_bus_consumers_ws28_029.py`
- `tests/test_ops_dashboard_extensions.py`
- `doc/task/23-phase3-full-target-task-list.md`
- `doc/00-omni-operator-architecture.md`

## 4. 验证记录

```bash
.\.venv\Scripts\python.exe -m pytest -q tests/test_core_event_bus_consumers_ws28_029.py tests/test_ops_dashboard_extensions.py tests/test_run_watchdog_daemon_ws28_025.py
```

扩展兼容回归：

```bash
.\.venv\Scripts\python.exe -m pytest -q tests/test_core_event_bus_consumers_ws28_029.py tests/test_core_event_bus_consumers_ws28_029.py tests/test_core_event_bus_consumers_ws28_029.py tests/test_brainstem_event_bridge_ws23_005.py tests/test_canary_rollback_drill.py
```

## 5. 结果

- Cron/Alert 事件生产者已进入统一 Topic Event Bus 链路；
- `SystemAgent` 主路径中已可观测 `cron.*` 与 `alert.*` 事件；
- 为 WS25-003 的 Replay 幂等强化提供稳定输入流。
