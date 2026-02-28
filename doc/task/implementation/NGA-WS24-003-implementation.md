> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS24-003 实施记录（插件资源限制与超时熔断）

## 1. 背景

隔离 worker 只是第一步。若插件可无限输出、长时间阻塞或持续报错重试，宿主仍会被拖垮。
本任务目标是把“资源配额 + 超时熔断”固化到 worker 执行面。

## 2. 实施内容

1. `PluginWorkerSpec` 扩展预算字段
   - 文件：`mcpserver/plugin_worker.py`
   - 新增限制项：
     - `max_payload_bytes`
     - `max_output_bytes`
     - `timeout_seconds`
     - `max_memory_mb`
     - `cpu_time_seconds`
     - `max_failure_streak`
     - `cooldown_seconds`

2. 宿主侧执行预算和熔断
   - 插件调用前检查 payload 大小，超限直接拒绝。
   - 子进程超时分类为 `timeout`，并进入失败计数。
   - 达到失败阈值后触发 circuit-open，在冷却窗口内拒绝新调用。
   - 新增 runtime metrics（调用总数、timeout、circuit-open、预算拒绝统计）。

3. worker 运行时资源限制入口
   - 文件：`mcpserver/plugin_worker_runtime.py`
   - 新增参数：
     - `--max-memory-mb`
     - `--cpu-time-seconds`
   - POSIX 环境下通过 `resource.setrlimit` 做 best-effort 限额；
     Windows 环境回退为 no-op（不阻塞调用链）。

4. registry 预算注入
   - 文件：`mcpserver/mcp_registry.py`
   - 从 `_worker_limits` 读取并注入 `PluginWorkerSpec`，避免“manifest 配置存在但执行层未生效”。

## 3. 变更文件

- `mcpserver/plugin_worker.py`
- `mcpserver/plugin_worker_runtime.py`
- `mcpserver/mcp_registry.py`
- `mcpserver/mcp_manager.py`
- `tests/test_mcp_plugin_isolation_ws24_001.py`

## 4. 验证记录

```bash
.\.venv\Scripts\python.exe -m pytest -q tests/test_mcp_plugin_isolation_ws24_001.py
```

关键断言覆盖：
- 超时调用可被检测并计入 timeout；
- 连续失败触发 circuit-open；
- 超大输出被 output budget 拒绝。

## 5. 结果

- 恶意或异常插件的“无限跑/无限吐”行为被预算与熔断机制限制在 worker 边界内。
- 宿主侧获得可观测的失败分类指标，为 M9 门禁提供数据基础。
