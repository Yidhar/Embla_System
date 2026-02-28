> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS15-006 实施记录（GC 质量评测与回归基线）

## 任务信息
- 任务ID: `NGA-WS15-006`
- 标题: GC 质量评测与回归基线
- 状态: 已完成（最小可交付）

## 变更范围
- `system/gc_eval_suite.py`（新增）
- `tests/test_gc_quality_eval.py`（新增）

## 指标定义
1. 召回率（Recall）
- `recall_by_field`：按字段统计命中率，包含 `trace_ids/error_codes/paths/hex_addresses`。
- `recall_overall`：上述字段的整体命中率（命中总数 / 期望总数）。

2. 误删率（False Delete Rate）
- 定义：关键字段期望值中未被抽出的比例。
- 关键字段默认与召回字段一致：`trace/error/path/hex`。
- 公式：`missing_critical / total_critical_expected`。

3. 时延（Latency）
- `latency_avg_ms`：评测链路平均耗时。
- `latency_p95_ms`：评测链路 p95 耗时。
- 评测链路：`extract_gc_evidence -> build_gc_fetch_hints -> build_gc_reader_followup_plan -> build_gc_memory_index_card`。

## 阈值（回归断言）
- `recall_overall >= 0.85`
- `false_delete_rate <= 0.15`
- `latency_p95_ms <= 50`

## 复现与 CI 接入
1. 直接输出报告（JSON）
- `uv --cache-dir .uv_cache run python -m system.gc_eval_suite --iterations 5`

2. 严格模式（阈值不达标返回非 0）
- `uv --cache-dir .uv_cache run python -m system.gc_eval_suite --iterations 5 --strict`

3. 回归测试
- `uv --cache-dir .uv_cache run python -m pytest -q tests/test_gc_quality_eval.py`

