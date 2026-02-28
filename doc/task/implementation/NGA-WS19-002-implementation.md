> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS19-002 实施记录（Router 规则引擎与角色路由）

## 任务信息
- Task ID: `NGA-WS19-002`
- Title: Router 规则引擎与角色路由
- 状态: 已完成（进入 review）

## 本次范围（仅 WS19-002）
1. 路由引擎实现
- 新增 `autonomous/router_engine.py`
  - 请求模型：`RouterRequest`
    - `description / risk_level / budget_remaining / estimated_complexity / trace_id / session_id`
  - 决策模型：`RouterDecision`
    - `task_type / selected_role / selected_model_tier / tool_profile`
    - `reasoning`（可解释原因）
    - `replay_fingerprint`（可重放一致性指纹）
  - 核心逻辑：`TaskRouterEngine.route(...)`
    - 按任务类型（ops/development/research/general）分类
    - 按风险等级选择角色（高风险强制 `sys_admin`）
    - 按预算/复杂度分层模型（`primary/secondary/local`）
    - 生成 deterministic `replay_fingerprint`
  - 可重放：`TaskRouterEngine.replay(...)`
    - 同请求复算指纹，验证决策可重放一致性
  - 审计：支持 `decision_log` jsonl 落盘（请求+决策）

2. 包级导出
- 更新 `autonomous/__init__.py`
  - 导出 `TaskRouterEngine`、`RouterRequest`、`RouterDecision`

3. 测试覆盖
- 新增 `autonomous/tests/test_router_engine_ws19_002.py`
  - 高风险运维任务路由到 `sys_admin + primary`
  - 预算分层（低预算 local / 中预算 secondary）
  - 决策可重放一致性（fingerprint）
  - 决策审计日志落盘

## 验证命令
- `python -m ruff check autonomous/router_engine.py autonomous/__init__.py autonomous/tests/test_router_engine_ws19_002.py`
  - 结果: `All checks passed`
- `python -m pytest -q autonomous/tests/test_router_engine_ws19_002.py autonomous/tests/test_meta_agent_runtime_ws19_001.py autonomous/tests/test_event_replay_tool_ws18_003.py`
  - 结果: `passed`

## 交付结果与验收对应
- 交付“按任务类型/风险/预算路由角色与模型”：已落地规则引擎。
- 验收“路由决策可解释且可重放”：
  - 可解释：`reasoning` 字段
  - 可重放：`replay_fingerprint` + `replay(...)` 验证
- 回退策略：可通过 `requested_role` 或固定 fallback role 做兜底。

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `autonomous/router_engine.py; autonomous/__init__.py; autonomous/tests/test_router_engine_ws19_002.py; doc/task/implementation/NGA-WS19-002-implementation.md`
- `notes`:
  - `router engine now performs deterministic role/model routing by task type risk and budget, emits explainable reasoning, and supports replay fingerprint verification with decision audit logging`

## Date
2026-02-24
