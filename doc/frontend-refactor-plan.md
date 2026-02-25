# 全新 Web 前端重构方案（自治代理数据面板优先）

文档状态：设计基线（可执行版）  
创建时间：2026-02-25  
最后更新：2026-02-25  
适用仓库：`Embla_System`

---

## 1. 目标重定义

本项目的新前端不再以“个人 AI 助手聊天 UI”为中心，而是以“自治代理运行与发布态势”作为第一视角。

核心定位：

1. 这是一个 **Autonomous Agent Operations Console**。
2. 聊天仅是“人类与代理沟通渠道之一”（`ChatOps`），不是主入口。
3. 主入口是多维数据看板：发布门禁、运行稳态、风险、回滚、证据链。

---

## 2. 现状问题（为什么原草案不适配）

当前旧草案的主要偏差：

1. 页面结构偏“对话产品”，对发布与稳定性治理支持不足。
2. 指标体系偏用户体验，缺少 `M0-M12` 收口链与 `WS27` 验收证据链。
3. 没有把 `scratch/reports/*` 的既有产物体系作为一等数据源。
4. 没有明确“前端仅消费 BFF 聚合接口”的边界策略。

结论：

- 旧草案可作为视觉参考，不可作为本项目执行方案。

---

## 3. 产品原则（必须满足）

1. **Ops-First**：发布态势与运行健康优先于聊天。
2. **Evidence-First**：所有关键状态必须可追溯到报告路径或事件证据。
3. **Guardrail-First**：展示门禁状态、失败原因、回滚路径，不只展示“成功”。
4. **Composable**：新前端独立目录开发，不改旧 `frontend/`；可并行迭代。
5. **Read-Only by Default**：默认只读看板；高风险操作需显式二次确认。

---

## 4. 信息架构（IA）

新前端一级导航：

1. `Overview`：发布总览（默认首页）
2. `Release Gates`：门禁链明细（M0-M12 + WS27）
3. `Runtime`：运行稳态（预算、租约、fail-open、cutover）
4. `Incidents`：风险与演练（OOB、drill、repair）
5. `ChatOps`：对话与任务触发（次级入口）
6. `Evidence`：报告与签署产物索引

页面优先级：

- P0：`Overview`、`Release Gates`、`Runtime`
- P1：`Incidents`、`Evidence`
- P2：`ChatOps` 深化

---

## 5. 数据域与指标域

### 5.1 发布域（Release Domain）

主要指标：

1. `full_chain_passed`（M0-M12 全链）
2. `doc_consistency_passed`（WS27-005）
3. `signoff_passed`（WS27-006）
4. `wallclock_acceptance_passed`（WS27-001 真实72h）
5. `failed_groups/failed_steps`（失败分组和步骤）

关键数据源（现有产物）：

1. `scratch/reports/release_closure_chain_full_m0_m12_result.json`
2. `scratch/reports/ws27_m12_doc_consistency_ws27_005.json`
3. `scratch/reports/phase3_full_release_report_ws27_006.json`
4. `scratch/reports/release_phase3_full_signoff_chain_ws27_006_result.json`
5. `scratch/reports/ws27_72h_wallclock_acceptance_ws27_001.json`
6. `scratch/reports/ws27_72h_wallclock_acceptance_ws27_001_state.json`

### 5.2 运行域（Runtime Domain）

主要指标：

1. `subagent_runtime.enabled`
2. `rollout_percent`
3. `fail_open_budget_ratio` 与预算耗尽状态
4. `lease_status`
5. `runtime_snapshot_ready`

关键数据源：

1. `scratch/reports/ws26_runtime_snapshot_ws26_002.json`
2. `scratch/reports/ws27_subagent_cutover_status_ws27_002.json`
3. `scratch/reports/ws27_subagent_cutover_apply_ws27_002.json`
4. `scratch/reports/ws27_subagent_cutover_rollback_snapshot_ws27_002.json`

### 5.3 事件与演练域（Incident/Drill Domain）

主要指标：

1. `oob_drill_passed`
2. drill 场景覆盖数
3. 最新失败演练的错误摘要

关键数据源：

1. `scratch/reports/ws27_oob_repair_drill_ws27_003.json`
2. `scratch/reports/ws26_m11_runtime_chaos_ws26_006.json`

---

## 6. 后端接口契约草案（BFF 聚合）

说明：

- 新前端不直接扫描文件系统。
- 通过 `apiserver` 提供只读聚合接口。
- 旧接口保留，新接口加在 `/v1/ops/*` 名下。

建议新增：

1. `GET /v1/ops/overview`
- 返回总览卡片数据：全链状态、门禁数量、当前风险等级、72h 验收倒计时。

2. `GET /v1/ops/release/gates`
- 返回 WS27-004/005/006 聚合状态、失败项、产物路径。

3. `GET /v1/ops/runtime/status`
- 返回 WS26/WS27 运行时关键指标（rollout/fail-open/lease）。

4. `GET /v1/ops/incidents/latest`
- 返回最新 OOB/chaos 演练结论和失败摘要。

5. `GET /v1/ops/evidence/index`
- 返回可签署报告清单（路径、时间、pass/fail、摘要）。

6. `GET /v1/ops/wallclock/status`
- 返回 72h 状态（`started_at`、`elapsed_hours`、`remaining_hours`、`target_reached`）。

契约约束：

1. 所有接口返回统一字段：`status`、`generated_at`、`data`。
2. 每个状态对象必须携带 `source_reports`（可追溯路径列表）。
3. 所有失败项必须有 `reason_code` 与 `reason_text`。

---

## 7. 新前端工程边界

### 7.1 目录策略

- 新建独立目录：`frontend_ops/`（或 `web_console/`，待最终命名确认）。
- 不改旧目录：`frontend/` 保持现状。

### 7.2 技术建议（可落地优先）

优先建议：

1. `Vue 3 + Vite + TypeScript`（与现仓库技术栈一致，迁移成本低）。
2. 采用轻量图表库（如 ECharts）用于趋势和门禁状态。
3. 设计系统偏“控制台风格”：高信息密度、低装饰噪声。

可选方案：

- React 技术栈可行，但会增加一套独立心智和工程维护成本。

### 7.3 视觉方向（针对本项目）

1. 深浅双主题可切换，但默认浅色运维台（便于截图和评审）。
2. 色彩语义固定：
- 通过：绿色
- 警告：橙色
- 失败：红色
- 未知：灰色
3. 组件风格偏“指挥台”：卡片 + 表格 + 时间线 + 状态芯片。

---

## 8. 页面设计草图（功能视角）

### 8.1 `Overview`（默认首页）

核心模块：

1. 顶部 KPI 行：
- 全链状态
- 文档一致性状态
- 放行状态
- 72h 倒计时

2. 中部双栏：
- 左：门禁链时间线（M0-M12）
- 右：当前高风险项 Top N

3. 底部：
- 最新报告清单（可跳 Evidence）

### 8.2 `Release Gates`

1. 按 `WS27-004/005/006` 分区显示。
2. 每区展示：
- `passed`
- 失败项列表
- 关键 checks
- 产物路径
- 最近更新时间

3. 支持一键复制复核命令（只读，不执行）。

### 8.3 `Runtime`

1. `subagent_runtime` 配置快照。
2. `rollout/fail-open/lease` 状态卡。
3. cutover 与 rollback 快照对比。

### 8.4 `Incidents`

1. OOB 演练历史。
2. 失败 drill 详情和修复建议链接。
3. 近 24h 风险热区（由报告摘要构建）。

### 8.5 `ChatOps`

1. 保留聊天与流式事件渲染。
2. 显式标注“沟通通道”，避免误导为系统主界面。

---

## 9. 里程碑（文档到交付）

### Phase A（本轮，文档定稿）

1. 定稿本方案（本文件）。
2. 定稿 BFF 接口契约草案。
3. 定稿新前端目录边界。

### Phase B（MVP 开发）

1. 后端：补 `/v1/ops/*` 聚合只读接口。
2. 前端：完成 `Overview + Release Gates + Runtime` 三页。
3. 打通真实报告渲染。

### Phase C（增强）

1. 加 `Incidents + Evidence + ChatOps`。
2. 增加筛选、对比、导出能力。
3. 增加权限模型（只读/操作员/审批人）。

---

## 10. 验收标准（DoD）

1. 进入首页 5 秒内可看到 M0-M12 当前结论。
2. 任一红色状态可追溯到具体报告路径与失败字段。
3. 可直接看到 72h 墙钟验收剩余时间与达标状态。
4. 不依赖旧 `frontend/` 代码与打包链。
5. 旧前端不被改动即可并行运行。

---

## 11. 风险与对策

1. 风险：报告 JSON 字段不稳定。
- 对策：BFF 做 schema 归一化层。

2. 风险：接口多源拼装导致延迟。
- 对策：聚合接口按域拆分 + 缓存（3~10 秒）。

3. 风险：前端再次回到“聊天优先”。
- 对策：导航顺序固定为 `Overview` 首位，`ChatOps` 后置。

---

## 12. 待确认项（需你拍板）

1. 新前端目录名：`frontend_ops/` 还是 `web_console/`。
2. 技术栈：沿用 Vue 还是改 React（推荐沿用 Vue）。
3. 第一批必须上线的页面：建议 `Overview + Release Gates + Runtime`。

