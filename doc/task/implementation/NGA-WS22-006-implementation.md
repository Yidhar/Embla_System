> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS22-006 实施记录（Sub-Agent 灰度接管比例控制）

## 1. 背景

此前 `SystemAgent` 对 `subagent_runtime` 的接管开关仅支持全开/全关，缺少灰度比例能力。
这会导致 Phase3 接管策略在生产前无法做“按比例放量 + 可回退”的稳态验证。

## 2. 实施内容

1. 配置模型扩展
   - 在 `SubAgentRuntimeConfig` 增加 `rollout_percent`（0-100，默认 100）。
   - 在 `SystemAgentConfig.from_source()` 增加字段解析并做边界裁剪。

2. 运行时接管决策
   - 在 `SystemAgent` 增加 `_resolve_runtime_mode(task)`：
     - `subagent_runtime.enabled=false` -> `legacy`
     - `rollout_percent=0` -> `legacy`
     - `rollout_percent=100` -> `subagent`
     - 其余比例 -> 对 `task_id + instruction` 计算稳定 bucket 决策
   - 支持任务级覆盖：
     - `task.metadata.runtime_mode`
     - `task.metadata.force_runtime_mode`
     - `task.metadata.execution_mode`
     - 可强制 `subagent/legacy`

3. 可观测性补齐
   - 每次 attempt 发出 `SubAgentRuntimeRolloutDecision`：
     - `runtime_mode`
     - `rollout_percent`
     - `rollout_bucket`
     - `decision_reason`

4. 测试与发布链更新
   - 新增 `tests/test_manage_ws27_subagent_cutover_ws27_002.py`：
     - `rollout_percent=0` 时即便启用 runtime 也走 legacy
     - 任务级强制 `runtime_mode=subagent` 可覆盖 `rollout_percent=0`
   - 将该测试纳入 `scripts/release_phase3_closure_chain_ws22_004.py` 的 T0 回归集合。

## 3. 变更文件

- `agents/runtime/mini_loop.py`
- `agents/pipeline.py`
- `tests/test_main_brainstem_bootstrap_ws28_024.py`
- `tests/test_manage_ws27_subagent_cutover_ws27_002.py`
- `scripts/release_phase3_closure_chain_ws22_004.py`
- `doc/task/runbooks/release_m6_m7_phase3_closure_onepager.md`
- `doc/task/22-ws-phase3-scheduler-bridge-and-rollout.md`

## 4. 验证记录

1. 语法检查
```bash
.\.venv\Scripts\python.exe -m py_compile agents/pipeline.py agents/runtime/mini_loop.py tests/test_manage_ws27_subagent_cutover_ws27_002.py scripts/release_phase3_closure_chain_ws22_004.py
```

2. 回归测试
```bash
.\.venv\Scripts\python.exe -m pytest -q tests/test_manage_ws27_subagent_cutover_ws27_002.py tests/test_agent_runtime_session_ws30_002.py tests/test_core_lease_fencing_ws28_029.py tests/test_main_brainstem_bootstrap_ws28_024.py tests/test_subagent_contract.py tests/test_release_phase3_closure_chain_ws22_004.py
```

3. 发布链路验证（跳过长稳）
```bash
.\.venv\Scripts\python.exe scripts/release_phase3_closure_chain_ws22_004.py --skip-longrun
```

## 5. 结果

- Phase3 调度接管从“开关式切换”升级为“比例灰度 + 任务级强制覆盖”。
- 发布前可逐步提升接管比例并保持可审计回退路径。
