# NGA-WS22-005 实施记录（Sub-Agent 子任务规范校验硬门禁）

## 1. 背景

在 `WS22` 调度桥接链路中，`SubAgentRuntime` 对不合法子任务图（重复 ID、坏依赖、自依赖、空指令）此前缺少前置拒绝，
会把问题延后到执行阶段，导致失败语义不稳定并增加 `fail_open` 噪声。

## 2. 实施内容

1. 在 `SubAgentRuntime.run()` 增加子任务规范校验前置门禁：
   - 规则：
     - 重复 `subtask_id`
     - 空 `instruction`
     - `dependencies` 自依赖
     - `dependencies` 引用不存在节点
   - 行为：
     - 命中规则时发出 `SubAgentRuntimeRejected(reason=invalid_subtask_spec)`
     - 返回 `gate_failure=runtime`，`fail_open_recommended=true`
     - 不进入 worker 执行阶段
2. 新增 Phase3 回归测试覆盖上述门禁。
3. 将新增测试纳入 `scripts/release_phase3_closure_chain_ws22_004.py` 的 T0 目标集。

## 3. 变更文件

- `autonomous/tools/subagent_runtime.py`
- `autonomous/tests/test_subagent_runtime_spec_validation_ws22_005.py`
- `scripts/release_phase3_closure_chain_ws22_004.py`
- `doc/task/runbooks/release_m6_m7_phase3_closure_onepager.md`
- `doc/task/22-ws-phase3-scheduler-bridge-and-rollout.md`

## 4. 验证记录

1. 语法校验
```bash
.\.venv\Scripts\python.exe -m py_compile autonomous/tools/subagent_runtime.py autonomous/tests/test_subagent_runtime_spec_validation_ws22_005.py scripts/release_phase3_closure_chain_ws22_004.py
```

2. Phase3 关键回归
```bash
.\.venv\Scripts\python.exe -m pytest -q autonomous/tests/test_subagent_runtime_spec_validation_ws22_005.py autonomous/tests/test_subagent_runtime_ws21_002.py autonomous/tests/test_subagent_runtime_eventbus_ws21_003.py autonomous/tests/test_subagent_runtime_chaos_ws21_006.py autonomous/tests/test_system_agent_subagent_bridge_ws22_001.py autonomous/tests/test_system_agent_lease_guard_ws22_004.py autonomous/tests/test_system_agent_longrun_baseline_ws22_004.py tests/test_release_phase3_closure_chain_ws22_004.py autonomous/tests/test_ws22_release_gate.py
```

3. 发布链路脚本验证（跳过长稳）
```bash
.\.venv\Scripts\python.exe scripts/release_phase3_closure_chain_ws22_004.py --skip-longrun
```

## 5. 结果

- 子任务图非法输入被稳定拦截，不再进入 worker 执行。
- `WS22` 运行时拒绝链路更早、更可审计，Phase3 调度接管质量提升。
