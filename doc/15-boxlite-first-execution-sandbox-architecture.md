# 15 — BoxLite-First 执行沙箱架构

> 文档层级：`L1-TARGET`
> 版本：v1.0 | 2026-03-10
> 前置依赖：[14-multi-agent-architecture](14-multi-agent-architecture.md) · [12-limbs-layer-modules](12-limbs-layer-modules.md) · [09-tool-execution-specification](09-tool-execution-specification.md)

---

## 1. 设计结论

Embla System 的可写 Agent 执行面采用以下 canonical 方案：

- **控制面留在宿主**：Session、Memory、Pipeline、Expert/Review 编排、审计账本都继续运行在宿主进程。
- **工作区边界继续使用 `git worktree`**：每个自维护任务创建独立 worktree，禁止直接对主 checkout 做 `rw` 执行。
- **执行面整体迁入 BoxLite**：Dev / Review 的文件读写、搜索、命令执行、测试、lint、事务写入，以及 `query_docs` / `file_ast_*` 等工作区感知工具都默认在 BoxLite box 内完成。
- **审批与落库继续留在宿主**：`audit/promote/teardown` 仍由宿主执行，对主仓库拥有最终写入权。

简写公式：

`host worktree lifecycle + box execution plane + host audit/promote/teardown`

该方案的目标不是替换现有多 Agent 框架，而是把 `native execution` 重构为可插拔 `execution backend`，并以 BoxLite 作为 Embla 默认可写执行后端。首次缺少 BoxLite SDK 时，运行时会优先通过项目 `.venv` 自动 bootstrap 安装 `boxlite`；只读 Shell 与无 session 宿主工具不在此范围内。

---

## 2. 为什么采用这条路线

### 2.1 需要保留的既有资产

当前运行时已经形成正确的生命周期骨架：

- `spawn_child_agent(..., workspace_mode="worktree")` 为子 Agent 分配独立 worktree。
- `audit_child_workspace` 生成可审批的 diff/report 工件并写入 audit ledger。
- `promote_child_workspace` 仅在显式审批凭证存在时，将 worktree 改动落回主仓库。
- `teardown_child_workspace` 在提交流程结束后销毁临时工作区。

这些语义已经进入 session metadata、ledger 与 `execution_receipt`，不应在引入更强执行隔离时被推倒重来。

### 2.2 需要替换的技术债中心

当前 `native_tools -> native_executor` 模式的主要问题不是没有工作区隔离，而是：

- 路径感知分散在 `workspace_root`、`cwd`、`project_root`、`apply_workspace_path_overrides` 多处。
- `run_cmd` 仍主要在宿主执行，执行边界与工作区边界没有完全统一。
- `workspace_txn_apply`、`python_repl`、`git_*` 与普通文件工具没有共享同一个后端抽象。

如果继续在现有路径重写机制上追加补丁，技术债会持续扩大；因此建议直接重构为 `ExecutionBackend` 抽象，并以 BoxLite 作为 target canonical。

---

## 3. 架构分层

### 3.1 Host / Control Plane

宿主控制面负责：

- `agents/pipeline.py`：Shell/Core/Expert/Dev/Review 生命周期编排
- `agents/runtime/*`：session store、mailbox、parent tools、tool profile 注入
- `summer_memory/*` 与分层记忆系统
- `system/git_worktree_sandbox.py`：worktree 创建、审计、promote、teardown
- 审计账本、receipt 聚合、事件总线与审批逻辑

宿主控制面**不再负责** Dev/Review 的主要读写与命令执行。

### 3.2 Box / Execution Plane

BoxLite 执行面负责：

- `read_file` / `write_file` / `search_keyword` / `list_files`
- `query_docs` / `file_ast_skeleton` / `file_ast_chunk_read`
- `run_cmd` / `git_status` / `git_diff` / `git_grep` / `git_log`
- `python_repl`
- `workspace_txn_apply`
- 测试、lint、build、脚本执行
- 产物输出与必要的 stdout/stderr 回传

对 Dev/Review 来说，`/workspace` 是唯一 canonical 工作根。

### 3.3 Workspace / Approval Boundary

边界拆分固定为三层：

- **工作区边界**：宿主 `git worktree`
- **执行边界**：BoxLite box
- **审批边界**：宿主 `audit/promote/teardown`

这三层边界必须解耦，避免把“运行时隔离”和“主仓库提交流程”耦合成一个不可替换的实现。

---

## 4. Canonical 拓扑

### 4.1 自维护任务推荐拓扑

1. Expert/Parent 在宿主创建子 Agent。
2. 若 `workspace_mode=worktree`，宿主创建每任务 `git worktree`。
3. 若 `execution_backend=boxlite`，宿主以稳定 `box_name` 为该 session 创建/复用 BoxLite box，并记录运行时 `box_id`。
4. 宿主将该 worktree 以 `rw` 挂载到 box 内 `/workspace`。
5. 宿主将主 checkout 以 `ro` 挂载到与宿主一致的绝对路径，用于 worktree `.git` 间接引用、prompt/doc 读取和只读依赖复用。
6. 宿主将主仓库 `.venv` 以 `ro` 挂载到 `/workspace/.venv`，保证 `.venv/bin/python`、pytest、lint 命令在 worktree cwd 下可直接复用。
7. Dev/Review 的工具调用统一经过 `ExecutionBackend`；其中 workspace 执行面默认入 box，artifact/system 类能力允许走 host-bridge。
8. 任务完成后，宿主读取 worktree 并执行 `audit -> promote -> teardown`。

### 4.2 挂载规则

强制口径：

- 主 checkout **不得** 直接以 `rw` 形式挂入 box。
- 允许 `rw` 挂载的唯一仓库写面是“每任务临时 worktree”。
- 文档、prompt 资产、主 checkout 只读镜像与 `.venv` 依赖可使用 `ro` 挂载。
- 审计工件和日志可以通过单独的 artifact 目录导出或 copy-out。

### 4.3 非目标方案

以下方案不作为自维护任务 canonical：

- 直接把主仓库 checkout `rw` 挂到 box。
- 继续以宿主 `run_cmd` 为主，只把 `python_repl` 放进隔离环境。
- 用 BoxLite 取代 `audit/promote/teardown`，让 guest 直接掌握主仓库提交权。

---

## 5. 运行时抽象

### 5.1 `SandboxContext`

为每个 session 维护统一的 sandbox/execution 上下文，至少包含：

- `session_id`
- `workspace_mode`
- `workspace_origin_root`
- `workspace_host_root`
- `workspace_ref`
- `workspace_head_sha`
- `workspace_submission_state`
- `workspace_change_id`
- `execution_backend` (`native` | `boxlite`)
- `execution_root`（对 box 通常为 `/workspace`）
- `box_name`（稳定 session 级别命名，例如 `embla-agent-xxx`）
- `box_id`（运行时分配的实例 ID）
- `box_profile`
- `box_mount_mode`

原则：

- 宿主只关心 `workspace_host_root`。
- guest 只关心 `execution_root`。
- 工具层不得再自行拼接多套 `project_root/workspace_root/cwd` 口径。
- `SandboxContext.default()` 保留 `native` 仅作为无 session / 测试 harness 的宿主 fallback，不代表 session runtime 的默认后端。

### 5.2 `ExecutionBackend`

执行抽象层统一提供：

- `read_file`
- `write_file`
- `search_keyword`
- `list_files`
- `run_cmd`
- `workspace_txn_apply`
- `python_repl`
- `git_*`
- `copy_out_artifact`（如需要）
- `teardown`

推荐实现：

- `NativeExecutionBackend`：保留当前实现作为 fallback / 兼容路径
- `BoxLiteExecutionBackend`：新的 target canonical

### 5.3 `BoxLiteManager`

单独负责 box 生命周期：

- create / reuse / destroy
- volume mount 规划
- exec / timeout / kill semantics
- stdout/stderr / artifact 收集
- profile 到资源策略的映射

`BoxLiteManager` 不拥有 worktree promote 权，不写主仓库 ledger。

---

## 6. 与当前框架的映射关系

### 6.1 保持不变的部分

以下模块保持角色不变：

- `agents/runtime/parent_tools.py`：继续负责 `spawn_child_agent`、`audit_child_workspace`、`promote_child_workspace`、`teardown_child_workspace`
- `system/git_worktree_sandbox.py`：继续负责 worktree 生命周期与 ledger 写入
- `agents/pipeline.py`：继续负责 Review gate、receipt 汇总与 `awaiting_workspace_promotion`
- `memory_*` 与 Shell/Core/Expert 生命周期协议

### 6.2 需要重构的部分

以下模块从“本地执行器”重构为“后端路由器”：

- `apiserver/native_tools.py`
- `system/native_executor.py`
- `system/workspace_transaction.py`

重构后原则：

- `native_tools` 不再直接拥有唯一执行逻辑，而是根据 session 的 `SandboxContext` 选择 backend。
- `apply_workspace_path_overrides` 只作为 native fallback 的兼容层，不再作为 execution canonical。
- `workspace_txn_apply` 必须以 backend 内的工作根为准执行，而不是默认绑定宿主 `project_root`。

---

## 7. 子 Agent 生命周期如何接入 BoxLite

### 7.1 `spawn_child_agent` 扩展字段

在现有参数基础上，新增 target canonical 字段：

- `execution_backend`：`native` | `boxlite`
- `execution_profile`：执行资源/隔离配置预设
- `box_profile`：`default` | `readonly_docs` | `test_runner` | `browser` | `custom`

推荐默认：

- 自维护 Dev：`workspace_mode=worktree`, `execution_backend=boxlite`
- 自维护 Review：`workspace_mode=inherit`, `execution_backend=boxlite`
- 只读 Shell：仍保持宿主只读，不进入 box

### 7.2 Spawn 流程

当 Parent 以 `workspace_mode=worktree` + `execution_backend=boxlite` 创建子 Agent 时：

1. 宿主创建 worktree。
2. 宿主创建 box 并建立 volume mount。
3. 宿主写入 `SandboxContext` 到 session metadata。
4. 工具调用阶段由 backend router 将该 session 的执行流量导入 box。
5. Agent 停止后，宿主根据 Review 结果决定 `audit/promote/teardown`。

### 7.3 Review 语义保持不变

Review Agent 仍是独立子 Agent；变化只在执行后端：

- 代码审查读取改动、搜索反模式、执行必要验证时，默认在同一 worktree 对应 box 内完成。
- `approve/request_changes/reject` 生命周期和当前事件协议保持不变。

---

## 8. 工具路由 canonical

### 8.1 文件类工具

- `read_file` / `write_file` / `list_files` / `search_keyword`
- 统一路由到 `ExecutionBackend`
- 对 `boxlite` 后端，路径全部相对 `execution_root=/workspace`
- `query_docs`、`file_ast_skeleton`、`file_ast_chunk_read` 通过 guest helper 在 box 内执行，不再默认走宿主桥接

### 8.2 命令类工具

- `run_cmd`
- `git_*`
- 测试 / lint / build 命令
- 全部在 box 内 `/workspace` 运行

这意味着“执行边界”与“工作区边界”最终收敛到同一处，不再出现“文件改在 worktree、命令跑在宿主”的裂缝。

### 8.3 `python_repl`

- 目标态不再把 `docker` 作为自维护主路径
- `python_repl` 统一作为 `ExecutionBackend.python_repl()` 的一种实现
- 对 `boxlite` 后端，在 box 内执行隔离 Python 进程

### 8.4 `workspace_txn_apply`

建议拆成两层：

- `WorkspaceTransactionPlanner`：契约校验、diff 计划、回滚计划生成
- `ExecutionBackend.apply_workspace_transaction()`：在 backend 的工作根内执行原子写入/校验/回滚

对 `boxlite` 后端，事务的物理写入发生在 box 内 `/workspace`，其宿主对应路径就是 worktree 挂载点，因此 `audit/promote` 可直接消费结果。

---

## 9. 审计与 promote 语义

### 9.1 `audit`

`audit_child_workspace` 仍然读取宿主 worktree：

- 生成 `audit_report.json`
- 生成 tracked diff
- 记录 `worktree_audit` ledger 事件

BoxLite 不负责最终审计结论，只负责把变更写入 worktree。

### 9.2 `promote`

`promote_child_workspace` 仍然由宿主执行：

- 校验 `approval_ticket`
- 检查主仓库与 worktree baseline 的冲突
- 将 audited worktree 的改动复制回主仓库根
- 记录 `worktree_promoted` ledger 事件

这保证了：即使执行在 box 内发生，主仓库仍只接受审计过的 worktree promote。

### 9.3 `teardown`

收尾顺序建议固定为：

1. 停止/销毁 box
2. 移除 worktree
3. 写入 `worktree_teardown` ledger

如 box 销毁失败，不得跳过 ledger 记录；失败也必须可审计。

### 9.4 `execution_receipt` 语义保持不变

BoxLite-first 改造**不改变**以下 canonical：

- 只要 worktree 尚未 promote/teardown 收口，`execution_receipt.stop_reason` 仍可保持 `awaiting_workspace_promotion`
- Review gate 仍以最终生效的 `approve/request_changes/reject` 判定
- 中间态审查事件仍通过 `review_result`、`review_rework_requested`、`review_reject_respawn` 暴露

---

## 10. 安全基线

### 10.1 基线原则

- 主 checkout 永不直接 `rw` 暴露给 guest
- 每任务使用一次性 worktree
- 默认最小挂载、最小权限、最小网络
- 宿主拥有最终 promote 权和 ledger 写入权

### 10.2 Policy Firewall 位置

Policy Firewall 继续保留在宿主控制面：

- 负责工具 allowlist / denylist
- 负责高风险调用治理
- 负责 receipt 与审计字段的一致性

BoxLite 是执行隔离层，不取代高层策略治理。

### 10.3 产物与日志

建议区分：

- `display_preview`：短回显，进入 SSE / LLM 上下文
- `raw_artifact_ref`：完整工件，按需读取

避免将大型结构化结果直接截断后回灌模型。

---

## 11. 分阶段实施

### Phase A：抽象收口（低风险）

目标：不改变现有行为，只抽象接口。

- 引入 `SandboxContext`
- 引入 `ExecutionBackend`
- 将当前实现封装为 `NativeExecutionBackend`
- 让 `native_tools` 改为 backend router

### Phase B：最小 BoxLite 路径

目标：先打通主要编码任务。

- `read_file`
- `write_file`
- `search_keyword`
- `run_cmd`

使用 `host worktree + box rw mount` 完成最小闭环。

### Phase C：全部工具 canonical 到 BoxLite

- `workspace_txn_apply`
- `python_repl`
- `git_*`
- 测试 / lint / build
- artifact export

### Phase D：清理旧兼容链（主链已完成）

- 降级 `apply_workspace_path_overrides` 为兼容层
- 收缩宿主直接执行路径到 `artifact_reader` / `killswitch_plan` 等系统级 host-bridge
- 已将默认可写执行 backend 固化为 `boxlite`

---

## 12. 最终 canonical 决策

Embla System 对默认可写执行链的最终口径统一为：

- **保留**：`git worktree + audit/promote/teardown`
- **替换**：`native execution` 的默认主路径
- **新增**：`SandboxContext + ExecutionBackend + BoxLiteExecutionBackend`
- **默认**：Dev/Review 在 box 内执行，Shell/控制面留宿主
- **兼容**：无 session / 测试 harness 允许 `native` 宿主 fallback，但不改变 session runtime 默认值

因此，BoxLite 在 Embla 中的角色不是“替代 worktree sandbox”，而是：

**作为 worktree sandbox 之下的默认执行后端，为现有多 Agent 框架提供更强、更统一的执行隔离。**
