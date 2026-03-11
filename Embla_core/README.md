# Embla Core

面向普通用户的 Embla System 监控前端，聚焦：`Runtime + MCP + Memory + Workflow`。

## 启动

```bash
cd Embla_core
npm install
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000 npm run dev
```

如果后端的 `/v1/ops/mcp/fabric` 或 `/v1/ops/memory/graph` 暂时不可用，前端会自动降级：

- `Memory`：图谱先走 `/v1/ops/memory/graph`，关键词检索先走 `/v1/ops/memory/search`；失败时回退到 `/memory/stats` + `/memory/quintuples` + `/memory/quintuples/search`
- `MCP`：优先走 `/v1/ops/mcp/fabric` live 数据，安装入口写入项目根 `mcp_servers.json`

## 当前已完成页面

- `Runtime Posture`
- `MCP Fabric`
- `Memory Graph`
- `Workflow & Events`
- `Incidents`
- `Evidence`
- `ChatOps`（边界占位）

## 说明

- 当前“记忆召回率”页签展示的是 **召回就绪度**，因为后端尚未直接暴露真实 recall rate。
- 当前“Agent 数量与角色分布”展示的是 **最近观测到的 agent 角色信号**，因为后端尚未直接提供活跃 agent inventory 接口。
