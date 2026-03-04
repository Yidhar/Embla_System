> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS16-002 实施记录（AgentServer 弃用路径 Phase 2 设计）


> Migration Note (archived/legacy)
> 文中 `autonomous/*` 路径属于历史实现标识；当前实现请优先使用 `agents/*`、`core/*` 与 `config/autonomous_runtime.yaml`。

## 任务信息
- Task ID: `NGA-WS16-002`
- Title: AgentServer 弃用路径 Phase 2 设计
- 状态: 已完成（进入 review）

## 本次范围（仅 WS16-002）
1. 弃用路径 Runbook 固化
- 新增 `doc/task/runbooks/agentserver_phase2_deprecation_runbook.md`
  - 明确当前耦合基线（启动、配置、兼容 helper）
  - 给出 Phase-2 删除顺序（D0~D4）
  - 对齐替代链路（`apiserver + agentic_tool_loop + native/mcp` 与 `autonomous/system_agent`（archived/legacy））
  - 明确阶段门禁与回退动作

2. “不新增 agentserver 依赖”自动化守门
- 新增 `tests/test_agentserver_deprecation_guard_ws16_002.py`
  - 扫描核心 Python 目录的直接导入语句（`from/import agentserver`）
  - 仅允许历史过渡点 `main.py`（allowlist）
  - 新增导入即失败，阻断依赖扩散

## 验证命令
- `python -m pytest -q tests/test_agentserver_deprecation_guard_ws16_002.py`
  - 结果: `passed`
- `python -m ruff check tests/test_agentserver_deprecation_guard_ws16_002.py`
  - 结果: `All checks passed`

## 交付结果与验收对应
- 删除顺序：已在 runbook 明确 D0~D4 阶段执行顺序。
- 替代链路：已在 runbook 明确新链路组件与迁移目标。
- 回退策略：已在 runbook 明确开关回切、配置回滚、端口兼容策略。
- 验收“`不新增 agentserver 依赖`”：由 guard test 自动化执行。

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `doc/task/runbooks/agentserver_phase2_deprecation_runbook.md; tests/test_agentserver_deprecation_guard_ws16_002.py; doc/task/implementation/NGA-WS16-002-implementation.md`
- `notes`:
  - `phase-2 deprecation runbook now defines D0-D4 removal order, replacement links, and rollback gates; an automated guard blocks new direct agentserver imports outside transitional allowlist`

## Date
2026-02-24
