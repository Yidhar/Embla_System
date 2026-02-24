# NGA-WS22-004 实施记录（调度层混沌与 Lease 守护）

## 任务信息
- 任务ID: `NGA-WS22-004`
- 标题: 调度层混沌与 Lease 守护
- 状态: 已完成（长稳基线收口）

## 交付物

1. 长稳基线 Harness
- 文件: `autonomous/ws22_longrun_baseline.py`
- 能力:
  - 复用 `SystemAgent -> SubAgentRuntime -> Scaffold` 实际链路
  - 注入周期性 fail-open 场景（缺失 patch intent）并验证 fallback 稳定性
  - 统计事件完整性、workflow 状态分布、异常计数、门禁指标快照
  - 自动落盘报告: `scratch/reports/ws22_scheduler_longrun_baseline.json`

2. 基线测试
- 文件: `autonomous/tests/test_system_agent_longrun_baseline_ws22_004.py`
- 用例:
  - `test_ws22_longrun_equivalent_baseline_report`
- 断言:
  - `virtual_elapsed_seconds >= 600`
  - `task_rejected_count == 0`
  - `event_mismatch_count == 0`
  - `unhandled_exception_count == 0`
  - `failed_workflow_state_count == 0`

3. 可执行演练脚本
- 文件: `scripts/chaos_ws22_scheduler_longrun.py`
- 用法:
  - `.\.venv\Scripts\python.exe scripts/chaos_ws22_scheduler_longrun.py`
  - 可选参数:
    - `--rounds`
    - `--virtual-round-seconds`
    - `--fail-open-every`
    - `--lease-renew-every`
    - `--scratch-root`
    - `--report-file`

## 验证命令

1. 新增链路回归
- `.\.venv\Scripts\python.exe -m pytest -q autonomous/tests/test_system_agent_longrun_baseline_ws22_004.py autonomous/tests/test_system_agent_lease_guard_ws22_004.py autonomous/tests/test_system_agent_subagent_bridge_ws22_001.py`

2. 演练脚本执行
- `.\.venv\Scripts\python.exe scripts/chaos_ws22_scheduler_longrun.py --rounds 120 --virtual-round-seconds 5 --fail-open-every 15 --lease-renew-every 20`

## 一次本地结果（2026-02-24）

- `rounds=120`
- `virtual_elapsed_seconds=600.0`（10 分钟等效长稳窗口）
- `elapsed_wall_seconds=10.3264`
- `planned_fail_open_rounds=8`
- `task_approved_count=120`
- `task_rejected_count=0`
- `fail_open_count=8`
- `event_mismatch_count=0`
- `unhandled_exception_count=0`
- `workflow_states={"ReleaseCandidate": 120}`
- `passed=true`

## 结论

- WS22-004 的“Lease 守护 + fail-open + 事件链完整性”已具备可重复长稳基线与统计报告产物。
- `SystemAgent` 桥接链路在 10 分钟等效窗口内未出现未捕获异常、状态污染或事件丢失。
