# NGA-WS28-021 Phase C/D 实施记录（`.spec` 策略外置 + 门禁闭环）

最后更新：2026-02-27  
任务状态：`in_progress`（Phase C/D done）  
优先级：`P1`  
类型：`feature`

## 1. 目标

在 Phase B（语义守卫 + 可观测）基础上，完成两项收口：

1. Phase C：语义策略从代码常量外置到 `.spec`。
2. Phase D：治理信号进入 `M0-M12` 全链门禁，支持阻断。

## 2. 代码改动

1. `.spec` 外置（Phase C）
- 新增 `policy/role_executor_semantic_guard.spec`。
- `autonomous/tools/execution_bridge.py` 新增：
  - `DEFAULT_ROLE_EXECUTOR_SEMANTIC_GUARD_SPEC`
  - spec 路径解析与加载（缺失/非法回退）
  - role 级策略解析（`strict_semantic_guard` / `allowed_semantic_toolchains` / 默认值）
- 保留任务 contract 侧策略覆盖优先级，`policy_source` 保持可追踪。

2. 门禁闭环（Phase D）
- 新增脚本：`scripts/run_ws28_execution_governance_gate_ws28_021.py`
  - 聚合 `/ops/runtime_posture` 与 `/ops/incidents_latest` 侧治理信号
  - 增加策略文件门禁：`policy/role_executor_semantic_guard.spec`
    - 文件存在性
    - `schema_version` 校验
    - `frontend/backend/ops` 角色策略完整性
    - `sha256` 审计哈希输出
  - 输出 gate/runtime/incidents 三份报告
  - 核心检查项：
    - governance status 非 critical
    - critical 治理事故计数为 0
    - warning/rejection ratio 在预算内
- `scripts/release_closure_chain_full_m0_m12.py`
  - 新增 `m12_execution_governance` 组（`M12-T4`）
  - 新增 CLI 参数：
    - `--ws28-021-governance-output`
    - `--ws28-021-runtime-posture-output`
    - `--ws28-021-incidents-output`
    - `--skip-m12-governance`

## 3. 测试更新

1. `autonomous/tests/test_execution_bridge_role_executors_ws28_014.py`
- 新增 spec 驱动策略生效测试。
- 新增 spec 非法回退测试。

2. `tests/test_run_ws28_execution_governance_gate_ws28_021.py`
- 新增门禁脚本通过/失败双场景测试。

3. `tests/test_release_closure_chain_full_m0_m12.py`
- 新增 `m12_execution_governance` 组断言。
- 新增治理门禁失败即停链测试。

4. `doc/task/runbooks/release_m12_full_chain_m0_m12_onepager_ws27_004.md`
- 同步新增产物与判定标准。

## 4. 回归命令（本次）

```bash
.venv/bin/ruff check \
  autonomous/tools/execution_bridge.py \
  autonomous/tools/subagent_runtime.py \
  scripts/run_ws28_execution_governance_gate_ws28_021.py \
  scripts/release_closure_chain_full_m0_m12.py \
  autonomous/tests/test_execution_bridge_role_executors_ws28_014.py \
  autonomous/tests/test_subagent_runtime_eventbus_ws21_003.py \
  tests/test_run_ws28_execution_governance_gate_ws28_021.py \
  tests/test_release_closure_chain_full_m0_m12.py \
  tests/test_ops_dashboard_extensions.py

.venv/bin/pytest -q \
  autonomous/tests/test_execution_bridge_native_ws28_013.py \
  autonomous/tests/test_execution_bridge_role_executors_ws28_014.py \
  autonomous/tests/test_subagent_runtime_ws21_002.py \
  autonomous/tests/test_subagent_runtime_eventbus_ws21_003.py \
  autonomous/tests/test_system_agent_execution_bridge_cutover_ws28_013.py \
  tests/test_run_ws28_execution_governance_gate_ws28_021.py \
  tests/test_release_closure_chain_full_m0_m12.py \
  tests/test_ops_dashboard_extensions.py
```

## 5. 下一步

1. 将治理 reason_code 分层进 release signoff（hard/soft）策略表，不仅靠固定预算阈值。
2. 将 `role_executor_semantic_guard.spec` 纳入受控变更链（ACL + 审批票据 + 审计 ledger）。
