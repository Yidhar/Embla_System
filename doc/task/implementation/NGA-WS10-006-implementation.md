> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS10-006 实施记录（兼容开关与灰度发布策略）

## 任务信息
- Task ID: `NGA-WS10-006`
- Title: 兼容开关与灰度发布策略
- 状态: 已完成（进入 review）

## 结论
`NGA-WS10-006` 的能力已由 `NGA-WS16-005` 实装并验证，本次完成任务映射与证据收敛，不重复引入并行实现。

## 已落地能力（复用 WS16-005）
1. 双栈兼容开关
- `system/config.py`
  - `ToolContractRolloutConfig.mode`:
    - `legacy_only`
    - `dual_stack`
    - `new_stack_only`
  - 模式别名归一化（`legacy/dual/new`）

2. 渐进灰度与下线门禁
- `apiserver/agentic_tool_loop.py`
  - 按 rollout 模式执行 legacy/new contract 的补齐、兼容与阻断
  - 下线门禁错误码：`E_LEGACY_CONTRACT_DECOMMISSIONED`
  - 输出 rollout snapshot 与 metadata 供观测/回滚判断

3. 迁移与回滚配套
- `scripts/config_migration_ws16_004.py`
  - 自动补齐 `tool_contract_rollout` 默认字段
  - 保留非破坏式 backup/restore 迁移路径

4. 验证覆盖
- `tests/test_contract_rollout_ws16_005.py`
- `tests/test_config_migration_ws16_004.py`
- `tests/test_tool_schema_validation.py`

## 验证命令
- `powershell -ExecutionPolicy Bypass -File scripts/run_tests_safe.ps1 tests/test_contract_rollout_ws16_005.py tests/test_config_migration_ws16_004.py tests/test_tool_schema_validation.py tests/test_agentic_loop_contract_and_mutex.py`
  - 结果: `22 passed`

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `system/config.py; apiserver/agentic_tool_loop.py; scripts/config_migration_ws16_004.py; tests/test_contract_rollout_ws16_005.py; tests/test_config_migration_ws16_004.py; doc/task/implementation/NGA-WS10-006-implementation.md`
- `notes`:
  - `ws10-006 rollout controls are delivered via ws16-005: mode-gated dual stack (legacy_only/dual_stack/new_stack_only), decommission gate, rollout snapshot metadata, and migration defaults with rollback path`

## Date
2026-02-24
