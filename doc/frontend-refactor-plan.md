# Embla_core 全新 Web 前端重构方案（运行态势数据面板优先）

文档状态：设计基线（可执行版）  
创建时间：2026-02-25  
最后更新：2026-02-25  
适用仓库：`Embla_System`

---

## 1. 目标重定义

`Embla_core` 不是个人助手聊天产品，而是自治代理系统的数据面板（Data Plane Console）。

核心定位：

1. 首页主视角必须是运行态势，不是发布倒计时。
2. 聊天只是一条人机沟通通道（`ChatOps`），不是系统主入口。
3. 发布域只保留为“合规与证据”次级模块，不占主资源位。
4. 一切关键状态必须可追溯到现有 API 或 `scratch/reports/*` 实际产物。

---

## 2. 现状问题（为什么要改）

前一版方案虽然已经从“聊天优先”转向“运维优先”，但仍存在偏差：

1. 信息架构仍把 `Release` 放在前排，和长期运营场景不匹配。
2. `MCP`、`Memory Graph`、`Workflow/Event` 信号未被定义为一等域。
3. 运行时稳定性指标（lease/fail-open/queue/lock/disk）没有形成完整看板语义。
4. 缺少“卡片字段 -> API/报告来源”的强映射，实施时容易失真。

结论：

- 新版必须明确“运行态势 > 工具织网 > 记忆图谱 > 事件流程 > 合规证据 > 聊天”。

---

## 3. 产品原则（强约束）

1. `Runtime-First`：运行态势始终是首屏。
2. `Fabric-Visible`：MCP 服务注册、可用性、来源（builtin/mcporter）必须可观测。
3. `Memory-Operational`：记忆系统不仅展示“有无”，还要展示规模、活跃任务、查询能力。
4. `Evidence-Traceable`：每个告警、红灯和结论都能链接到来源路径。
5. `Read-Only by Default`：默认只读；变更动作（如 cutover）必须显式确认。
6. `Composable`：新前端独立在 `Embla_core/`，不改旧 `frontend/`。

---

## 4. 信息架构（IA）

`Embla_core` 一级导航：

1. `Runtime Posture`（默认首页）
2. `MCP Fabric`
3. `Memory Graph`
4. `Workflow & Events`
5. `Incidents`
6. `Evidence`（次级：含发布合规）
7. `ChatOps`（次级）

页面优先级：

- P0：`Runtime Posture`、`MCP Fabric`、`Memory Graph`、`Workflow & Events`
- P1：`Incidents`、`Evidence`
- P2：`ChatOps`

说明：

- 不再单独设置“发布倒计时首页”。
- 发布相关视图仅在 `Evidence` 中作为“阶段性验收证据”出现。

---

## 5. 数据域与指标域（按仓库真实能力）

### 5.1 运行稳态域（Runtime Stability）

核心指标：

1. `runtime_rollout.value`（SubAgent 命中率）
2. `runtime_fail_open.value`、`budget_exhausted`、`fail_open_blocked_ratio`
3. `runtime_lease.state`、`fencing_epoch`、`lease_lost_churn_ratio`
4. `queue_depth.value`、`oldest_pending_age_seconds`
5. `lock_status.state`、`seconds_to_expiry`
6. `disk_watermark_ratio.value`、`filesystem_free_gb`
7. `error_rate.value`、`latency_p95_ms.value`

来源映射：

1. `scripts/export_slo_snapshot.py`（统一指标采集）
2. `scripts/export_ws26_runtime_snapshot_ws26_002.py`（WS26-002 汇总）
3. `scratch/reports/ws26_runtime_snapshot_ws26_002.json`
4. `logs/autonomous/events.jsonl`
5. `logs/autonomous/workflow.db`
6. `logs/runtime/global_mutex_lease.json`

### 5.2 MCP 工具织网域（MCP Fabric）

核心指标：

1. 注册总数、内置服务数、外部配置服务数
2. `isolated_worker_services`、`rejected_plugin_manifests`
3. 服务可用性矩阵（`available`）
4. 任务快照分布（`registered/configured`）

来源映射：

1. `GET /mcp/status`
2. `GET /mcp/services`
3. `GET /mcp/tasks`
4. `mcpserver/mcp_registry.py`（状态语义：registered/isolated/rejected）

### 5.3 记忆图谱域（Memory Graph / Memory Ops）

核心指标：

1. `memory_stats.total_quintuples`
2. `memory_stats.active_tasks`
3. `memory_stats.task_manager.*`
4. 五元组查询命中数与关键词热点
5. 最近实体关系图（subject-predicate-object）

来源映射：

1. `GET /memory/stats`
2. `GET /memory/quintuples`
3. `GET /memory/quintuples/search`
4. `summer_memory/memory_manager.py`

### 5.4 工作流与事件域（Workflow & Events）

核心指标：

1. Outbox 积压（pending 数、最老待处理时长）
2. 关键事件计数（active: `LeaseLost`; archived_legacy: `SubAgentRuntimeFailOpen`、`SubAgentRuntimeFailOpenBlocked`）
3. 日志上下文统计（会话负载）
4. 当前工具执行态（`tool_status`）

来源映射：

1. `scripts/export_slo_snapshot.py`（queue、error/latency 等）
2. `GET /logs/context/statistics`
3. `GET /logs/context/load`
4. `GET /tool_status`
5. `logs/autonomous/events.jsonl`（通过聚合接口读取）

### 5.5 事件演练域（Incidents / Drill）

核心指标：

1. OOB 演练通过率
2. 最近失败 drill 的 case 与失败原因
3. 修复路径可用性（snapshot recovery / force legacy fallback）

来源映射：

1. `scratch/reports/ws27_oob_repair_drill_ws27_003.json`
2. `scratch/reports/ws26_m11_runtime_chaos_ws26_006.json`
3. `scratch/reports/ws27_subagent_cutover_status_ws27_002.json`

### 5.6 合规证据域（Evidence / Compliance，次级）

说明：

- 该域用于阶段性交付复核，不再占首页主位。

核心指标：

1. 全链结果（M0-M12）
2. 文档一致性结果（WS27-005）
3. 签署链结果（WS27-006）
4. 72h wall-clock 验收状态（WS27-001）

来源映射：

1. `scratch/reports/release_closure_chain_full_m0_m12_result.json`
2. `scratch/reports/ws27_m12_doc_consistency_ws27_005.json`
3. `scratch/reports/release_phase3_full_signoff_chain_ws27_006_result.json`
4. `scratch/reports/phase3_full_release_report_ws27_006.json`
5. `scratch/reports/ws27_72h_wallclock_acceptance_ws27_001.json`

---

## 6. BFF 聚合接口契约（`/v1/ops/*`）

约束：

1. 前端不直接扫描文件系统。
2. 前端只消费后端聚合接口。
3. 每个返回对象必须带 `source_reports` 或 `source_endpoints`。

建议新增接口：

1. `GET /v1/ops/runtime/posture`
- 聚合 `runtime_rollout`、`runtime_fail_open`、`runtime_lease`、`queue_depth`、`lock_status`、`disk_watermark_ratio`、`error_rate`、`latency_p95_ms`。

2. `GET /v1/ops/mcp/fabric`
- 聚合 `/mcp/status` + `/mcp/services` + `/mcp/tasks`，输出 builtin/mcporter/isolated/rejected 视图。

3. `GET /v1/ops/memory/graph`
- 聚合 `/memory/stats` 与 `/memory/quintuples`，输出统计、热点实体、关系采样。

4. `GET /v1/ops/workflow/events`
- 聚合 outbox 队列、关键事件计数、日志上下文统计、工具状态。

5. `GET /v1/ops/incidents/latest`
- 聚合 OOB/chaos/cutover 相关报告，输出最近风险和修复建议链接。

6. `GET /v1/ops/evidence/index`
- 聚合 release/doc/signoff/wallclock 报告目录，用于验收复核。

统一返回字段：

1. `status`
2. `generated_at`
3. `data`
4. `severity`
5. `source_reports`
6. `source_endpoints`
7. `reason_code` / `reason_text`（失败或降级必填）

---

## 7. 卡片到数据源映射（实施检查表）

1. Runtime Hero 卡片 -> `/v1/ops/runtime/posture` -> `ws26_runtime_snapshot_ws26_002 + export_slo_snapshot`
2. MCP Availability Matrix -> `/v1/ops/mcp/fabric` -> `/mcp/status + /mcp/services + /mcp/tasks`
3. Memory Graph & Stats -> `/v1/ops/memory/graph` -> `/memory/stats + /memory/quintuples`
4. Queue & Event Timeline -> `/v1/ops/workflow/events` -> `workflow.db + events.jsonl + /logs/context/*`
5. Incident Radar -> `/v1/ops/incidents/latest` -> `ws27_oob_repair_drill_ws27_003 + ws26_m11_runtime_chaos_ws26_006`
6. Compliance Drawer -> `/v1/ops/evidence/index` -> `release/doc/signoff/wallclock` 报告

---

## 8. 工程边界（已确认）

### 8.1 新前端目录

- 固定目录名：`Embla_core/`
- 与旧 `frontend/` 并行维护，互不影响。

### 8.2 技术栈

- 固定为：`Next.js + TypeScript + Tailwind CSS + Lucide React`
- 路由：`App Router`
- 数据层：BFF 接口 + 可选 React Query 缓存

### 8.3 设计系统

- 设计语言：`Zen-iOS Hybrid`
- 强约束规范：`doc/embla-core-ui-design-spec.md`

---

## 9. `Embla_core` 建议目录结构

```text
Embla_core/
  app/
    (dashboard)/
      runtime-posture/page.tsx
      mcp-fabric/page.tsx
      memory-graph/page.tsx
      workflow-events/page.tsx
      incidents/page.tsx
      evidence/page.tsx
      chatops/page.tsx
    layout.tsx
    page.tsx
  components/
    layout/
    cards/
    charts/
    tables/
    graphs/
  lib/
    api/
      ops.ts
      mcp.ts
      memory.ts
    types/
      runtime.ts
      mcp.ts
      memory.ts
      workflow.ts
      incidents.ts
      evidence.ts
    format/
  styles/
    globals.css
    tokens.css
  public/
  package.json
```

---

## 10. 页面设计草图（运行态势优先）

### 10.1 `Runtime Posture`（默认首页）

1. 顶部 6 卡：rollout、fail-open、lease、queue、lock、disk。
2. 中部：错误率/延迟趋势 + 关键事件时间线。
3. 底部：当前风险清单（可跳转 `Incidents`）。

### 10.2 `MCP Fabric`

1. 服务来源分层（builtin / mcporter / isolated / rejected）。
2. 可用性矩阵（online/offline/degraded）。
3. 服务详情抽屉（manifest、工具能力、命令摘要）。

### 10.3 `Memory Graph`

1. 记忆统计头部（quintuples/active_tasks/task backlog）。
2. 关系图谱画布（实体与关系边）。
3. 关键词检索与 drill-down（调用 `/memory/quintuples/search`）。

### 10.4 `Workflow & Events`

1. Outbox 积压监控（数量与最老等待时长）。
2. 高危事件泳道（fail-open、lease-lost、auto-degraded）。
3. 会话上下文加载统计与工具执行状态。

### 10.5 `Incidents`

1. OOB 演练最近结果与 case 细节。
2. runtime chaos 历史与失败归因。
3. 修复 runbook 快速入口。

### 10.6 `Evidence`（次级）

1. 统一证据索引（path、timestamp、pass/fail、摘要）。
2. 发布/文档/签署/wallclock 报告只在本页展示。
3. 支持任务域筛选（WS27-001~006、M0-M12）。

### 10.7 `ChatOps`（次级）

1. 标注“沟通通道，非主态势页”。
2. 保留任务触发与流式事件，不抢首页资源位。

---

## 11. 项目内可直接追加的增强建议（深度对齐）

1. `Fail-Open Budget Burn` 进度条：直接消费 `runtime_fail_open.budget_remaining_ratio`，用于提前预警。
2. `Lease/Fencing Guard` 面板：显示 `fencing_epoch` 与 `seconds_to_expiry`，避免并发误判。
3. `MCP 信任边界` 看板：单独展示 `rejected_plugin_manifests` 与 `isolated_worker_services`。
4. `Memory 提取背压` 指标：基于 `active_tasks + task_manager` 做负载提示。
5. `Outbox 冻结检测`：当 `pending` 与 `oldest_pending_age_seconds` 同时超阈值时提升为 critical。
6. `运行降级原因瀑布`：聚合 `decision_reasons` 与 `gate_failure_counts`，用于回溯。

---

## 12. 里程碑（文档到交付）

### Phase A（当前）

1. 文档改版定稿（运行态势优先）。
2. UI 规范补充信息层级约束。
3. 明确卡片与数据源映射表。

### Phase B（MVP）

1. 后端：实现 `/v1/ops/runtime/posture`、`/v1/ops/mcp/fabric`、`/v1/ops/memory/graph`、`/v1/ops/workflow/events`。
2. 前端：完成 `Runtime Posture + MCP Fabric + Memory Graph + Workflow & Events`。
3. 打通风险高亮与来源追溯。

### Phase C（增强）

1. 增加 `Incidents + Evidence + ChatOps`。
2. 增加跨域筛选、对比与导出。
3. 增加角色权限（viewer/operator/approver）。

---

## 13. 验收标准（DoD）

1. 进入首页 5 秒内看到运行稳态 6 个核心信号。
2. 首页不出现发布倒计时主卡。
3. 任一红色告警可追溯到 API 或报告路径。
4. MCP 与 Memory 两个域都能在无聊天场景下独立提供价值。
5. 新前端独立运行且不依赖旧 `frontend/`。

---

## 14. 风险与对策

1. 风险：多源数据字段不一致。  
对策：BFF 做 schema 归一化与版本标记。

2. 风险：事件/报告更新频率不一致导致状态跳变。  
对策：按域设置缓存（3-10 秒）并标注 `generated_at`。

3. 风险：实施中再次滑向“聊天优先”。  
对策：导航顺序固定，首页仅允许运行态势模块。

4. 风险：视觉效果影响可读性。  
对策：严格遵循 `Zen-iOS Hybrid` 对比和层级规则，优先可读性。
