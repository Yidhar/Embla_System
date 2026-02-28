> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS16-005 实施记录（兼容双栈灰度与下线开关）

## 任务信息
- Task ID: `NGA-WS16-005`
- Title: 兼容双栈灰度与下线开关
- 状态: 已完成（进入 review）

## 本次范围（仅 WS16-005）
1. 配置模型与运行时灰度策略
- `system/config.py`
  - 新增 `ToolContractRolloutConfig`
  - 支持 `mode`: `legacy_only` / `dual_stack` / `new_stack_only`
  - 支持别名归一化：`legacy`/`dual`/`new` 等
  - 新增 `decommission_legacy_gate` 与 `emit_observability_metadata`
- `config.json.example`
  - 新增 `tool_contract_rollout` 配置段

2. Agentic Loop 契约双栈接线与门禁
- `apiserver/agentic_tool_loop.py`
  - 新增 `ToolContractRolloutRuntime` 运行态解析
  - 在 `_enforce_tool_result_schema` 中按模式执行兼容与门禁：
    - `dual_stack`: 补齐新契约字段
    - `legacy_only`: 必要时回填 legacy `result`
    - `new_stack_only` 或 `decommission_legacy_gate=true`: 阻断 legacy-only payload
  - 新增错误码：`E_LEGACY_CONTRACT_DECOMMISSIONED`
  - 新增观测事件：
    - `contract_rollout_snapshot`
    - `tool_results.metadata.contract_rollout`
    - `guardrail(type=legacy_contract_decommission_gate)`

3. 迁移脚本补齐新配置字段
- `scripts/config_migration_ws16_004.py`
  - 新增 `_ensure_tool_contract_rollout`
  - 升级时自动补齐 rollout 默认字段并规范化 mode
  - 保持现有 backup/restore 非破坏式策略

4. 测试覆盖
- 新增 `tests/test_contract_rollout_ws16_005.py`
  - 默认值、模式别名、双栈回填、下线门禁阻断、SSE 元数据可观测
- 更新 `tests/test_config_migration_ws16_004.py`
  - rollout 字段补齐与已有值保留

## 验证命令
- `uv --cache-dir .uv_cache run python -m pytest -q tests/test_contract_rollout_ws16_005.py tests/test_config_migration_ws16_004.py tests/test_tool_schema_validation.py tests/test_agentic_loop_contract_and_mutex.py`
  - 结果: `22 passed`
- `uv --cache-dir .uv_cache run python -m ruff check apiserver/agentic_tool_loop.py system/config.py scripts/config_migration_ws16_004.py tests/test_contract_rollout_ws16_005.py tests/test_config_migration_ws16_004.py`
  - 结果: `All checks passed`

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `apiserver/agentic_tool_loop.py; system/config.py; config.json.example; scripts/config_migration_ws16_004.py; tests/test_contract_rollout_ws16_005.py; tests/test_config_migration_ws16_004.py; doc/task/implementation/NGA-WS16-005-implementation.md`
- `notes`:
  - `dual-stack tool contract rollout landed with mode gates (legacy_only/dual_stack/new_stack_only), decommission guardrail E_LEGACY_CONTRACT_DECOMMISSIONED, rollout snapshot metadata, and migration defaults with focused regression coverage`

## Date
2026-02-24
