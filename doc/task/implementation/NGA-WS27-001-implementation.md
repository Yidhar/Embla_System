> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS27-001 实施记录（M12：72h 长稳 + 磁盘配额压测）

## 任务信息
- 任务ID: `NGA-WS27-001`
- 标题: 72h 长稳耐久脚本与磁盘配额压测
- 状态: 已完成（首版）

## 变更范围

1. 72h 耐久 + 配额压测 baseline harness
- 文件: `autonomous/ws27_longrun_endurance.py`
- 变更:
  - 新增 `WS27LongRunConfig` 与 `run_ws27_72h_endurance_baseline(...)`。
  - 在虚拟 72h（默认 72h/300s round）下执行持续写入：
    - 低/中/高优先级 artifact 混合写入（触发高水位清理与配额背压）
    - EventBus topic 事件持续发布（`system.ws27.longrun`）
  - 报告内置关键验收检查：
    - `no_enospc`
    - `no_unhandled_exceptions`
    - `no_event_loss`
    - `disk_quota_pressure_exercised`

2. 脚本入口
- 文件: `scripts/run_ws27_longrun_endurance_ws27_001.py`
- 变更:
  - 提供可参数化 CLI 入口，支持远程环境两类执行：
    - 默认 72h 配置（用于正式验收）
    - 缩短参数（用于快速演练/回归）
  - 默认报告路径:
    - `scratch/reports/ws27_72h_endurance_ws27_001.json`

3. 自动化回归
- 文件:
  - `autonomous/tests/test_ws27_longrun_endurance_ws27_001.py`
  - `tests/test_run_ws27_longrun_endurance_ws27_001.py`
- 变更:
  - baseline 回归覆盖报告结构与关键检查结果。
  - CLI smoke 覆盖参数解析、执行与落盘路径。

4. 真实 72h 墙钟验收记录脚本（补充）
- 文件:
  - `scripts/manage_ws27_72h_wallclock_acceptance_ws27_001.py`
  - `tests/test_manage_ws27_72h_wallclock_acceptance_ws27_001.py`
- 变更:
  - 新增 `start/status/finish` 三段式墙钟验收记录管理。
  - 将“真实 72h 验收证据”独立成 `scratch/reports/ws27_72h_wallclock_acceptance_ws27_001.json`。
  - `finish --strict` 可直接作为签署前的硬门禁命令。

5. 任务快照更新
- 文件: `doc/task/23-phase3-full-target-task-list.md`
- 变更:
  - 在“本轮推进快照”新增 `NGA-WS27-001` 首版落地说明与代码锚点。

## 验证命令

1. WS27-001 baseline + CLI 回归
- `python3 -m pytest -q autonomous/tests/test_ws27_longrun_endurance_ws27_001.py tests/test_run_ws27_longrun_endurance_ws27_001.py -p no:tmpdir`

2. 单独运行 WS27-001 脚本（快速演练）
- `python3 scripts/run_ws27_longrun_endurance_ws27_001.py --target-hours 0.02 --virtual-round-seconds 6 --artifact-payload-kb 256 --max-total-size-mb 1 --max-single-artifact-mb 1 --max-artifact-count 256 --high-watermark-ratio 0.8 --low-watermark-ratio 0.5 --critical-reserve-ratio 0.1 --normal-priority-every 3 --high-priority-every 8`

3. 墙钟验收记录（补充）
- `python3 scripts/manage_ws27_72h_wallclock_acceptance_ws27_001.py --action start --target-hours 72`
- `python3 scripts/manage_ws27_72h_wallclock_acceptance_ws27_001.py --action status`
- `python3 scripts/manage_ws27_72h_wallclock_acceptance_ws27_001.py --action finish --strict`

## 结果摘要

- `NGA-WS27-001` 已具备可执行、可回归、可审计的首版脚本。
- 默认配置可覆盖 “72h 长稳 + 配额压力 + 事件完整性” 的统一报告产物。
- 该脚本为后续 `NGA-WS27-004`（M0-M12 全量收口链）提供 `M12/T1` 可复用入口。
