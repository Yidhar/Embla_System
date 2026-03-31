> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS16-003 实施记录（MCP 状态占位接口收敛）

## 任务信息
- 任务ID: `NGA-WS16-003`
- 标题: MCP 状态占位接口收敛
- 状态: 已完成（进入 review）

## 变更范围
- `apiserver/api_server.py`
- `tests/test_mcp_status_snapshot.py`（新增）

## 实施内容
1. `/mcp/status` 从硬编码离线响应改为运行态快照
- 新增 `_build_mcp_runtime_snapshot()`：
  - 自动读取 `mcp_registry`（内置服务）
  - 读取 `~/.mcporter/config.json`（外部服务）
  - 合并生成统一状态：
    - `server` (`online/offline`)
    - `tasks`（兼容前端的 `total/active/completed/failed`）
    - `registry`（内置/外部服务明细）
    - `scheduler`（快照来源与统计）

2. `/mcp/tasks` 从空列表改为服务级任务投影
- 新增 `_build_mcp_task_snapshot(status)`：
  - 内置服务投影为 `registered`
  - 外部服务投影为 `configured`
  - 支持按 `status` 过滤

## 验证结果
- `tests/test_mcp_status_snapshot.py`
  - 校验内置 + 外部服务聚合计数
  - 校验 `/mcp/tasks` 的状态过滤逻辑

## 结论
- 前端调用 `/mcp/status` 与 `/mcp/tasks` 不再只能收到“离线占位”。
- 接口在不依赖独立 MCP 进程的前提下，仍可提供可观测、可追踪的服务状态基线。

