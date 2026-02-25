# NGA-WS25-005 实施记录（Event/GC 质量评测基线脚本）

## 1. 背景

在 `WS25-001~004` 完成后，M10 仍缺少一个统一质量基线入口，用于同时验证：

1. Replay 幂等不产生重复副作用；
2. GC 证据质量阈值持续达标；
3. 关键证据保真策略（`trace/error/path`）在真实工具结果链路可见。

本任务目标是把上述检查合并为可执行、可产出报告的单一基线脚本。

## 2. 实施内容

1. 新增 M10 质量基线 harness
   - 文件：`autonomous/ws25_event_gc_quality_baseline.py`
   - 输出报告项：
     - replay idempotency drill
     - critical evidence preservation drill
     - GC quality thresholds validation

2. Replay 幂等演练
   - 通过 `EventStore.publish + replay_dispatch(anchor_id)` 连续重放两次同窗口：
     - 第一次必须投递成功；
     - 第二次必须命中 dedupe 且不重复触发 side-effect；
     - 锚点需推进到有效序号。

3. 关键证据保真演练
   - 使用超长 JSON 工具输出构造 `ToolResultEnvelope`：
     - 校验 `critical_evidence` 中 `trace_ids/error_codes/paths` 非空；
     - 校验 `fetch_hints` 含对应 `grep:*` 线索；
     - 校验证据引用（artifact ref）存在。

4. GC 质量阈值复用
   - 复用 `system.gc_eval_suite.evaluate_gc_quality()` 与阈值校验；
   - 将阈值违规项纳入统一报告。

5. CLI 入口
   - 文件：`scripts/run_event_gc_quality_baseline_ws25_005.py`
   - 支持参数：
     - `--replay-event-count`
     - `--gc-iterations`
     - `--output`

## 3. 变更文件

- `autonomous/ws25_event_gc_quality_baseline.py`
- `scripts/run_event_gc_quality_baseline_ws25_005.py`
- `autonomous/tests/test_ws25_event_gc_quality_baseline.py`
- `tests/test_run_event_gc_quality_baseline_ws25_005.py`
- `doc/task/23-phase3-full-target-task-list.md`
- `doc/00-omni-operator-architecture.md`
- `doc/task/implementation/NGA-WS25-005-implementation.md`

## 4. 验证记录

```bash
.\.venv\Scripts\python.exe -m pytest -q autonomous/tests/test_ws25_event_gc_quality_baseline.py tests/test_run_event_gc_quality_baseline_ws25_005.py tests/test_gc_quality_eval.py autonomous/tests/test_topic_event_bus_replay_idempotency_ws25_003.py tests/test_tool_contract.py tests/test_episodic_memory.py
```

## 5. 结果

- M10 Event/GC 已具备可重复执行的质量基线报告；
- Replay 幂等、GC 阈值、关键证据保真可在同一报告中追踪；
- 为 `WS25-006` 门禁链提供稳定输入。
