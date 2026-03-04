> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS25-006 实施记录（M10 综合门禁脚本链）

## 1. 背景

`WS25-005` 提供了 Event/GC 质量基线，但 M10 仍需发布前门禁闭环：

1. 质量报告需要进入 release gate；
2. 文档快照与 runbook 需要被机器校验；
3. 全量收口链需要纳入 M10 组。

本任务目标是形成“可执行 + 可拒绝 + 可追责”的 M10 综合门禁链。

## 2. 实施内容

1. 新增 M10 gate 评估器
   - 文件：`autonomous/ws25_release_gate.py`
   - 校验维度：
     - `WS25-005` 报告通过（task_id/scenario/passed）
     - 任务文档快照包含 `NGA-WS25-003/004/005/006`
     - runbook 包含关键执行命令

2. 新增 M10 gate CLI
   - 文件：`scripts/validate_m10_closure_gate_ws25_006.py`
   - 输出：`scratch/reports/ws25_m10_closure_gate_result.json`

3. 新增 M10 release chain
   - 文件：`scripts/release_closure_chain_m10_ws25_006.py`
   - 默认步骤：
     - `T0` M10 定向回归
     - `T1` `run_event_gc_quality_baseline_ws25_005.py`
     - `T2` `validate_m10_closure_gate_ws25_006.py`
     - `T3` `validate_doc_consistency_ws16_006.py --strict`

4. 接入全量收口链
   - 文件：`scripts/release_closure_chain_full_m0_m7.py`
   - 新增 `m10` group 与 `--m10-output/--skip-m10` 参数；
   - 目标域更新为 `M0-M10`（兼容文件名）。

5. 发布摘要链路扩展
   - 文件：`scripts/render_release_closure_summary.py`
   - 新增 M10 报告输入与汇总展示。

6. 新增 runbook
   - 文件：`doc/task/runbooks/release_m10_event_gc_closure_onepager_ws25_006.md`

## 3. 变更文件

- `autonomous/ws25_release_gate.py`
- `scripts/validate_m10_closure_gate_ws25_006.py`
- `scripts/release_closure_chain_m10_ws25_006.py`
- `scripts/release_closure_chain_full_m0_m7.py`
- `scripts/render_release_closure_summary.py`
- `doc/task/runbooks/release_m10_event_gc_closure_onepager_ws25_006.md`
- `tests/test_ws25_release_gate.py`
- `tests/test_release_closure_chain_m10_ws25_006.py`
- `tests/test_release_closure_chain_full_m0_m7.py`
- `tests/test_render_release_closure_summary.py`
- `doc/task/23-phase3-full-target-task-list.md`
- `doc/00-omni-operator-architecture.md`
- `doc/task/implementation/NGA-WS25-006-implementation.md`

## 4. 验证记录

```bash
.\.venv\Scripts\python.exe -m pytest -q tests/test_ws25_release_gate.py tests/test_release_closure_chain_m10_ws25_006.py tests/test_release_closure_chain_full_m0_m7.py tests/test_render_release_closure_summary.py tests/test_ws25_event_gc_quality_baseline.py tests/test_run_event_gc_quality_baseline_ws25_005.py
```

## 5. 结果

- M10 形成独立门禁脚本链（报告、文档、runbook 三位一体）；
- 全量收口链已扩展到 `M0-M10`；
- 下一阶段可转入 `M11` 稳态化任务（WS26）。
