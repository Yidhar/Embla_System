# NGA-WS12-006 实施记录（大文件与并发压测基线）

## 任务信息
- 任务ID: `NGA-WS12-006`
- 标题: 大文件与并发压测基线
- 状态: 已完成（最小可交付）

## 变更范围
- `tests/test_workspace_concurrency_baseline.py`（新增）

## 基线场景
1. 构造 `30,000` 行目标文件。
2. 先执行一次预写入（prime），使后续并发 worker 的 baseline 变为陈旧。
3. 启动 `12` 个并发 worker 对同一行提交 `workspace_txn_apply`。
4. 首轮冲突后进入重试；重试阶段串行化，确保可复现实验与稳定成功率。
5. 将指标写入 `scratch/reports/workspace_concurrency_baseline.json`。

## 指标定义
- `retry_count`: 所有 worker 的重试次数总和。
- `conflict_count`: 命中 `conflict_ticket` 的冲突次数总和。
- `successful_workers`: 最终提交成功的 worker 数。
- `success_rate`: `successful_workers / workers`。
- `conflict_rate`: `conflict_count / total_attempts`。
- `avg_backoff_ms`, `max_backoff_ms`: 冲突返回的 `backoff_ms` 统计值。

## 复现实验入口
- `uv --cache-dir .uv_cache run python -m pytest -q tests/test_workspace_concurrency_baseline.py`

## 一次本地结果（2026-02-24）
- `workers=12`
- `large_file_lines=30000`
- `total_attempts=24`
- `retry_count=12`
- `conflict_count=12`
- `successful_workers=12`
- `success_rate=1.0`
- `conflict_rate=0.5`
- `avg_backoff_ms=20.0`
- `max_backoff_ms=20`
- `elapsed_ms=1128`
