# NGA-WS27-004 实施记录（M12：`release_closure_chain_full_m0_m12.py`）

## 任务信息
- 任务ID: `NGA-WS27-004`
- 标题: `release_closure_chain_full_m0_m12.py`
- 状态: 已完成（首版）

## 变更范围

1. M0-M12 全量收口链脚本
- 文件: `scripts/release_closure_chain_full_m0_m12.py`
- 变更:
  - 新增统一入口 `run_release_closure_chain_full_m0_m12(...)`。
  - 复用 `M0-M11` 基础链：`run_release_closure_chain_full_m0_m7(...)`。
  - 串联 `M12` 三个执行组：
    - `M12-T1`：`WS27-001` endurance baseline
    - `M12-T2`：`WS27-002` cutover `plan/apply/status`
    - `M12-T3`：`WS27-003` OOB repair drill
  - 支持 `skip` 组、`quick_mode`、`continue_on_failure` 与统一 JSON 报告输出。
  - 在 cutover 前自动补齐 `WS26` runtime snapshot（若缺失），降低远程环境首跑失败概率。

2. 自动化回归
- 文件: `tests/test_release_closure_chain_full_m0_m12.py`
- 变更:
  - 覆盖全绿路径（`M0-M11 + M12` 全链路组合）。
  - 覆盖默认失败即停路径（`m12_cutover` 失败时不继续执行 `m12_oob_repair`）。
  - 覆盖 `quick_mode` 参数透传（基础链 + `WS27-001` 快速参数集）。

3. 执行 runbook
- 文件: `doc/task/runbooks/release_m12_full_chain_m0_m12_onepager_ws27_004.md`
- 变更:
  - 固化远程环境快速验收与全量执行命令。
  - 明确产物路径与判定标准，作为 `M12` 收口链执行参考。

4. 任务快照更新
- 文件:
  - `doc/task/23-phase3-full-target-task-list.md`
  - `doc/task/runbooks/remote_test_env_handoff_phase3_m11_to_m12.md`
- 变更:
  - 将 `NGA-WS27-004` 标记为“首版已落地”，并补充代码锚点、验证命令与产物路径。

## 验证命令

1. WS27-004 定向回归
- `python3 -m pytest -q tests/test_release_closure_chain_full_m0_m12.py -p no:tmpdir`

2. 全量链兼容回归（M0-M11 + M0-M12）
- `python3 -m pytest -q tests/test_release_closure_chain_full_m0_m7.py tests/test_release_closure_chain_full_m0_m12.py -p no:tmpdir`

3. 代码规范
- `python3 -m ruff check scripts/release_closure_chain_full_m0_m12.py tests/test_release_closure_chain_full_m0_m12.py`

## 结果摘要

- `NGA-WS27-004` 已提供可执行的 `M0-M12` 统一收口入口，并与现有 `M0-M11` 链保持兼容。
- `M12` 三个任务（`WS27-001/002/003`）已被编排进同一报告域，便于发布门禁与追溯审计。
- 可作为后续 `NGA-WS27-005/006` 的文档一致性与放行签署输入。
