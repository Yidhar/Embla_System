> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS23-006 实施记录（M8 门禁脚本链 + Runbook）

## 1. 背景

WS23-001~005 能力虽已具备，但缺少统一的 M8 门禁执行链与出场判定。
需要把报告产物、文档状态、runbook 完整串联到发布链，形成可回归、可审计的收口闭环。

## 2. 实施内容

1. 新增 M8 门禁评估器
   - 新增 `autonomous/ws23_release_gate.py`，聚合以下检查：
     - WS23-001/003/004/005 报告存在性与 `passed/task_id/scenario` 一致性；
     - WS23 任务文档快照项（002~006）是否落盘；
     - M8 runbook 是否包含链路命令与 gate 命令。
   - 新增入口 `scripts/validate_m8_closure_gate_ws23_006.py`。

2. 新增 M8 发布链脚本
   - 新增 `scripts/release_closure_chain_m8_ws23_006.py`，串行执行 T0-T6：
     - T0 WS23 回归
     - T1 Brainstem Supervisor dry-run
     - T2 Immutable DNA gate
     - T3 KillSwitch OOB bundle
     - T4 Outbox bridge smoke
     - T5 M8 gate 校验
     - T6 文档一致性终检

3. 接入全量发布链
   - 更新 `scripts/release_closure_chain_full_m0_m7.py`：
     - 新增 `m8` group；
     - 新增参数 `--m8-output`、`--skip-m8`；
     - `quick-mode` 下转发 M8 skip 参数。
   - 更新 `scripts/render_release_closure_summary.py`，支持 `m8` 报告展示。

4. runbook 与任务文档更新
   - 新增 `doc/task/runbooks/release_m8_phase3_closure_onepager_ws23_006.md`。
   - 更新 `doc/task/23-phase3-full-target-task-list.md` 快照（标记 WS23-005/006 已落地）。
   - 更新 `doc/task/README.md` 与 `doc/00-omni-operator-architecture.md` 证据矩阵。

## 3. 变更文件

- `autonomous/ws23_release_gate.py`
- `scripts/validate_m8_closure_gate_ws23_006.py`
- `scripts/release_closure_chain_m8_ws23_006.py`
- `scripts/release_closure_chain_full_m0_m7.py`
- `scripts/render_release_closure_summary.py`
- `autonomous/tests/test_ws23_release_gate.py`
- `tests/test_release_closure_chain_m8_ws23_006.py`
- `tests/test_release_closure_chain_full_m0_m7.py`
- `tests/test_render_release_closure_summary.py`
- `doc/task/runbooks/release_m8_phase3_closure_onepager_ws23_006.md`
- `doc/task/23-phase3-full-target-task-list.md`
- `doc/task/README.md`
- `doc/00-omni-operator-architecture.md`

## 4. 验证记录

```bash
.\.venv\Scripts\python.exe -m pytest -q autonomous/tests/test_ws23_release_gate.py tests/test_release_closure_chain_m8_ws23_006.py tests/test_release_closure_chain_full_m0_m7.py tests/test_render_release_closure_summary.py -p no:tmpdir
```

## 5. 结果

- M8 已形成独立收口链并接入全量发布链。
- 发布报告可同时展示 `m0_m5/m6_m7/m8` 三段执行状态，满足 Phase3 继续放量的门禁基础要求。

