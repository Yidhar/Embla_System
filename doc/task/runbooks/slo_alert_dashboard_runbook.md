# NGA-WS17-008 SLO/告警看板 Runbook

## 1. 目标与范围
- 任务: `NGA-WS17-008`
- 目标: 在本地环境提供可执行的 SLO 快照与值班联动手册，不依赖外部监控系统。
- 指标范围: `错误率`、`延迟 p95`、`队列深度`、`磁盘水位`、`锁状态`。

## 2. 一页式 SLO 指标与告警阈值

| 指标 | 采集来源（本地） | 计算口径 | Warning 阈值 | Critical 阈值 |
|---|---|---|---|---|
| 错误率 `error_rate` | `logs/autonomous/events.jsonl`（优先 `CliExecutionCompleted`，缺失时回退 canary `evaluated_windows`） | `失败次数 / 总样本` | `max_error_rate * 0.5`（默认 `1%`） | `max_error_rate`（默认 `2%`） |
| 延迟 `latency_p95_ms` | 同上 | CLI 事件 `duration_seconds` 的 p95（ms）；回退路径取 canary window 的最大 p95 | `max_latency_p95_ms * 0.8`（默认 `1200ms`） | `max_latency_p95_ms`（默认 `1500ms`） |
| 队列深度 `queue_depth` | `logs/autonomous/workflow.db` 的 `outbox_event` 表 | `status='pending'` 条数 + 最老 pending 年龄 | `batch_size`（默认 `50`）或最老年龄 `120s` | `max(batch_size*3, batch_size+1)`（默认 `150`）或最老年龄 `300s` |
| 磁盘水位 `disk_watermark_ratio` | `ArtifactStore`（`logs/artifacts` 元数据） | `total_size_mb / max_total_size_mb` | `high_watermark_ratio`（默认 `0.90`） | `1 - critical_reserve_ratio`（默认 `0.95`） |
| 锁状态 `lock_status` | `logs/runtime/global_mutex_lease.json` | `seconds_to_expiry = expires_at - now` | `seconds_to_expiry <= max(2, ttl*0.2)` | `seconds_to_expiry <= 0` |

阈值配置来源:
- `autonomous/config/autonomous_config.yaml`
- `ArtifactStoreConfig`（`system/artifact_store.py`）

## 3. 快照导出（本地可执行）

### 3.1 命令
```bash
uv --cache-dir .uv_cache run python scripts/export_slo_snapshot.py
```

默认行为:
- 控制台打印完整 JSON。
- 同步写文件: `logs/runtime/slo_snapshot_baseline.json`。

常用参数:
```bash
uv --cache-dir .uv_cache run python scripts/export_slo_snapshot.py --stdout-only
uv --cache-dir .uv_cache run python scripts/export_slo_snapshot.py --events-limit 10000
uv --cache-dir .uv_cache run python scripts/export_slo_snapshot.py --output logs/runtime/slo_snapshot_custom.json
```

### 3.2 输出结构（关键字段）
- `summary.overall_status`: `unknown | ok | warning | critical`
- `metrics.error_rate`
- `metrics.latency_p95_ms`
- `metrics.queue_depth`
- `metrics.disk_watermark_ratio`
- `metrics.lock_status`
- `threshold_profile`: 当前生效阈值快照（来自本地配置）

## 4. 值班联动流程（On-call）

### 4.1 触发规则
1. `summary.overall_status = critical`。
2. 任一单指标进入 `critical` 并持续两个采样周期。
3. `warning` 指标数量 >= 2 且持续 10 分钟。

### 4.2 处置优先级
1. `lock_status`（先判断是否 lease 过期/抖动，避免双主风险）
2. `queue_depth`（先止血积压，防止级联超时）
3. `error_rate` 与 `latency_p95_ms`（确认是否功能性退化）
4. `disk_watermark_ratio`（确认是否接近背压/拒写阈值）

### 4.3 分项排障动作

#### A. 错误率/延迟告警
1. 复采样快照，确认不是瞬时尖峰：
   ```bash
   uv --cache-dir .uv_cache run python scripts/export_slo_snapshot.py --stdout-only
   ```
2. 检查 `logs/autonomous/events.jsonl` 最新 `CliExecutionCompleted` 与回滚事件。
3. 若连续 `critical`，暂停高风险自动变更，转入人工审批执行。

#### B. 队列深度告警
1. 检查 `workflow.db` pending 是否持续增长。
2. 若 `pending` 达到 critical，优先降低新任务注入速率，先清 backlog。
3. 若最老 pending 年龄 > 300s，排查 outbox 消费链（lease 是否健康、消费者是否存活）。

#### C. 磁盘水位告警
1. 查看 `metrics.disk_watermark_ratio.total_size_mb` 与 `artifact_count`。
2. 若超过 warning，执行低优先级 artifact 清理。
3. 若达到 critical，优先保障关键路径写入（高优先级 artifact / runtime 状态文件）。

#### D. 锁状态告警
1. 检查 `metrics.lock_status.state` 与 `seconds_to_expiry`。
2. `near_expiry`：确认心跳线程是否阻塞、I/O 是否拥堵。
3. `expired`：按 failover 流程进行主实例切换，并核对 `fencing_epoch` 单调递增。

## 5. 恢复验收
1. 连续 3 次快照（间隔 1-2 分钟）`overall_status = ok`。
2. `queue_depth` 回落到 warning 以下。
3. `lock_status.state = healthy` 且 `seconds_to_expiry` 充足。
4. 记录事件时间线、处置动作、恢复证据路径（JSON 快照文件）。

## 6. 交接信息模板
- 事件级别: `warning/critical`
- 触发时间: `YYYY-MM-DD HH:mm:ss`
- 触发指标: `error_rate / latency / queue_depth / disk / lock`
- 当前快照: `logs/runtime/slo_snapshot_baseline.json`
- 已执行动作:
- 待跟进风险:
- 下一次复盘时间:
