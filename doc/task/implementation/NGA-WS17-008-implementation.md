# NGA-WS17-008 实施记录（SLO/告警看板上线）

## 任务信息
- 任务ID: `NGA-WS17-008`
- 标题: SLO/告警看板上线
- 状态: 已完成（最小可交付）

## 变更范围
- `scripts/export_slo_snapshot.py`（新增）
- `tests/test_slo_snapshot_export.py`（新增）
- `doc/task/runbooks/slo_alert_dashboard_runbook.md`（新增）

## 实施内容
1. 本地 SLO 快照导出器
- 导出字段包含：
  - 错误率 `error_rate`
  - 延迟 `latency_p95_ms`
  - 队列深度 `queue_depth`
  - 磁盘水位 `disk_watermark_ratio`
  - 锁状态 `lock_status`
- 输出 JSON（stdout + 文件），包含 `summary.overall_status` 与阈值快照。

2. 数据源
- `logs/autonomous/events.jsonl`（CLI 事件；回退 canary window）
- `logs/autonomous/workflow.db`（pending 队列深度）
- `logs/runtime/global_mutex_lease.json`（锁到期状态）
- `ArtifactStore` 指标（artifact 容量与水位）
- `autonomous/config/autonomous_config.yaml`（阈值配置）

3. 值班 runbook
- 一页式指标阈值定义、触发规则、分项排障动作、恢复验收与交接模板。
- 提供可直接执行的快照导出命令。

## 验证
- `uv --cache-dir .uv_cache run python -m pytest -q tests/test_slo_snapshot_export.py`
- `uv --cache-dir .uv_cache run python -m ruff check scripts/export_slo_snapshot.py tests/test_slo_snapshot_export.py`

结果：通过。
