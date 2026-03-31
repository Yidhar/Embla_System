> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS24-004 实施记录（Plugin worker 生命周期与僵尸回收）

## 1. 背景

仅有超时并不等于完成生命周期治理。
插件异常退出、超时、历史遗留 job 都可能在 runtime 层形成“僵尸/幽灵执行链”。
本任务目标是把 worker 调用过程纳入统一 lineage，并补上 stale cleanup。

## 2. 实施内容

1. worker 调用接入 process lineage
   - 文件：`mcpserver/plugin_worker.py`
   - 每次调用记录：
     - `register_start(call_id, command, root_pid, fencing_epoch)`
     - 正常结束 `register_end(..., status=completed/failed)`
     - 超时路径 `kill_job(...)` + `orphan_scan(...)`

2. stale worker 自动清理
   - 每次调用前扫描 `list_running()`：
     - 匹配 `mcpserver.plugin_worker_runtime`
     - 超过 `stale_reap_grace_seconds` 的记录执行 `kill_job`
   - 清理计数汇总到 runtime metrics：`stale_reaped_total`

3. 观测增强
   - 暴露 `get_plugin_worker_runtime_metrics()` / `reset_plugin_worker_runtime_metrics()`
   - 可用于后续 M9 门禁脚本直接采样 worker 稳定性指标。

## 3. 变更文件

- `mcpserver/plugin_worker.py`
- `tests/test_mcp_plugin_isolation_ws24_001.py`

## 4. 验证记录

```bash
.\.venv\Scripts\python.exe -m pytest -q tests/test_mcp_plugin_isolation_ws24_001.py
```

关键断言覆盖：
- 超时路径会触发 lineage 回收分支；
- stale worker 记录可在新调用开始前被回收；
- 调用结束后存在对应 `register_end` 记录。

## 5. 结果

- Plugin worker 生命周期不再是“黑盒一次性进程”，而是纳入统一可追踪、可回收链路。
- 对“僵尸残留”和“超时孤儿”场景具备基础止血能力，可继续叠加 WS24-005 混沌演练验证。
