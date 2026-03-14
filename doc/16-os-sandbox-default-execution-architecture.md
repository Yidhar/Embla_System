# 16 — OS-Sandbox-First 默认执行架构

> 文档层级：`L1-TARGET`
> 版本：v1.0 | 2026-03-15
> 前置依赖：[14-multi-agent-architecture](14-multi-agent-architecture.md) · [12-limbs-layer-modules](12-limbs-layer-modules.md) · [09-tool-execution-specification](09-tool-execution-specification.md)

---

## 1. 设计结论

Embla System 的默认可写执行面不再以 `BoxLite-first` 作为 canonical，而改为：

- **控制面留在宿主**：Shell/Core/Expert/Dev/Review 编排、session store、memory、receipt、audit ledger 都继续在宿主进程。
- **工作区边界继续使用 `git worktree`**：每个自维护任务拥有独立 worktree，主 checkout 仍禁止直接作为可写工作面。
- **默认执行面切换为 `os_sandbox_worktree`**：Dev / Review 的文件读写、搜索、命令执行、测试、lint、事务写入默认在宿主 OS 上、受 worktree 根边界约束的执行环境中完成。
- **审批与落库继续留在宿主**：`audit/promote/teardown` 仍由宿主执行，对主仓库拥有唯一最终写入权。
- **`BoxLite` 退居可选强隔离后端**：仅在高风险、不可信代码、浏览器/系统级操作或远端 execution host 场景下显式启用。

简写公式：

`host control plane + host git worktree + os_sandbox execution plane + host audit/promote/teardown`

这个方案的目标不是回退到“无边界宿主执行”，而是把当前 `native execution` 演进为三层明确分工：

- `native`：宿主只读 / system-only fallback
- `os_sandbox`：默认可写执行后端
- `boxlite`：可选强隔离后端

---

## 2. 为什么从 BoxLite-first 调整为 OS-sandbox-first

### 2.1 Embla 当前阶段的核心目标

Embla 现阶段的主任务是：

- 高频 AI 驱动重构
- 小步修改 + 小步验证
- worktree 审计与 promote 流程稳定收口
- 降低新机器初始化成本
- 让 `Shell -> Core -> Expert -> Dev/Review` 主链优先稳定、可观察、低摩擦

这些目标更依赖：

- 与宿主开发环境高度一致
- 冷启动快
- 日志与调试路径直接
- 依赖链少

而不是默认追求最强隔离。

### 2.2 BoxLite-first 的真实成本

`BoxLite-first` 作为默认后端，会把以下前置条件绑定到主链：

- 宿主必须具备 microVM 能力（本地 SDK provider 需要 `KVM`）
- 当前进程必须实际获得 `/dev/kvm` 访问权限
- runtime image 必须能从 registry 拉取，或本机具备本地构镜像能力
- `boxlite` SDK / runtime 行为必须稳定，且与宿主权限模型、网络环境、容器构建链不冲突

这些条件对“默认开发后端”过重，且与 AI 高频试错并不匹配。

### 2.3 为什么“项目内 vendoring runtime 资产”不能替代 KVM

项目内资产仓库可以解决：

- runtime image / guest helper / manifest 的分发问题
- 公网 registry 不可达
- runtime 版本漂移

但不能解决：

- CPU 虚拟化扩展是否存在
- 内核是否加载 KVM 模块
- `/dev/kvm` 是否存在
- 当前进程能否打开 `/dev/kvm`
- 宿主是否允许 nested virtualization

因此：

- **运行时资产可以 vendoring**
- **宿主虚拟化能力不能 vendoring**

这就是 `BoxLite` 不适合作为默认后端、但仍适合作为可选强隔离后端的根本原因。

---

## 3. 默认执行后端分层

Embla 的 canonical `execution_backend` 分为三层：

### 3.1 `native`

定位：宿主只读 / system-only fallback

适用范围：

- Shell 只读工具
- 无 session / 测试 harness
- 审计账本、artifact、killswitch、系统诊断等 host-only 能力

特点：

- 不假定 worktree 是唯一写面
- 不承担自维护任务的默认可写执行职责

### 3.2 `os_sandbox`

定位：默认可写执行后端

适用范围：

- Dev 默认执行
- Review 默认执行
- `core_execution` 的常规自维护任务

特点：

- 执行在宿主 OS 上进行
- 但所有路径、cwd、repo_path、变更事务都以 session 的 worktree 根为 canonical
- 进程树、资源限制、网络策略、输出审计由宿主 runtime 管控

### 3.3 `boxlite`

定位：可选强隔离执行后端

适用范围：

- 第三方不可信代码
- 高风险系统级任务
- 浏览器 / 特定 runtime profile
- 远端 sandbox host 场景

特点：

- 强隔离能力更强
- 但前置条件更重，不再承担默认可写执行主链

---

## 4. OS Sandbox Canonical 拓扑

### 4.1 自维护任务主拓扑

1. Parent 在宿主创建子 Agent。
2. 若 `workspace_mode=worktree`，宿主创建每任务 `git worktree`。
3. Parent 为子 session 写入 `SandboxContext`：
   - `workspace_host_root=<worktree path>`
   - `execution_backend=os_sandbox`
   - `execution_root=<worktree path>`
4. Dev/Review 的工具调用统一进入 `ExecutionBackend` 路由。
5. `OsSandboxExecutionBackend` 负责：
   - 把文件/命令/搜索/事务路径绑定到 worktree 根
   - 以 worktree 作为默认 cwd / repo_path
   - 在宿主进程中执行，并附带进程树监管与资源/网络策略
6. 任务完成后，宿主执行 `audit -> promote -> teardown`。

### 4.2 与当前 worktree 机制的关系

`os_sandbox` 不是替代 worktree，而是：

- **工作区边界**：仍由 `git worktree` 提供
- **执行边界**：由宿主 OS 上的受控进程模型提供
- **审批边界**：仍由 `audit/promote/teardown` 提供

因此，当前已经落地的提交治理资产可以完整保留。

---

## 5. `os_sandbox` 的边界模型

### 5.1 路径边界

对 `os_sandbox` session：

- 默认工作根 = `workspace_host_root`
- `read_file` / `write_file` / `search_keyword` / `list_files` / `workspace_txn_apply` / `git_*` / `run_cmd` 的 canonical 根都应当是该 worktree
- 相对路径一律相对 worktree 根解析
- 绝对路径若逃逸出 worktree 根，应视为违规，而不是仅检查“是否仍在仓库根内”

### 5.2 进程边界

对 `run_cmd` / `python_repl` / 测试 / lint：

- `cwd` 默认固定为 worktree 根
- 所有子进程要绑定 session 级 lineage / kill switch
- 支持会话结束时统一回收子进程树
- detached 进程仍然默认禁止

### 5.3 网络边界

默认策略：

- `os_sandbox` 可写任务默认 **network off**
- 只有显式 profile 或工具契约允许时才打开网络
- 是否允许网络，应进入 `SandboxContext` / execution receipt / runtime posture 可观测字段

### 5.4 资源边界

推荐按 profile 控制：

- CPU 时间
- 内存上限
- 进程数上限
- 单命令超时

实现上不要求第一阶段立即做到最强约束，但接口和状态口径需要预留。

### 5.5 第一阶段已落地的策略字段

为了让 `os_sandbox` 从“默认 backend 名称”升级成“可观察、可治理的默认执行面”，session metadata 与工具回执统一补齐：

- `sandbox_policy`：当前会话生效的 `os_sandbox` profile 名称
- `network_policy`：`enabled | disabled | host`
- `resource_profile`：`standard | heavy | host | ...`

这些字段需要进入：

- child session metadata
- native tool success / error 回执
- `execution_receipt.agent_state.execution_runtime`
- runtime posture 聚合面（至少包含 `os_sandbox_runtime` 摘要）

第一阶段的实际约束：

- `run_cmd` / `python_repl` / `sleep_and_watch` 按 profile 自动钳制超时
- `network_enabled=false` 时，命令通道注入离线环境变量
- `network_enabled=false` 时，对明显联网命令做 denylist 门禁

说明：

- 这一阶段的 no-network 仍是命令级门禁，不等价于完整 OS 防火墙/namespace
- 更强隔离仍由 `BoxLite` 承担
- runtime posture 中，`BoxLite` 不可用若不影响默认可写主链，应降级为 optional warning，而不是主链 critical

---

## 6. 执行后端职责重排

### 6.1 `NativeExecutionBackend`

新语义：

- 仅作为 host-only / sessionless fallback
- 不再默认承担 worktree 可写执行职责
- 不再把 `apply_workspace_path_overrides` 当作 canonical 路径模型

### 6.2 `OsSandboxExecutionBackend`

新默认后端，负责：

- 基于 `workspace_host_root` 做路径重写与 worktree 根约束
- 将 `execution_root` 固定为宿主 worktree 路径
- 复用宿主 `.venv`、Node、git、缓存和开发依赖
- 通过宿主 `NativeExecutor` / `WorkspaceTransactionManager` 执行，但必须带 session-root 感知

### 6.3 `BoxLiteExecutionBackend`

保留，但语义调整为：

- optional strong-isolation backend
- advanced profile backend
- remote execution backend

它不再是默认自维护任务路径。

### 6.4 BoxLite 不可用时的 canonical fallback

`BoxLite` 退出默认主链后，fallback 规则必须明确区分“是否已经具备 worktree 边界”：

- 若 child session 是 `workspace_mode=worktree`
  - 请求 `execution_backend=boxlite`
  - 但 runtime preflight / ensure 失败
  - **canonical fallback = `os_sandbox`**
- 若 child session 没有 worktree（如 project/sessionless/host-only）
  - `boxlite` 不可用
  - **fallback = `native`**

因此：

- `native` 不再承担 self-repo 默认可写执行职责
- 只要 worktree 已存在，fallback 优先回到 `os_sandbox`
- 不能再出现 “BoxLite 失败 -> worktree child 直接退到 host-only native” 的旧口径

---

## 7. `SandboxContext` 演进要求

`SandboxContext` 需要明确支持：

- `execution_backend`：`native | os_sandbox | boxlite`
- `execution_backend_requested`
- `execution_root`
- `workspace_host_root`
- `workspace_mode`
- `execution_profile`
- `sandbox_policy`
- `network_policy`
- `resource_profile`

后续建议追加：

- `process_scope_id`

原则：

- 任何工具层不得自行拼接新的 `project_root / workspace_root / cwd` 口径
- 一切执行边界由 `SandboxContext + ExecutionBackend` 统一决定

---

## 8. Spawn 默认值与升级策略

### 8.1 默认值

新的 target canonical：

- 自维护 Dev：`workspace_mode=worktree`, `execution_backend=os_sandbox`
- 自维护 Review：`workspace_mode=inherit`, `execution_backend=os_sandbox`
- 只读 Shell：宿主只读，不进入可写执行面

### 8.2 升级到 BoxLite 的触发条件

仅在以下场景显式使用 `execution_backend=boxlite`：

- 第三方不可信代码
- 明确需要更强隔离的写操作
- 浏览器自动化
- 专门的强隔离测试 profile
- 远端 `BoxLite REST` execution host

### 8.3 失败降级策略

- `boxlite` 不可用时，若 session 有 worktree，应优先降级到 `os_sandbox`
- 不应直接退回“无 worktree 语义的 native host”
- 只有无 session / host-only 工具链才回退到 `native`

---

## 9. 为什么这更接近 Codex-style OS sandbox

`os_sandbox_worktree` 的目标不是复制某个外部产品的实现细节，而是采用同类原则：

- 默认在宿主 OS 上执行，而不是默认起 microVM
- 通过工作目录、路径边界、进程边界、资源限制、网络开关实现受控执行
- 让默认开发路径优先低摩擦、可观察、环境一致

换句话说：

- **工作台任务**：`os_sandbox`
- **防爆楼任务**：`boxlite`

Embla 当前大多数自维护任务属于前者。

---

## 10. 分阶段落地建议

### Phase A：口径收敛

- 文档 canonical 从 `BoxLite-first` 改为 `OS-sandbox-first`
- `execution_backend` 扩展为 `native | os_sandbox | boxlite`
- 默认配置切到 `os_sandbox`

### Phase B：最小后端骨架

- 引入 `OsSandboxExecutionBackend`
- `NativeExecutionBackend` 收缩为 host-only fallback
- `BoxLite -> host` 降级语义改为：
  - worktree child：`boxlite -> os_sandbox`
  - host-only / sessionless：`boxlite -> native`

### Phase C：session-root 强约束

- 文件路径、cwd、repo_path、事务写入全部以 worktree 根为唯一事实源
- 补齐进程树清理、资源限制、网络策略
- 工具回执与执行收据暴露 `sandbox_policy / network_policy / resource_profile`

### Phase D：高级后端

- `BoxLite` 保留为 opt-in 强隔离
- 支持远端 REST execution host
- 运行时资产仓库仅服务于 `BoxLite` profile，不再阻塞默认主链

---

## 11. 结论

Embla 的默认执行面应当优先满足：

- 新机器容易启动
- 开发环境一致
- worktree 提交流程稳定
- 多 Agent 主链低摩擦

因此，新的 target canonical 应明确为：

**`OS-sandbox-first` 作为默认可写执行后端，`BoxLite` 作为可选强隔离后端。**
