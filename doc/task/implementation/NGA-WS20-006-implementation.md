> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS20-006 实施记录（桌面端发布兼容性验证）

## 任务信息
- Task ID: `NGA-WS20-006`
- Title: 桌面端发布兼容性验证
- 状态: 已完成（进入 review）

## 本次范围（仅 WS20-006）
1. 新增自动化兼容检查器
- 新增 `scripts/desktop_release_compat_ws20_006.py`
- 输出统一 JSON 报告：`doc/task/reports/ws20_006_desktop_compat_report.json`
- `--strict` 模式可作为发布门禁（失败即非 0 退出）

2. 新增 WS20-006 回归测试
- 新增 `tests/test_embla_core_release_compat_gate.py`
- 覆盖：
  - 兼容报告结构与关键检查项完整
  - 场景矩阵（配置/网络/权限）完整
  - 报告可稳定写出

3. 新增发布验证 Runbook
- 新增 `doc/task/runbooks/desktop_release_compat_ws20_006.md`
- 定义自动化入口、场景矩阵、手工补充验证与 M5 出场条件

## 验证命令
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_embla_core_release_compat_gate.py`
- `.\.venv\Scripts\python.exe scripts/desktop_release_compat_ws20_006.py --strict`

## 交付结果与验收对应
- deliverables“不同配置与网络场景兼容报告”：脚本生成结构化报告并落盘。
- acceptance“关键平台可稳定运行”：通过自动化项覆盖发布脚本/打包目标/网络退化与权限退化路径，并在 runbook 明确多平台验证步骤。
- rollback“暂停升级并回退前一稳定包”：runbook 中保留发布门禁与回退策略。

## Date
2026-02-24
