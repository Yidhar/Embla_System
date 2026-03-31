# WS30 — Multi-Agent 协作系统状态刷新

文档状态：执行对齐（Status Refresh）  
最后更新：2026-03-10  
适用范围：`WS30` 多代理执行面基础设施 + `WS31` BoxLite-first 自维护执行沙箱并轨结果。

> 说明  
> 本文已从“原始任务拆解清单”收敛为“当前实现状态刷新”。原始 TODO、WS 粗估与阶段性拆卡不再作为当前执行依据；涉及运行时与验收时，统一以本文列出的 canonical 文档、代码锚点与测试证据为准。

---

## 1. Canonical 口径

发生冲突时，优先使用以下文档：

1. `doc/01-module-overview.md`：当前模块主链、`execution_receipt` 与最终收口口径。
2. `doc/09-tool-execution-specification.md`：父/子工具协议、Review 生命周期、worktree 提交流程与清理事实。
3. `doc/14-multi-agent-architecture.md`：多代理角色分工与 Dev 自检 / Review 闭环。
4. `doc/15-boxlite-first-execution-sandbox-architecture.md`：`host worktree + box execution + host audit/promote/teardown` 的自维护执行沙箱设计。
5. `doc/Multi Agent Target Architecturev2.1.md`：目标态蓝图；仅用于目标定义，不直接等价当前默认运行链。

---

## 2. 判定语义（沿用 `doc/task/25-*`）

- `TARGET_DONE`：该能力已经达到当前目标态定义，可作为 canonical 能力使用。
- `BRIDGE_DONE`：能力已工程化落地并具备测试/门禁证据，但仍属于桥接态或局部收口态。
- `TARGET_PENDING`：目标态仍未闭合，当前只有局部实现、过渡方案或待补齐项。

---

## 3. 当前状态矩阵（2026-03-10）

| 能力项 | 当前实现 | 状态 | 代码锚点 | 测试证据 |
|---|---|---|---|---|
| 1.1 Agent 生命周期运行时 | `AgentSession` / `AgentSessionStore` 已具备会话创建、挂起/恢复、消息持久化、metadata 持久化与销毁；`destroy()` 已返回事实型 cleanup report，并可释放 BoxLite / worktree 资源。 | `TARGET_DONE` | `agents/runtime/agent_session.py`、`agents/runtime/parent_tools.py` | `tests/test_agent_runtime_session_ws30_002.py` |
| 1.2 Agent Mailbox | `AgentMailbox` 已具备 inbox topic 语义、SQLite 持久化、顺序读取与 parent/child 消息通道。 | `TARGET_DONE` | `agents/runtime/mailbox.py` | `tests/test_agent_runtime_session_ws30_002.py` |
| 1.3 TaskBoard 引擎 | `TaskBoardEngine` 已落地 `MD + SQLite` 双层同步、任务状态查询与 Expert 协作面。 | `TARGET_DONE` | `agents/runtime/task_board.py` | `tests/test_task_board_engine_ws30_003.py` |
| 1.4 迷你 Tool-Loop | `run_mini_loop()` 已支持独立 LLM 会话、child tools、父消息轮询、中断标志、动态工具激活。 | `TARGET_DONE` | `agents/runtime/mini_loop.py` | `tests/test_mini_loop_ws30_004.py` |
| 2.1 Shell Agent | `ShellAgent` 已具备只读工具集、`dispatch_to_core`、`route_semantic(shell_readonly/shell_clarify/core_execution)` 与路由上下文封装；API 侧已消费该语义。 | `BRIDGE_DONE` | `agents/shell_agent.py`、`apiserver/routes_chat.py`、`apiserver/api_server.py` | `tests/test_agent_roles_ws30_005.py`、`tests/test_shell_native_tool_boundary_ws30_007.py` |
| 2.2 Core Agent | `CoreAgent` 已具备分解、Expert 映射、router context 消费、收据聚合与 review gate 收口；但默认入口尚未完全只保留这一条链。 | `BRIDGE_DONE` | `agents/core_agent.py`、`agents/pipeline.py` | `tests/test_agent_roles_ws30_005.py` |
| 2.3 Expert / Dev / Review 角色闭环 | `ExpertAgent`、`DevAgent`、`ReviewAgent` 均已存在；Dev 必须先自检再 `report_to_parent(completed + verification_report)`，Review 必须输出结构化 `review_result(verdict=approve/request_changes/reject)`，并由 Expert 驱动返修 / 重做 / blocked 分支。 | `BRIDGE_DONE` | `agents/expert_agent.py`、`agents/dev_agent.py`、`agents/review_agent.py`、`agents/runtime/child_tools.py`、`agents/pipeline.py` | `tests/test_agent_roles_ws30_005.py`、`tests/test_agent_runtime_session_ws30_002.py` |
| P0 L1 记忆 + 精准编辑工具 | `memory_*` 已形成 canonical 名称集合，覆盖读/写/列举/搜索/打标签/精准 patch/insert/append/replace/deprecate/delete/link；冲突返回语义已补齐。 | `TARGET_DONE` | `agents/memory/l1_memory.py`、`agents/memory/memory_tools.py` | `tests/test_memory_tools_ws30_006.py`、`tests/test_l1_memory.py` |
| P0 动态 Tool Profile（最小注入） | `spawn_child_agent(tool_profile=...)` 已支持 `refactor/new_doc/bugfix/review/cleanup/custom` 预设，并支持 memory task 自动推断，显著缩小子代理注入工具子集。 | `TARGET_DONE` | `agents/runtime/tool_profiles.py`、`agents/runtime/parent_tools.py` | `tests/test_memory_tools_ws30_006.py` |
| 3.1 原子化 Prompt 引擎 | `PromptAssembler` 已具备 DNA 加载、block 组装、checksum 校验、memory hints 注入与 block 枚举。 | `TARGET_DONE` | `agents/prompt_engine.py` | `tests/test_prompt_engine.py` |
| 3.2 L1 → L2 / Tool Topology 分层 | `summer_memory/quintuple_graph.py` 已保留 Shell L2 五元组图谱与向量索引能力；`agents/memory/semantic_graph.py` 明确为工具结果拓扑，不再与 Shell L2 混为同一事实源。 | `BRIDGE_DONE` | `summer_memory/quintuple_graph.py`、`agents/memory/semantic_graph.py` | `tests/test_l2_l3_memory.py` |
| 3.4 Hierarchical RAG | `HierarchicalIndex`、`ast_chunker` 已具备文件摘要 / section index / chunk 按需读取与基础检索；但向量化召回、增量重建触发与专用 `explore_large_file` 接口仍未完全收口到目标态。 | `BRIDGE_DONE` | `agents/memory/hierarchical_rag.py`、`agents/memory/ast_chunker.py` | `tests/test_l2_l3_memory.py` |
| 4.1 Git worktree 沙箱 | owner worktree 已具备创建、审计、promote、teardown、ledger 记录与提交待审批态；提交链语义已稳定。 | `BRIDGE_DONE` | `system/git_worktree_sandbox.py`、`agents/runtime/parent_tools.py` | `tests/test_worktree_sandbox_ws30_008.py`、`tests/test_worktree_submission_ws30_010.py` |
| 4.1/WS31 BoxLite-first 执行后端 | 已形成 `native / boxlite` 双后端路由；BoxLite 使用稳定 `box_name` + 运行时 `box_id`，并在 destroy 时释放执行盒；`query_docs` / `file_ast_*` 已进入 box 内 guest helper 路径；宿主仍是 worktree audit/promote/teardown 的唯一事实源。 | `BRIDGE_DONE` | `system/execution_backend/boxlite_backend.py`、`system/boxlite/manager.py`、`system/sandbox_context.py`、`apiserver/native_tools.py` | `tests/test_sandbox_context_boxlite_ws31_001.py`、`tests/test_boxlite_runtime_spawn_ws31_002.py`、`tests/test_native_tools_backend_router_ws31_003.py`、`tests/test_boxlite_backend_exec_ws31_004.py`、`tests/test_boxlite_manager_teardown_ws31_005.py` |
| 4.2 主链默认切换与遗留入口清理 | 全局默认 `execution_backend` 已切换为 `boxlite`，且默认 `boxlite.mode=required`；缺少 SDK 时会优先通过项目 `.venv` 自动安装 `boxlite`。session runtime 主链统一为 `host control plane + BoxLite execution plane + host worktree lifecycle`。`SandboxContext.default()` 保留 `native` 仅作无 session / 测试 harness fallback。更广泛的 legacy 命名清理继续按仓库级治理推进，但不再阻塞 BoxLite 默认主链。 | `BRIDGE_DONE` | `main.py`、`apiserver/routes_chat.py`、`agents/pipeline.py`、`system/boxlite/manager.py` | `tests/test_main_entrypoint_runtime.py`、`tests/test_chat_route_session_state_snapshot_ws28_011.py`、`tests/test_sandbox_context_boxlite_ws31_001.py`、`tests/test_boxlite_backend_exec_ws31_004.py` |

---

## 4. 已完成的关键口径收敛

1. `Dev completed` 不再是自由文本完成态，必须附带结构化 `verification_report`。
2. `Review completed` 不再是模糊“通过/打回”，必须附带结构化 `review_result`，且 `verdict` 只能是 `approve / request_changes / reject`。
3. `reject` 不再只有单一失败路径；当前已有：`request_changes -> resume 原 Dev`、`reject -> respawn fresh Dev`、不可恢复时 `expert_blocked` 上报三类收口分支。
4. `destroy_child_agent` 的资源释放事实与 `execution_receipt` 已彻底分离：前者返回 `box_cleanup_* / workspace_cleanup_*`，后者只汇总最终审查/提交流程状态。
5. BoxLite 运行时元数据已统一为：稳定 `box_name` + 实例级 `box_id`，不再混用。
6. L2 已拆分为两条 canonical 语义：
   - `summer_memory/quintuple_graph.py`：Shell 会话级事实图谱；
   - `agents/memory/semantic_graph.py`：Tool-Result Topology / forensics。

---

## 5. 对原始任务拆解文档的更正

以下旧路径/旧命名已不再作为当前实现依据：

- 原 `agents/runtime/prompt_engine.py` → 当前 canonical 为 `agents/prompt_engine.py`。
- 原 `agents/memory/md_file_memory.py` → 当前 canonical 为 `agents/memory/l1_memory.py`。
- 原“L2 单一事实源”表述 → 当前必须区分 `Shell L2 Graph` 与 `Tool-Result Topology`。
- 原“只有 worktree 沙箱”表述 → 当前已升级为 `host worktree + execution backend(native/boxlite)` 双层模型。

---

## 6. 当前剩余缺口（下一阶段）

1. 继续收缩剩余 sessionless `native` fallback 与更广泛 legacy 兼容入口，使 BoxLite 默认主链之外只保留明确的宿主系统能力。
2. 把 `HierarchicalIndex` 从“可用索引器”继续推进到目标态：补强向量召回、增量重建触发与统一工具入口。
3. 继续对齐 runtime 文档与任务拆解文档，避免目标态蓝图、桥接态实现、历史实施记录三者混写。

---

## 7. 推荐阅读顺序

1. `doc/01-module-overview.md`
2. `doc/09-tool-execution-specification.md`
3. `doc/14-multi-agent-architecture.md`
4. `doc/15-boxlite-first-execution-sandbox-architecture.md`
5. `doc/task/25-subagent-development-fabric-status-matrix.md`
6. `doc/Multi Agent Target Architecturev2.1.md`
