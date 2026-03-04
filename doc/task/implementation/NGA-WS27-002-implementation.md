> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS27-002 实施记录（M12：Legacy -> SubAgent Full Cutover + 回滚窗）

## 任务信息
- 任务ID: `NGA-WS27-002`
- 标题: Legacy -> SubAgent Full cutover 方案与回滚窗
- 状态: 已完成（首版）
- 状态: 已完成（含配置布局保真修复）

## 变更范围

1. Cutover 管理脚本
- 文件: `scripts/manage_ws27_subagent_cutover_ws27_002.py`
- 变更:
  - 新增 `plan/apply/rollback/status` 四类动作：
    - `plan`: 基于当前 `autonomous_config.yaml` 与 `WS26` 运行时快照生成分阶段 cutover 计划
    - `apply`: 应用目标 rollout（默认 100%），并落盘回滚快照
    - `rollback`: 优先从快照恢复；快照缺失时执行安全降级（`enabled=false + rollout_percent=0`）
    - `status`: 输出 cutover 完整性检查结果，作为门禁输入
  - 输出统一 JSON 报告，便于收口链与 runbook 追溯。
  - `apply/rollback` 写回配置时改为“仅更新 `subagent_runtime` 目标键”，尽量保留 YAML 既有布局与引号风格，避免无语义大 diff。

2. 回归测试
- 文件: `tests/test_manage_ws27_subagent_cutover_ws27_002.py`
- 变更:
  - 覆盖 `plan` 的 phase 计划与回滚窗产物。
  - 覆盖 `apply -> rollback` 的快照恢复闭环。
  - 覆盖“无快照回退”安全降级分支。
  - 覆盖 `status` 在非 full-cutover 场景下返回非零退出码。
  - 覆盖 `apply` 后非 `subagent_runtime` 区域布局保真（如 `cli_tools` 引号与 inline 列表风格）。

3. 执行 runbook
- 文件: `doc/task/runbooks/release_m12_cutover_rollback_onepager_ws27_002.md`
- 变更:
  - 固化执行顺序（plan/apply/status/rollback）与预期产物路径。
  - 明确“快照缺失时安全降级”行为与最终放行前置条件。

4. 任务快照更新
- 文件: `doc/task/23-phase3-full-target-task-list.md`
- 变更:
  - 新增 `NGA-WS27-002` 本轮落地说明、代码锚点与回归项。

## 验证命令

1. WS27-002 定向回归
- `python -m pytest -q tests/test_manage_ws27_subagent_cutover_ws27_002.py -p no:tmpdir`

2. 联合 WS27 最小回归
- `python -m pytest -q tests/test_ws27_longrun_endurance_ws27_001.py tests/test_run_ws27_longrun_endurance_ws27_001.py tests/test_manage_ws27_subagent_cutover_ws27_002.py -p no:tmpdir`

## 结果摘要

- 已具备可执行 cutover 计划与一键回退能力，满足 WS27-002 的核心验收方向。
- 具备“回滚快照恢复”与“快照缺失兜底降级”双通道，降低远程环境误操作风险。
- 可作为后续 `NGA-WS27-004`（M0-M12 全量收口链）中的 M12 cutover 步骤输入。
- 配置写回由“全文件重排”收敛为“目标字段最小改动”，减少提交噪音并降低误审风险。
