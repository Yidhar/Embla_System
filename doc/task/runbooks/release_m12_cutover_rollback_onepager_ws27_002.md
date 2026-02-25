# M12 一页式执行清单（WS27-002：Legacy -> SubAgent Full Cutover + 回滚窗）

适用任务：`NGA-WS27-002`  
默认分支：`modifier/naga`

## 1. 目标

- 将 `subagent_runtime` 从灰度态推进到 `100%`（Full Cutover）。
- 保留可审计回滚窗口，支持“一键回退”到切换前配置。

## 2. 关键脚本

- 主脚本：`scripts/manage_ws27_subagent_cutover_ws27_002.py`
- 默认配置文件：`autonomous/config/autonomous_config.yaml`
- 默认回滚快照：`scratch/reports/ws27_subagent_cutover_rollback_snapshot_ws27_002.json`
- 默认报告输出：`scratch/reports/ws27_subagent_cutover_ws27_002.json`

## 3. 推荐执行顺序

1. 生成 cutover 计划（读取 WS26 运行时快照）

```powershell
.\.venv\Scripts\python.exe -m scripts.manage_ws27_subagent_cutover_ws27_002 `
  --action plan `
  --runtime-snapshot-report scratch/reports/ws26_runtime_snapshot_ws26_002.json `
  --output scratch/reports/ws27_subagent_cutover_plan_ws27_002.json
```

2. 应用目标 rollout（例如 100%，并可选禁用 fail-open）

```powershell
.\.venv\Scripts\python.exe -m scripts.manage_ws27_subagent_cutover_ws27_002 `
  --action apply `
  --rollout-percent 100 `
  --disable-fail-open `
  --output scratch/reports/ws27_subagent_cutover_apply_ws27_002.json
```

3. 状态检查（作为 cutover 完整性门禁）

```powershell
.\.venv\Scripts\python.exe -m scripts.manage_ws27_subagent_cutover_ws27_002 `
  --action status `
  --runtime-snapshot-report scratch/reports/ws26_runtime_snapshot_ws26_002.json `
  --output scratch/reports/ws27_subagent_cutover_status_ws27_002.json
```

4. 一键回退（恢复到 apply 前快照）

```powershell
.\.venv\Scripts\python.exe -m scripts.manage_ws27_subagent_cutover_ws27_002 `
  --action rollback `
  --output scratch/reports/ws27_subagent_cutover_rollback_ws27_002.json
```

## 4. 预期产物

1. `scratch/reports/ws27_subagent_cutover_plan_ws27_002.json`
2. `scratch/reports/ws27_subagent_cutover_apply_ws27_002.json`
3. `scratch/reports/ws27_subagent_cutover_status_ws27_002.json`
4. `scratch/reports/ws27_subagent_cutover_rollback_ws27_002.json`
5. `scratch/reports/ws27_subagent_cutover_rollback_snapshot_ws27_002.json`

## 5. 判定标准

- `status` 报告 `passed=true`：
  - `subagent_runtime_enabled=true`
  - `rollout_percent_is_full=true`
  - `runtime_snapshot_ready=true`
  - `rollback_snapshot_exists=true`

## 6. 风险与回退说明

- 若回滚快照缺失，`rollback` 会执行安全降级：强制 `enabled=false` 且 `rollout_percent=0`。
- 真实放行前仍需结合 `WS27-001` 真实墙钟 72h 验收记录进行最终签署，不仅依赖虚拟等效脚本结果。
