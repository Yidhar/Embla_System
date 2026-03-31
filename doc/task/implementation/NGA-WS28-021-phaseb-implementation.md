> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS28-021 Phase B 实施记录（语义工具链守卫 + 治理可观测）

最后更新：2026-02-27  
任务状态：`done`（Phase B done；后续 Phase C/D 收口已落地）  
优先级：`P1`  
类型：`feature`

## 1. 目标

在已完成的路径策略守卫（path policy）基础上，补齐两件事情：

1. FE/BE/Ops 执行器引入语义工具链守卫（semantic toolchain guard）。
2. 将拒绝原因结构化为治理字段，并接入 Runtime/Incident 聚合接口。

## 2. 代码改动

1. `agents/tool_loop.py`
- 扩展 `RoleExecutionPolicy`：
  - `strict_semantic_guard`
  - `allowed_semantic_toolchains`
- 为 FE/BE/Ops 执行器增加默认语义工具链白名单。
- 新增语义分类器（`_classify_semantic_toolchain`）与违规判定。
- 引入结构化治理载荷（`execution_bridge_governance`），包含：
  - `reason_code`
  - `category`
  - `severity/status`
  - `violations`
  - `policy_source`
  - `executor`
- `ExecutionBridgeReceipt` 增加 `governance` 字段，保证审计同源。

2. `agents/runtime/mini_loop.py`
- 将治理字段透传到标准事件：
  - `SubTaskExecutionBridgeReceipt`
  - `SubTaskExecutionCompleted`
  - `SubTaskRejected`
- 新增标准字段：
  - `execution_bridge_governance`
  - `execution_bridge_governance_reason_code`
  - `execution_bridge_governance_category`
  - `execution_bridge_governance_severity`

3. `apiserver/api_server.py`
- 新增 `_ops_build_execution_bridge_governance_summary()`，从事件流聚合治理信号。
- `/v1/ops/runtime/posture` 接入：
  - `summary.execution_bridge_governance_status`
  - `summary.execution_bridge_governance_reason_codes`
  - `metrics.execution_bridge_rejection_ratio`
  - `metrics.execution_bridge_governance_warning_ratio`
  - `data.execution_bridge_governance`
- `/v1/ops/incidents/latest` 接入：
  - `summary.execution_bridge_governance`
  - `summary.runtime_prompt_safety.execution_bridge_governance`
  - 新增 `ExecutionBridgeGovernanceIssue` incident 类型。

## 3. 测试更新

1. `tests/test_agent_roles_ws30_005.py`
- 新增语义守卫阻断断言。
- 新增结构化治理字段断言（path violation / ops ticket / warning）。

2. `tests/test_core_event_bus_consumers_ws28_029.py`
- 新增治理字段透传断言（completed/receipt/rejected）。

3. `tests/test_ops_dashboard_extensions.py`
- 新增 Runtime posture 聚合 execution governance 的断言。
- 新增 incidents 聚合 `ExecutionBridgeGovernanceIssue` 的断言。

## 4. 回归命令（本次执行）

```bash
.venv/bin/ruff check \
  agents/tool_loop.py \
  agents/runtime/mini_loop.py \
  tests/test_agent_roles_ws30_005.py \
  tests/test_core_event_bus_consumers_ws28_029.py \
  tests/test_ops_dashboard_extensions.py

.venv/bin/pytest -q \
  tests/test_agent_roles_ws30_005.py \
  tests/test_core_event_bus_consumers_ws28_029.py \
  tests/test_subagent_contract.py \
  tests/test_run_ws28_execution_governance_gate_ws28_021.py \
  tests/test_run_ws28_execution_governance_gate_ws28_021.py \
  tests/test_ops_dashboard_extensions.py
```

结果：通过。

## 5. 下一步建议（WS28-021 后续）

1. 将 semantic toolchain 白名单升级为外置 `.spec`（按角色可热更新并受 ACL 审计）。
2. 将治理 reason_code 进入发布门禁（例如 M12 gate 新增 hard/soft 策略分层）。
