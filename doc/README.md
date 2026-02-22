# NagaAgent 文档归档索引

本目录用于统一归档项目模块文档与工程评估文档，目标是让后续维护、重构和协作都有统一入口。

## 文档列表

1. `doc/01-module-overview.md`
   - 项目总体架构、运行时调用链、端口与打包关系。
2. `doc/02-module-archive.md`
   - 按模块归档职责、关键文件、输入输出、依赖与风险点。
3. `doc/03-qt-migration-assessment.md`
   - 使用 C++/Qt UI 框架改造本项目的可行性评估、成本估算和分阶段路线。
4. `doc/04-api-protocol-proxy-guide.md`
   - 模型 API 协议路由、Google 原生接口（`generateContent`/`streamGenerateContent`/`BidiGenerateContent`）与系统代理策略说明。
5. `doc/05-dev-startup-and-index.md`
   - `frontend` `npm run dev` 启动流程、模块目录索引、排障清单。
6. `doc/06-structured-tool-calls-and-local-first-native.md`
   - 结构化 `tool_calls` 主链路说明（LLM -> Loop）、Local-first（AgentServer -> Native）拦截策略，以及 `cwd/pwd -> get_cwd` 修复记录。
7. `doc/07-autonomous-agent-sdlc-architecture.md`
   - 无人值守自治迭代架构文档（借鉴多 Agent 框架思想但不依赖其库），包含状态机、时序图、记忆治理与自动发布回滚策略。
8. `doc/09-工具调用与任务执行规范.md`
   - 工具调用与任务执行规范：Codex 主链路下发、Native 审阅验证、失败降级与回执模板。

## 使用建议

1. 新成员先读 `01`，理解全局拓扑和服务边界。
2. 日常开发或排障时查 `02`，快速定位模块入口。
3. 模型连通性或代理问题优先读 `04`，按“配置 -> 日志 -> URL”顺序排查。
4. 做技术路线决策时读 `03`，优先参考分阶段实施方案。
5. 需要执行任务发布/审阅闭环时优先读 `09`。

## Additional Runbook
- `doc/05-dev-startup-and-index.md`: `frontend` `npm run dev` startup flow, module directory index, and troubleshooting checklist.

