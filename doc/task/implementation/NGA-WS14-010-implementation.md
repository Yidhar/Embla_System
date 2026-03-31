> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS14-010 实施记录

## 任务信息
- 任务ID: `NGA-WS14-010`
- 标题: KillSwitch OOB 健康探测与恢复 runbook
- 状态: `review`
- 依赖: `NGA-WS14-009`

## 本次实现

### 1) OOB 健康探测 helper（与现有 marker/allowlist 一致）
- 文件: `system/killswitch_guard.py`
- 新增:
  - `build_oob_health_probe_plan(...)`
  - `validate_oob_health_probe_plan(...)`
- 对齐策略:
  - 继续使用统一 marker：`OOB_ALLOWLIST_ENFORCED`
  - 复用 allowlist 归一化逻辑（IP/CIDR + hostname）
  - probe target 必须被 allowlist 覆盖，否则拒绝生成/校验通过
- 兼容性:
  - `build_oob_killswitch_plan(...)` 接口未破坏，仅将 marker 改为常量复用

### 2) 回归测试
- 文件: `tests/test_native_executor_guards.py`
- 新增用例:
  - `test_oob_health_probe_plan_valid_with_marker_and_allowlist`
    - 覆盖“有 OOB marker 且 allowlist 合法”的正向路径。
  - `test_oob_health_probe_plan_rejects_missing_marker`
    - 覆盖缺 marker 的错误路径。
  - `test_oob_health_probe_plan_rejects_probe_target_outside_allowlist`
    - 覆盖 probe target 不在 allowlist 内的错误路径。

### 3) 运行手册
- 文件: `doc/task/runbooks/killswitch_oob_runbook.md`
- 内容覆盖:
  - 触发条件
  - OOB 健康探测（熔断前/后）
  - disarm / recover
  - 回滚

## 验证
- 最小回归命令:
  - `uv --cache-dir .uv_cache run python -m pytest -q tests/test_native_executor_guards.py`
- 结果:
  - ✅ 29 passed（含本任务新增用例）
  - ⚠️ 环境告警：`PytestCacheWarning`（`.pytest_cache` 写入被拒绝），不影响用例通过

## 已知边界与风险
1. 健康探测计划中的 `ping` / `nc` 依赖目标主机具备对应命令，若环境精简需替换为等效探测器。
2. 当前 helper 以“allowlist 覆盖关系 + 规则检查命令形态”为主，未直接执行真实网络连通性验证；真实验证仍需 runbook 执行时落地。

## 时间
2026-02-24
