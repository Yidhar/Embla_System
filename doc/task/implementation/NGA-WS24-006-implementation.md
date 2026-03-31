> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS24-006 实施记录（M9 发布门禁接入）

## 1. 背景

M9 目标要求“插件隔离能力必须进入发布收口链”。
本任务将 WS24-005 演练结果、文档状态与 runbook 可执行性纳入统一 gate。

## 2. 实施内容

1. 新增 M9 门禁评估器
   - `agents/release_gates/ws24_release_gate.py`
   - 校验项：
     - WS24-005 混沌演练报告存在且通过
     - 任务文档包含 WS24-002~006 已落地快照
     - runbook 包含 m9 chain/m9 gate/full chain 命令

2. 新增 M9 门禁脚本入口
   - `scripts/validate_m9_closure_gate_ws24_006.py`
   - 统一输出 `scratch/reports/ws24_m9_closure_gate_result.json`

3. 新增 M9 收口链
   - `scripts/release_closure_chain_m9_ws24_006.py`
   - 标准步骤：
     - `T0` M9 定向回归
     - `T1` WS24-005 混沌演练
     - `T2` WS24-006 门禁校验
     - `T3` 文档一致性检查

4. 接入全量收口链
   - `scripts/release_closure_chain_full_m0_m7.py` 扩展 `m9` group（保留兼容命名）
   - `scripts/render_release_closure_summary.py` 扩展 m9 汇总行与报告路径

5. 新增 runbook
   - `doc/task/runbooks/release_m9_plugin_isolation_closure_onepager_ws24_006.md`

## 3. 变更文件

- `agents/release_gates/ws24_release_gate.py`
- `tests/test_release_closure_chain_m9_ws24_006.py`
- `scripts/validate_m9_closure_gate_ws24_006.py`
- `scripts/release_closure_chain_m9_ws24_006.py`
- `tests/test_release_closure_chain_m9_ws24_006.py`
- `scripts/release_closure_chain_full_m0_m7.py`
- `tests/test_release_closure_chain_full_m0_m7.py`
- `scripts/render_release_closure_summary.py`
- `tests/test_render_release_closure_summary.py`
- `doc/task/runbooks/release_m9_plugin_isolation_closure_onepager_ws24_006.md`

## 4. 验证记录

```bash
.\.venv\Scripts\python.exe -m pytest -q tests/test_release_closure_chain_m9_ws24_006.py tests/test_release_closure_chain_m9_ws24_006.py tests/test_release_closure_chain_full_m0_m7.py tests/test_render_release_closure_summary.py
```

## 5. 结果

- M9 发布门禁已具备独立执行入口与可追踪报告。
- 全量收口链已可调度至 M9，Phase3 发布收口从 M0-M8 扩展到 M0-M9。
