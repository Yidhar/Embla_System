> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS26-006 实施记录（M11 混沌门禁）

## 任务信息
- 任务ID: `NGA-WS26-006`
- 标题: M11 混沌门禁（锁泄漏 / logrotate / double-fork）
- 状态: 已完成

## 变更范围

1. M11 门禁评估器
- 文件: `autonomous/ws26_release_gate.py`
- 变更:
  - 新增 `evaluate_ws26_m11_closure_gate(...)`：
    - 校验 `WS26-002` 运行时快照报告（rollout/fail-open/lease）
    - 校验 `WS26-006` 混沌回归报告（lock/logrotate/double-fork）
    - 校验任务快照文档与 M11 runbook 命令完整性
  - 支持细粒度 `checks/reasons` 回执，供发布门禁与 CI 直接消费。

2. M11 混沌回归报告脚本
- 文件: `scripts/run_ws26_m11_runtime_chaos_suite_ws26_006.py`
- 变更:
  - 新增三类场景回归执行与统一报告输出：
    - `C1` 锁泄漏 + fencing 接管链（含清道夫联动）
    - `C2` `sleep_and_watch` logrotate/ReDoS 防护
    - `C3` double-fork/脱离进程树签名回收
  - 输出标准 JSON 报告：`task_id/scenario/failed_cases/case_results`。

3. M11 收口链与全量链接入
- 文件:
  - `scripts/release_closure_chain_m11_ws26_006.py`
  - `scripts/validate_m11_closure_gate_ws26_006.py`
  - `scripts/release_closure_chain_full_m0_m7.py`
- 变更:
  - 新增 M11 独立收口链（T0~T4）：
    - 定向测试
    - 运行时快照导出
    - 混沌回归报告
    - M11 gate 校验
    - 文档一致性严格校验
  - 全量链新增 `m11` group 与 `--m11-output/--skip-m11` 参数。
  - `target_scope` 扩展到 `M0-M11`（保留脚本名兼容）。

4. 文档与回归
- 文件:
  - `doc/task/runbooks/release_m11_lock_fencing_closure_onepager_ws26_006.md`
  - `doc/task/23-phase3-full-target-task-list.md`
  - `doc/00-omni-operator-architecture.md`
  - `tests/test_ws26_release_gate.py`
  - `tests/test_run_ws26_m11_runtime_chaos_suite_ws26_006.py`
  - `tests/test_release_closure_chain_m11_ws26_006.py`
  - `tests/test_release_closure_chain_full_m0_m7.py`
- 变更:
  - 补齐 M11 一页式执行清单与出口条件。
  - 将 WS26-006 写入任务快照与目标态证据矩阵。
  - 增加门禁/脚本/全量链三层回归覆盖。

## 验证命令

1. WS26 门禁与收口链单测
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_ws26_release_gate.py tests/test_run_ws26_m11_runtime_chaos_suite_ws26_006.py tests/test_release_closure_chain_m11_ws26_006.py tests/test_release_closure_chain_full_m0_m7.py`

2. 关键 M11 回归
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_system_agent_fail_open_budget_ws26_003.py tests/test_agentic_loop_contract_and_mutex.py tests/test_chaos_lock_failover.py tests/test_chaos_sleep_watch.py tests/test_process_lineage.py tests/test_export_ws26_runtime_snapshot_ws26_002.py -p no:tmpdir`

3. 静态检查
- `.\.venv\Scripts\python.exe -m ruff check autonomous/ws26_release_gate.py scripts/validate_m11_closure_gate_ws26_006.py scripts/run_ws26_m11_runtime_chaos_suite_ws26_006.py scripts/release_closure_chain_m11_ws26_006.py scripts/release_closure_chain_full_m0_m7.py tests/test_ws26_release_gate.py tests/test_run_ws26_m11_runtime_chaos_suite_ws26_006.py tests/test_release_closure_chain_m11_ws26_006.py tests/test_release_closure_chain_full_m0_m7.py`

## 结果摘要

- M11 已形成“报告生成 -> 门禁校验 -> 收口链 -> 全量链接入”闭环。
- 锁泄漏、logrotate/sleep_watch、double-fork 三类高风险链路具备独立报告与发布前拦截能力。
- 全量发布链保持兼容命名，同时目标域推进至 `M0-M11`。
