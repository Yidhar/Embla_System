# NagaAgent 全仓文档审计任务（Read-only）

你是资深技术写作者+代码审计员。请在 **只读** 模式下，对当前仓库（NagaAgent）做一次“全代码文档检查/文档健康度审计”，并输出 **Markdown 报告**。

## 审计范围
- 顶层：README.md、README_en.md、AGENTS.md、build.md、LICENSE、config.json.example
- doc/ 下所有文档
- runbooks/ 下运维文档
- 各子模块 README：agentserver/README.md、apiserver/README.md、Embla_core/README.md、system/README.md、logs/**/README.md、summer_memory/readme.md 等
- 代码内文档：Python/TS 关键入口与公共 API 的 docstring、注释、类型信息

## 重点关注
1) **入口可理解性**：新用户从 README 能否跑起来（环境、安装、启动、常见问题）。
2) **一致性**：
   - 各处端口/服务名/目录名是否一致（api_server/agentserver/mcpserver/memory_server 等）
   - MCP 服务名与工具名是否一致（codex-cli/codex-mcp、ask-codex、ping 等）
   - 文档与当前分支行为是否一致（例如 AgentServer 启停策略、自治 SDLC 约束）。
3) **可操作性**：命令是否能直接复制运行；Windows 兼容性；脚本路径是否正确。
4) **断链与过期**：相对链接、图片路径、脚本文件、文档标题引用。
5) **代码内 API 文档**：
   - FastAPI endpoint 的 docstring/注释是否能生成清晰的 OpenAPI 说明
   - 关键模块（apiserver/agentic_tool_loop.py, apiserver/api_server.py, system/config.py, mcpserver/mcp_manager.py, autonomous/*）对外行为是否有对应文档
6) **重复/冲突**：多处同一概念的描述冲突，或重复文档应合并/建立索引。
7) **国际化**：README_en.md 覆盖度与 README.md 是否一致；缺失项标注。

## 输出格式（Markdown）
- 摘要（总体评分/风险等级）
- 发现列表（按严重程度分：Critical / Major / Minor / Nice-to-have）
  - 每条包含：位置（文件路径+行号范围如可得）、问题、影响、建议修复方式
- 文档结构建议（建议新增/合并哪些文档，给出目录树草案）
- “最小可运行路径”建议（给出 5~10 步的最短跑通流程）
- 待补充信息清单（需要作者确认的点）

要求：
- 仅输出报告内容，不要执行写入修改；不要生成补丁。
- 尽量引用具体文件路径与具体段落（能定位就定位）。
