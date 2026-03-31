> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS28-020 实施记录（脑干控制面托管入口标准化）

最后更新：2026-02-27  
任务状态：`done`  
优先级：`P0`  
类型：`ops`

## 1. 背景问题

在 `WS28-017/018` 链路已可用后，托管入口仍存在两个一致性缺口：

1. 管理脚本输出文件与函数返回对象字段不完全一致（`output_file` 写盘缺失）。
2. 全链验收对脑干步骤只校验 `start/status` 基本通过，缺少“同源状态文件/心跳文件”一致性约束，排障锚点不足。

## 2. 目标

1. 统一 `start/status/stop` 三类动作的报告写盘契约。
2. 在 `M12` 脑干步骤加入同源校验，确保 `start` 与 `status` 针对同一状态文件与心跳文件。
3. 同步 runbook，使“单独托管验收”与“全链验收”完全同源。

## 3. 代码改动

1. `scripts/manage_brainstem_control_plane_ws28_017.py`
- 新增 `REPORT_SCHEMA_VERSION=ws28_017_brainstem_control_plane_manage.v1`。
- 新增 `_finalize_report()` 统一封装写盘逻辑，保证写盘与返回包含同一 `output_file`、`report_schema_version`。
- `start/status/stop` 返回体统一包含 `repo_root`。

2. `scripts/release_closure_chain_full_m0_m12.py`
- `M12-T0`（`m12_brainstem_control_plane`）新增标准校验字段：
  - `start_spawn_or_already_running`
  - `manager_state_exists`
  - `status_heartbeat_exists`
  - `state_file_consistent`
  - `heartbeat_file_consistent`
- 在步骤报告增加：
  - `action_sequence=["start","status"]`
  - `source_contract`（`state_file`/`heartbeat_file`/`manager_log`）

3. `doc/task/runbooks/release_m12_full_chain_m0_m12_onepager_ws27_004.md`
- 新增“托管入口单独验收”命令（`start + status`，与全链同源）。
- 新增“托管入口清理（stop）”命令。
- 判定标准增加上述新检查项。

## 4. 测试与验证

更新测试：

1. `tests/test_manage_brainstem_control_plane_ws28_017.py`
- 断言 `report_schema_version` 存在且稳定。
- 断言 `output_file` 在写盘报告中可见，`start/status/stop` 均生效。

2. `tests/test_release_closure_chain_full_m0_m12.py`
- 断言 `m12_brainstem_control_plane` 步骤包含 `action_sequence`。
- 断言 `state_file_consistent`、`heartbeat_file_consistent`、`start_spawn_or_already_running` 为真。

回归命令（本次执行）：

```bash
.venv/bin/ruff check \
  scripts/manage_brainstem_control_plane_ws28_017.py \
  scripts/release_closure_chain_full_m0_m12.py \
  tests/test_manage_brainstem_control_plane_ws28_017.py \
  tests/test_release_closure_chain_full_m0_m12.py

.venv/bin/pytest -q \
  tests/test_manage_brainstem_control_plane_ws28_017.py \
  tests/test_release_closure_chain_full_m0_m12.py
```

结果：通过。

## 5. 影响范围

1. 托管入口报告口径统一，便于 Runtime 看板与后续自动审计直接消费。
2. 全链验收的脑干步骤从“可运行”提升到“同源可追踪”。
3. 为下一步 `NGA-WS28-021`（角色专用执行器 v2）保留稳定运维基座。
