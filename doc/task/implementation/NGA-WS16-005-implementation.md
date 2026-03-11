> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS16-005 实施记录

> 历史说明（2026-03-10 refresh）
> - 本文记录的是过渡阶段的 rollout 与兼容清理实施证据。
> - 当前运行时 canonical 已收口为结构化工具契约唯一执行链，仅保留 `emit_observability_metadata` 作为观测开关。
> - 文中涉及的旧 rollout mode、兼容门禁与对应错误码均已退出主运行链，仅保留迁移脚本对历史配置输入的吸收能力。

## 任务信息
- Task ID: `NGA-WS16-005`
- Title: 兼容双栈灰度与下线开关
- 状态: 已完成（历史归档）

## 历史实施范围
1. 当时为工具结果契约引入 rollout 配置、观测元数据和迁移路径。
2. 当时为旧配置输入补充升级脚本、回退路径与回归测试。
3. 当前这些兼容控制已完成历史使命，主运行链仅保留结构化契约与观测元数据开关。

## 当前口径
- Runtime：仅结构化工具结果契约。
- Config：`tool_contract_rollout` 仅保留 `emit_observability_metadata`。
- Migration：仍接受历史输入并在升级时移除已退役字段。
- Documentation：以 `doc/09-tool-execution-specification.md` 与当前代码为准。

## 验证记录（历史）
- `uv --cache-dir .uv_cache run python -m pytest -q tests/test_contract_rollout_ws16_005.py tests/test_config_migration_ws16_004.py tests/test_tool_schema_validation.py tests/test_agentic_loop_contract_and_mutex.py`
  - 结果: `22 passed`
- `uv --cache-dir .uv_cache run python -m ruff check apiserver/agentic_tool_loop.py system/config.py scripts/config_migration_ws16_004.py tests/test_contract_rollout_ws16_005.py tests/test_config_migration_ws16_004.py`
  - 结果: `All checks passed`

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `apiserver/agentic_tool_loop.py; system/config.py; config.json.example; scripts/config_migration_ws16_004.py; tests/test_contract_rollout_ws16_005.py; tests/test_config_migration_ws16_004.py; doc/task/implementation/NGA-WS16-005-implementation.md`
- `notes`:
  - `historical rollout cleanup landed here; current runtime has since converged to the structured-only tool contract path with observability metadata retained`

## Date
2026-02-24
