# NGA-WS26-001 实施记录（SystemAgent 写路径强制收敛到 Scaffold/Txn）

## 任务信息
- 任务ID: `NGA-WS26-001`
- 标题: SystemAgent 写路径强制收敛到 Scaffold/Txn
- 状态: 已完成

## 变更范围

1. 配置与默认门禁
- 文件: `autonomous/tools/subagent_runtime.py`
- 变更:
  - `SubAgentRuntimeConfig` 新增:
    - `enforce_scaffold_txn_for_write`（默认 `true`）
    - `allow_legacy_fail_open_for_write`（默认 `false`）
  - 同步补充 `fail_open_budget_ratio`（为 WS26-002 指标预算使用）。

2. SystemAgent 写路径收敛逻辑
- 文件: `autonomous/system_agent.py`
- 变更:
  - 新增 `_task_requires_scaffold_txn(task)` 写意图识别：
    - `metadata.write_intent == true`
    - `target_files` 非空
    - `metadata.subtasks[*]` 存在 `patches` 字段
  - `runtime_mode` 解析阶段增加写路径强制:
    - write 任务默认收敛到 `subagent`；
    - `runtime_mode=legacy` 对 write 任务不再默认放行（会被强制回 `subagent` 或触发拒绝）。
  - 新增 `_evaluate_write_path_gate(...)`：
    - 当 write 任务仍落到 legacy（例如 subagent 被禁用）时触发
      `ReleaseGateRejected(gate=write_path)`。
  - fail-open 保护:
    - 当 `SubAgentRuntime` 推荐 fail-open 且任务是 write 任务时，默认阻断 legacy 回退；
    - 触发 `SubAgentRuntimeFailOpenBlocked` + `ReleaseGateRejected(gate=write_path)` 审计事件；
    - 仅在 `allow_legacy_fail_open_for_write=true` 时允许兼容回退。

3. 回归与兼容
- 文件:
  - `autonomous/tests/test_system_agent_write_path_ws26_001.py`（新增）
  - `autonomous/tests/test_system_agent_config.py`
  - `autonomous/tests/test_system_agent_subagent_bridge_ws22_001.py`
  - `autonomous/ws22_longrun_baseline.py`
- 变更:
  - 新增 WS26 核心回归：
    - 强制 legacy 的 write 任务被收敛到 subagent；
    - subagent 禁用时 write 任务进入 `write_path` 门禁拒绝；
    - write 任务 fail-open 默认阻断；
    - 显式开启兼容开关后可 fail-open 回退 legacy。
  - 对历史 WS22 长稳/桥接基线显式开启兼容开关，避免旧场景被新默认策略误伤。

## 验证命令

1. WS26 写路径门禁回归
- `.\.venv\Scripts\python.exe -m pytest -q autonomous/tests/test_system_agent_write_path_ws26_001.py`

2. 关联配置与桥接回归
- `.\.venv\Scripts\python.exe -m pytest -q autonomous/tests/test_system_agent_config.py autonomous/tests/test_system_agent_subagent_bridge_ws22_001.py autonomous/tests/test_system_agent_subagent_rollout_ws22_006.py autonomous/tests/test_system_agent_lease_guard_ws22_004.py`

## 结果摘要

- write 任务的默认执行路径已强制收敛到 `SubAgentRuntime -> Scaffold/Txn`。
- fail-open 不再默认绕过原子提交路径。
- 当发生阻断时，事件链中有可审计的 `gate=write_path` 拒绝记录，可直接用于发布门禁与观测。
