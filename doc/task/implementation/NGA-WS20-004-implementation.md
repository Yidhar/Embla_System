> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS20-004 实施记录（MCP 状态展示与真实后端对齐）

## 任务信息
- Task ID: `NGA-WS20-004`
- Title: MCP 状态展示与真实后端对齐
- 状态: 已完成（进入 review）

## 本次范围（仅 WS20-004）
1. 前端 MCP 状态来源切换到真实运行态接口
- `frontend/src/views/SkillView.vue`
  - `loadMcpServices` 改为并行拉取：
    - `GET /mcp/services`
    - `GET /mcp/status`
    - `GET /mcp/tasks`
  - 新增运行态总览卡（online/offline、total/active/completed/failed、timestamp）。
  - 每个服务显示运行态标签（`registered/configured/unavailable/...`）而非只看 `available`。
  - 新增“状态漂移”标记（`available` 与运行态是否在线不一致）。
  - 新增“刷新状态”按钮，支持手动拉取最新快照。

2. API 类型契约与后端快照对齐
- `frontend/src/api/core.ts`
  - 新增并导出：
    - `McpRuntimeSnapshot`
    - `McpTaskSnapshot`
    - `McpTaskListResponse`
  - `getMcpStatus/getMcpTasks` 返回类型改为上述结构化类型。

3. 前端错误处理收敛（顺手修复 lint 阻塞）
- `frontend/src/views/SkillView.vue`
  - 去除 `alert(...)` 分支，改为页面内错误提示：
    - `mcpImportError`
    - `skillImportError`

## 验证命令
- `cd frontend; npx eslint src/views/SkillView.vue src/api/core.ts src/utils/encoding.ts`
  - 结果: `passed`
- `cd frontend; npx vue-tsc --noEmit`
  - 结果: `passed`
- `cd frontend; npm run build`
  - 结果: 失败（环境权限问题，`plugin externalize-deps` 报 `spawn EPERM`），非业务逻辑类型错误。

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `frontend/src/views/SkillView.vue; frontend/src/api/core.ts; doc/task/implementation/NGA-WS20-004-implementation.md`
- `notes`:
  - `mcp ui now reads runtime snapshot/tasks/services jointly, shows online summary and per-service runtime status, and marks availability/runtime drift to align frontend display with backend state semantics`

## Date
2026-02-24
