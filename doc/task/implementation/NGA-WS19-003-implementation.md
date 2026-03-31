> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS19-003 实施记录（LLM Gateway 分层路由与缓存）


> 口径说明（archived）
> 文中 `autonomous/*` 路径属于历史实现标识；当前实现请优先使用 `agents/*`、`core/*` 与 `config/autonomous_runtime.yaml`。

## 任务信息
- Task ID: `NGA-WS19-003`
- Title: LLM Gateway 分层路由与缓存
- 状态: 已完成（进入 review）

## 本次范围（仅 WS19-003）
1. LLM Gateway 核心模块
- 新增 `agents/llm_gateway.py`
  - 路由输入：`GatewayRouteRequest`
  - 路由输出：`GatewayRouteDecision`
  - Prompt 封装输入：`PromptEnvelopeInput`
  - Prompt 三段封装：`PromptEnvelope`
  - 缓存结果：`PromptCacheOutcome`
  - 指标估算：`GatewayPlanMetrics`
  - 执行计划：`GatewayPlan`
  - 核心类：`LLMGateway`
    - `route(...)`：按任务类型/严重级别/预算选择 `primary|secondary|local`
    - `build_prompt_envelope(...)`：构建 Block1/2/3 与 token 估算
    - `apply_prompt_cache(...)`：Block1/2 缓存命中管理，Block3 明确不缓存
    - `build_plan(...)`：路由 + Prompt 封装 + 缓存 + 指标估算一体化
    - `estimate_metrics(...)`：输出 `effective_prompt_tokens`、成本与延时估算

2. 分层路由策略
- `heavy_log_parse` 默认走 `local`（降低 API 成本）
- `memory_cleanup` 默认走 `secondary`
- `high/critical` 风险优先 `primary`（预算不足自动降级）
- 低预算自动降级（`secondary/local`）
- 默认兜底 `primary`

3. 三段缓存策略
- Block1（静态头部）: `ephemeral` + TTL 缓存
- Block2（长期摘要）: `ephemeral` + TTL 缓存
- Block3（动态窗口）: `none`（禁止缓存）
- Block3 超过软阈值时触发主模型门禁：
  - 若初始命中 `primary`，自动降级为 `secondary` 并给出原因

4. 成本与延迟估算
- 使用 tier 成本因子 + 有效 prompt token 估算 `estimated_cost_units`
- 使用 tier 基线延迟 + token 规模估算 `estimated_latency_ms`
- 缓存命中时有效 token 降低，成本/延迟指标同步下降

5. 对外导出
- 更新 `autonomous/__init__.py`（archived） 暴露 Gateway 类型，便于后续 WS19-004/WS19-008 接入。

## 测试覆盖
- 新增 `tests/test_llm_gateway_prompt_slice_ws28_002.py`
  - 路由策略覆盖（主/次/本地）
  - 三段缓存策略字段覆盖（Block1/2/3）
  - Block3 软阈值门禁触发（primary -> secondary）
  - 缓存命中后有效 token 与延迟下降
  - 本地 tier 成本估算为 0

## 验证命令
- `.\.venv\Scripts\python.exe -m ruff check agents/llm_gateway.py tests/test_llm_gateway_prompt_slice_ws28_002.py autonomous/__init__.py`（归档路径，仅用于历史追溯）
  - 结果: `All checks passed!`
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_llm_gateway_prompt_slice_ws28_002.py tests/test_router_engine_prompt_profile_ws28_001.py`
  - 结果: `passed`
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_agentserver_deprecation_guard_ws16_002.py tests/test_native_executor_guards.py tests/test_policy_firewall.py tests/test_global_mutex.py tests/test_process_lineage.py tests/test_native_tools_runtime_hardening.py tests/test_agentic_loop_contract_and_mutex.py tests/test_dna_change_audit_ws18_007.py tests/test_immutable_dna_ws18_006.py tests/test_loop_cost_guard_ws18_005.py tests/test_watchdog_daemon_ws18_004.py tests/test_router_engine_prompt_profile_ws28_001.py tests/test_core_event_bus_consumers_ws28_029.py tests/test_llm_gateway_prompt_slice_ws28_002.py`
  - 结果: `84 passed, 0 failed`

## 交付结果与验收对应
- deliverables“主/次/本地模型分流 + 三段缓存策略”：已通过 `route + prompt_envelope + cache_outcome` 落地。
- acceptance“成本与延迟指标达预期”：已提供 `metrics` 并在缓存命中与 tier 变化下验证下降趋势。
- rollback“单模型回退开关”：可通过固定传入 `model_map.primary=secondary=local` 等效退回单模型策略。

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `agents/llm_gateway.py; tests/test_llm_gateway_prompt_slice_ws28_002.py; autonomous/__init__.py [archived]; doc/task/implementation/NGA-WS19-003-implementation.md`
- `notes`:
  - `llm gateway now supports primary-secondary-local tier routing, block1/block2 ephemeral cache with block3 uncached policy, soft-limit guardrail, and cost-latency estimation for plan comparison`

## Date
2026-02-24
