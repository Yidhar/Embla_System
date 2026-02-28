> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS20-003 实施记录（前端模块按域解耦）

## 任务信息
- Task ID: `NGA-WS20-003`
- Title: 前端模块按域解耦
- 状态: 已完成（进入 review）

## 本次范围（仅 WS20-003）
1. 新增按域路由边界（chat/tools/settings/ops）
- 新增 `frontend/src/domains/chat/routes.ts`
- 新增 `frontend/src/domains/tools/routes.ts`
- 新增 `frontend/src/domains/settings/routes.ts`
- 新增 `frontend/src/domains/ops/routes.ts`
- 新增 `frontend/src/router/routes.ts` 作为统一聚合入口
- `frontend/src/main.ts` 从内联路由切换为 `appRoutes`

2. 抽取 chat 域能力，消除视图间耦合
- 新增 `frontend/src/domains/chat/chatStream.ts`
- 新增 `frontend/src/domains/chat/sessionApi.ts`
- 新增 `frontend/src/domains/chat/index.ts`
- `frontend/src/views/FloatingView.vue` 不再从 `MessageView.vue` 导入 `chatStream`
- `frontend/src/views/MessageView.vue` 与 `frontend/src/views/FloatingView.vue` 不再直接依赖 `@/api/core`

3. 新增边界回归测试
- 新增 `tests/test_frontend_domain_boundaries_ws20_003.py`
- 覆盖：
  - 四个域路由模块存在且覆盖预期 path
  - 主路由改为聚合入口
  - 关键 chat 视图移除 cross-view 依赖和 core API 直连
  - 视图层禁止 `@/views/*` 互相导入

## 验证命令
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_frontend_domain_boundaries_ws20_003.py`
- `cd frontend; npm run build`

## 交付结果与验收对应
- deliverables“chat/tools/settings/ops 模块边界拆分”：已通过域路由模块 + chat 域 facade 落地。
- acceptance“模块依赖关系清晰且可独立测试”：新增自动化边界测试并通过。
- rollback“分支级回退”：本次仅做结构化导出与依赖替换，支持任务粒度回滚。

## Date
2026-02-24
