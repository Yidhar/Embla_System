# WS24x 设计讨论稿：Prompt 路由注入与多职能 Agent 注入时机

文档状态：设计稿（Executable Draft）  
最后更新：2026-02-26  
适用范围：`SystemAgent / Router / LLM Gateway / Agentic Loop / Sub-Agent Runtime`  

---

## 0. 审阅意见采纳结论（本轮）

针对本轮 PR Review（双层常驻代理 + 专家子代理库 + 命中率评估）逐条评估后，采纳结果如下：

1. 背景痛点补充：采纳。
- 原因：与当前 `/chat`、`/chat/stream`、`agentic_loop` 三条链路并存导致的上下文混叠问题一致。

2. 外部参考中“细分专家代理库”结论：采纳（措辞保守化）。
- 原因：逆向仓库确有大量细分 prompt，但数量以“数量级 40+”描述，避免写成绝对事实。

3. 分层与优先级调整（新增 `L1.5`，强调 `L3` 硬覆盖 `L2`）：采纳。
- 原因：与当前项目“工具物理权限优先于角色自我描述”原则一致。

4. 双层常驻模型（Outer Chat + Core Execution）：采纳为目标态，明确“分阶段迁移”。
- 原因：适配方向正确，但当前代码尚未完成物理双进程隔离，需按阶段落地。

5. `PromptComposeDecision` 增加路由评估字段：采纳。
- 原因：满足后续离线评估与路由回放需求。

6. `enforcement_mode: shadow|block` 与离线评估管道：采纳。
- 原因：可先审计后拦截，降低切换风险。

7. 验收指标新增命中率和只读暴露率：采纳。
- 原因：可量化且可被自动化回归验证。

8. 原“开放讨论问题”闭环为决议：采纳。
- 原因：进入工程化阶段需要明确约束而非继续悬而未决。

9. `Logical Priority` 与 `Physical Serialization` 解耦：采纳。
- 原因：避免把高动态切片提前拼接，导致 Anthropic Prompt Cache 前缀失效。

10. `L4_RECOVERY` 由固定 `ttl_rounds` 升级为混合 TTL：采纳。
- 原因：纯轮次 TTL 对 ReAct 长链修复不稳定，易在根因未收敛前失忆。

11. 契约屏障分级（Seed Contract -> Execution Contract）：采纳。
- 原因：避免 Outer 在 Path-B 进入“表单式盘问”，保持交互流畅性。

12. 冲突消解从 `conflicts_with[str]` 升级为语义域规则：采纳。
- 原因：降低 slice 重命名导致静默失效的风险。

13. DNA manifest 语义统一为 `.spec`：采纳。
- 原因：当前发布门禁和收口脚本默认使用 `system/prompts/immutable_dna_manifest.spec`，需消除 `.json` 与 `.spec` 混用歧义。

14. 增加“现状可支持度评估”并明确分阶段能力边界：采纳。
- 原因：当前代码可支持多 Agent Prompt 的“第一阶段”，但尚不具备完整 Prompt Slice 引擎与物理双层隔离。

15. 增加 Prompt 可修改分级（S0/S1/S2）与 AI 可改边界：采纳。
- 原因：需要在“自治效率”与“核心安全”之间建立可执行治理边界。

16. 增加目录规范与框架改造清单（文件级）：采纳。
- 原因：便于后续按增量任务直接实施，不再停留在概念描述。

---

## 1. 背景与问题

当前项目已具备若干 prompt 相关能力，但“何时注入、注入什么、注入多久、谁来注入”仍缺统一策略，导致以下风险：

1. 注入时机不统一：同一请求在不同链路（`/chat` vs `/chat/stream` vs `agentic_loop`）注入行为不一致。
2. 注入粒度偏粗：system prompt 常按“整段拼接”处理，缺少按阶段和风险的细粒度装配。
3. 生命周期不清：临时补救 prompt 未显式 TTL，容易污染后续轮次。
4. 多职能并发盲写：前后端/Ops 子代理并行时缺注入契约屏障，字段和验收口径容易错位。
5. 可审计性不足：缺少“本轮最终 prompt 由哪些片段组成”的可回放证据。
6. 外层闲聊与核心执行上下文混叠：缺少常驻外层代理与核心执行代理的物理隔离，日常闲聊容易污染执行链路。
7. 多专家路由漂移与 Ping-Pong：专家代理增多后，Router 意图误判会导致错误重试、反复切换和 Token 浪费。

---

## 2. 当前实现锚点（As-Is）

### 2.1 已有能力

1. 固定顺序 DNA 注入：
- `system/immutable_dna.py`
- 基于 `immutable_dna_manifest.spec` 的 `injection_order` 做顺序装配与 hash 校验（发布门禁同源）。

2. 三段式 Prompt Envelope：
- `autonomous/llm_gateway.py`
- `block1(static_header) + block2(long_term_summary) + block3(dynamic_messages)`，并具备缓存和 token 估算。

3. 动态窗口治理：
- `autonomous/working_memory_manager.py`
- soft/hard 双阈值 + critical marker 保留。

4. 记忆回注：
- `apiserver/agentic_tool_loop.py`
- 通过 `_inject_ephemeral_system_context()` 注入 `[Episodic Memory Reinjection]`。

5. 系统提示词拼接入口：
- `system/config.py::build_system_prompt()`
- 当前按“基础人格 + 附加知识 + 时间 + 技能 + 工具提示 + RAG”拼接。

### 2.2 缺口归纳

1. `RouterDecision` 只决定角色/模型/工具，不决定 prompt 片段注入策略。
2. 注入策略缺“阶段触发器”和“失败触发器”。
3. 子代理 spawn 时缺“最小必要上下文”强约束。
4. 缺注入冲突消解机制（例如技能指令覆盖安全策略）。
5. Outer/Core 尚未物理隔离，执行代理仍会间接受到闲聊历史影响。

### 2.3 现状可支持度评估（2026-02-26）

| 能力项 | 当前状态 | 结论 |
|---|---|---|
| 三路径准入（Path-A/B/C） | 部分具备（逻辑上可区分，未形成统一路由判定层） | 可先落地 P0 逻辑隔离 |
| 多 Agent Prompt 路由 | 部分具备（role/tool profile 有基础） | 需补 `prompt_profile/injection_mode` |
| Prompt Slice 组合引擎 | 未落地 | 需在 `autonomous/llm_gateway.py` 实现 |
| Prompt ACL（按文件/层级权限） | 未落地 | 必须优先补齐 |
| Outer/Core 物理隔离 | 未落地 | 先逻辑隔离，后进程隔离 |
| DNA 门禁一致性 | 已具备（`.spec`） | 作为核心不可降级约束 |

当前可执行判断：

1. 当前项目支持“多 Agent Prompt 的第一阶段（逻辑隔离 + 路由字段扩展）”。
2. 当前项目不支持“完全放任 AI 修改 Prompt”。
3. 在未引入 ACL 之前，核心 Prompt 改动必须走“审批票据 + manifest 重算 + gate 复验”。

---

## 3. 外部参考（Claude Code 逆向仓库）与启发

参考仓库：`Piebald-AI/claude-code-system-prompts`  
链接：<https://github.com/Piebald-AI/claude-code-system-prompts>

观察到的结构特征：

1. 主系统提示很薄，能力通过多段条件片段组合。
- 参考：`system-prompt-main-system-prompt.md`

2. 工具策略提示独立成片段，专门约束并行调用、工具优先级、参数完整性。
- 参考：`system-prompt-tool-usage-policy.md`

3. 子代理提示高度专用化（如 Explore/Plan 为严格只读）。
- 参考：`agent-prompt-explore.md`、`agent-prompt-plan-mode-enhanced.md`

4. Task 工具本身有额外注记，约束路径/格式/并行行为。
- 参考：`agent-prompt-task-tool.md`、`agent-prompt-task-tool-extra-notes.md`

5. 可见大量细分专家 prompt（数量级 40+），角色边界清晰。
- 典型角色：执行者（Task/Coder）、只读探索者（Explore）、规划者（Plan）、审查/压缩类后台代理。

设计启发：

1. Prompt 不是单一字符串，而是“角色化、阶段化、工具化”的片段集合。
2. 子代理 prompt 必须角色隔离，且具备硬限制（只读/禁止写）。
3. 工具策略应作为独立层，而非掺杂在对话风格中。
4. 核心执行代理不应包揽全部任务，应通过 `spawn_sub_agent` 拉起降权专家代理执行。

---

## 4. 目标态设计原则（To-Be）

1. 事件驱动注入：按阶段与风险触发，不按“固定模板全量拼接”。
2. 最小必要注入：默认最小，缺证据再补充。
3. 生命周期可控：每个片段有 TTL、drop 条件、冲突策略。
4. 可审计可回放：每轮输出注入快照（含来源、版本、hash）。
5. 安全不可被覆盖：安全层优先级高于技能层与任务层。
6. 工具物理权限优先：模型角色描述不得突破工具层权限隔离。
7. 逻辑优先级与物理拼接顺序解耦：先按逻辑裁剪，再按缓存友好顺序序列化。

### 4.1 DNA 单源约束（强制）

1. DNA manifest 统一使用：`system/prompts/immutable_dna_manifest.spec`。
2. 发布与验收链统一依赖 `.spec`，禁止并行维护 `.json` 作为第二事实源。
3. 任何受 DNA 保护 prompt 变更后，必须执行：
- `scripts/update_immutable_dna_manifest_ws23_003.py --approval-ticket ... --strict`
- 或等价“approved_update_manifest + gate 复验”流程。

---

## 5. 注入时机判定模型

定义四类触发器：

1. `phase_trigger`
- 请求进入新阶段时触发。
- 阶段建议：`intake -> plan -> contract -> execute -> recover -> summarize`

2. `risk_trigger`
- 风险阈值触发安全/事务片段。
- 典型条件：`write_intent=true`、`requires_global_mutex=true`、`risk_level in {write_repo, deploy, secrets, self_modify}`

3. `evidence_trigger`
- 缺关键证据时触发“证据补齐片段”。
- 典型条件：缺 `contract_schema`、缺 `trace_id`、缺 `raw_result_ref` 可读路径。

4. `failure_trigger`
- 连续失败或同根因重复时触发恢复片段。
- 建议阈值：`same_root_cause_streak >= 2`

判定顺序（建议）：

1. 先 `phase_trigger`
2. 再 `risk_trigger`
3. 再 `evidence_trigger`
4. 最后 `failure_trigger`

---

## 5.1 聊天与执行的三路径准入（新增）

为同时满足“高自动化 + 低延迟 + 低误触发”，采用三路径准入：

1. `Path-A: Outer Direct Read-Only`（默认优先）
- 适用：问候、闲聊、上传文件总结、文档检索、只读问答。
- 执行：Outer Chat 直接处理，仅加载只读能力，不进入 Core。
- 目标：`hi` 类请求 P95 `<300ms`。

2. `Path-B: Outer Clarify`
- 适用：意图不明确或输入信息不足。
- 执行：Outer 先澄清并生成 `Seed Contract`（最小必填 + 假设项），再决定是否升级 Core。

3. `Path-C: Core Execution`
- 适用：写操作、跨模块编排、多代理协同、需要回滚/重试治理。
- 执行：进入 Core 做路由、门禁、契约校验、权限裁剪与调度。

升级到 Core 的最小条件（建议）：

1. `write_intent=true` 或存在外部副作用。
2. 需要多阶段编排（单轮只读无法完成）。
3. 需要拉起专家子代理并行处理。

---

## 6. Prompt 分层、优先级、物理拼接与缓存规则

建议引入六层（兼容当前 `PromptEnvelope`，并补上 `L1.5`）：

1. `L0_DNA`（不可变）
- 来源：`ImmutableDNALoader.inject()`
- 优先级最高，不可覆盖。

2. `L1_TASK_BASE`
- 任务目标、验收标准、输出格式。

3. `L1.5_EPISODIC_MEMORY`
- 任务级长期证据与记忆回注。
- 绑定任务生命周期，不归入临时补救层。

4. `L2_ROLE`
- `sys_admin / developer / researcher` 等角色约束。
- 由 `RouterDecision.selected_role` 触发。

5. `L3_TOOL_POLICY`
- 与本轮工具/执行模式直接相关的硬规则（并行、参数完整性、只读模式、权限边界）。

6. `L4_RECOVERY`
- 失败后短期补救策略，必须 TTL 限制。

优先级：`L0 > L3 > L2 > L1.5 > L1 > L4`

强覆盖规则：

1. `L3_TOOL_POLICY` 必须硬覆盖 `L2_ROLE`。
2. 即使 `L2` 声称“可执行任意改动”，当 `L3` 只挂载只读工具时，模型必须服从只读约束。
3. 禁止“模糊局部覆盖”绕过工具层物理权限。

### 6.1 Prompt Caching 悖论处理（Logical vs Physical）

逻辑优先级用于“冲突裁剪”，不等于“物理拼接顺序”。  
物理拼接目标是提升缓存命中并降低延迟/成本。

推荐两阶段流程：

1. 逻辑阶段（无关序列化）
- 按 `L0 > L3 > L2 > L1.5 > L1 > L4` 做筛选与冲突消解。
- 输出“已确定的最终有效切片集合”。

2. 物理序列化阶段（缓存友好）
- `P0_STATIC_PREFIX`（尽量稳定，可缓存）：`L0 + L1(稳定部分) + L2 + L3`
- `P1_DYNAMIC_TAIL`（高动态，不放在前缀）：`L1.5 + L4 + 本轮证据/错误摘要`

硬规则：

1. 高动态切片（`L1.5/L4`）禁止插入缓存前缀。
2. `L3` 约束必须在最终可见 Prompt 中明确出现（可位于静态前缀末端）。
3. 每轮记录 `prefix_hash` 与 `tail_hash`，用于命中率与漂移追踪。

### 6.2 Prompt 可修改分级（Lockdown Policy）

定义三层可修改策略：

1. `S0_LOCKED`（核心锁死，AI 不可直接修改）
- 仅允许人工审批+代码评审+门禁链路变更。
- 目录/文件（当前）：
  - `system/immutable_dna.py`
  - `scripts/validate_immutable_dna_gate_ws23_003.py`
  - `scripts/update_immutable_dna_manifest_ws23_003.py`
  - `system/policy_firewall.py`
  - `apiserver/agentic_tool_loop.py`
  - `apiserver/native_tools.py`
  - `system/native_executor.py`
  - `system/workspace_transaction.py`
  - `system/global_mutex.py`
  - `system/process_lineage.py`
  - `autonomous/policy/gate_policy.yaml`

2. `S1_CONTROLLED`（可改但强管控）
- 允许 AI 生成变更，但必须审批票据+DNA 重算+gate 通过。
- 文件（当前 4/4）：
  - `system/prompts/conversation_style_prompt.txt`
  - `system/prompts/conversation_analyzer_prompt.txt`
  - `system/prompts/tool_dispatch_prompt.txt`
  - `system/prompts/agentic_tool_prompt.txt`

3. `S2_FLEXIBLE`（可放任修改）
- 非核心专家 prompt、实验型角色 prompt、可回退模板。
- 当前仓库尚未拆分此目录，现阶段可放任数量：`0`。

治理结论（当前阶段）：

1. 当前 4 个 DNA prompt 均不是“放任修改”对象。
2. 在多 Agent Prompt 目录拆分完成前，默认按 `S1_CONTROLLED` 处理。

### 6.3 目录规范（多 Agent Prompt）

目标目录（To-Be）：

1. `system/prompts/core/`
- DNA 受控核心 prompt（S1/S0 配套治理）

2. `system/prompts/agents/outer/`
- 外层交互代理 prompt（Path-A/B）

3. `system/prompts/agents/core_exec/`
- 核心执行代理 prompt（Path-C）

4. `system/prompts/agents/experts/`
- 专家子代理 prompt（Explore/Plan/Review/Ops 等）

5. `system/prompts/agents/recovery/`
- 故障恢复与补救策略 prompt（L4）

6. `system/prompts/specs/`
- `prompt_registry.spec`（切片注册、层级、TTL、冲突域）
- `prompt_acl.spec`（文件级修改权限策略）

迁移约束：

1. P0 先保持现有平铺文件可读，新增 registry 映射层兼容旧路径。
2. 目录迁移期需支持 alias 与回放对齐，避免旧切片引用失效。

---

## 7. 多职能 Agent 注入时机（关键）

### 7.1 双层常驻隔离模型（Two-Layer Persistent Model）

1. 外层交互代理（Outer Chat Agent）
- 职能：负责闲聊、需求澄清、生成执行契约（Contract）。
- 注入包：`L0_DNA + L1_TASK_BASE + L2_ROLE(Chat/Router)`。
- 工具权限：`ask_user`, `search_kb`, `read_uploaded_file`, `summarize_doc`, `delegate_to_core`（目标态）。
- 说明：上传文件总结/文档检索默认走 Outer 只读路径，不必直接拉起 Core。

2. 核心执行代理（Core Execution Agent）
- 职能：后台无头执行，不直接消费闲聊历史，仅消费 Contract。
- 注入包：`L0_DNA + L3_TOOL_POLICY + L4_RECOVERY`。
- 工具权限：系统执行工具 + `spawn_sub_agent`（目标态）。

3. 迁移说明
- 当前实现仍以单链路编排为主，本节是目标态结构。
- 先做逻辑隔离（Contract-only 输入），再做物理隔离（进程/会话隔离）。

### 7.2 专家子代理拉起与权限降级（Sub-Agent Spawning & Downgrade）

1. 子代理禁止越权直连用户，必须由 Core Agent 基于 Contract 拉起。
2. 拉起时必须声明 `delegation_intent`、`target_agent_type`、`contract_stage` 与契约校验和（`seed_contract_checksum` 或 `contract_checksum`）。
3. 若目标代理为 `Explore` 或 `Security_Review`：
- LLM Gateway 组装时必须剔除写工具 schema（如 `os_bash` 写命令、`edit_file`、`workspace_txn_apply`）。
- Prompt 层追加强只读约束（如 `CRITICAL: READ-ONLY MODE`）。

### 7.3 并行多职能契约屏障（Frontend/Backend/Ops）

为避免 Path-B 退化为“盘问式 UX”，采用分级契约屏障：

1. `Seed Contract`（低阻塞）
- 最小必填：`goal`、`scope_hint`、`risk_class`、`acceptance_hint`。
- 允许 `unknown_fields`，由 Outer 写入 `assumptions[]` 并标注 `confidence`。
- 生成 `seed_contract_checksum`，可用于 Core 的只读侦察/计划。

2. `Execution Contract`（写入前强校验）
- 首次写操作前，必须补齐写路径/副作用/回滚与验收口径。
- 生成 `contract_checksum` 并广播到所有子任务元数据。

3. 执行门禁
- `seed_contract_checksum`：允许 Path-C 只读分析、依赖探测、方案草拟。
- `contract_checksum`：才允许并行写入和落地执行。
- 未达 Execution Contract 时，系统自动降级为只读探索，不阻塞整个会话。

### 7.4 高风险二次确认矩阵（新增）

必须二次确认（默认）：

1. 删除/覆盖/批量改写类操作。
2. 生产态或外部系统高影响动作（部署、回滚、权限变更、网络隔离）。
3. 可能产生不可逆副作用的命令链。

可免二次确认（受限）：

1. 明确在沙箱/隔离环境中的编码和测试动作。
2. 无外部副作用、可回滚、且权限已限定在工作区内的写操作。

兜底规则：

1. 即使处于“可免确认”路径，一旦命中高危模式仍强制确认。
2. 二次确认仅作用于高风险动作，避免把低风险动作全部变成人工审批。

---

## 8. 建议数据结构（新增）

```python
@dataclass(frozen=True)
class SliceTTLPolicy:
    mode: str                    # rounds|time|event|hybrid
    rounds_soft: int             # 软过期：超过后降权但不立即删除
    rounds_hard: int             # 硬过期：超过后强制移除
    max_age_seconds: int
    keep_until_error_resolved: bool
    renew_on_progress: bool      # 发现新证据/进展时续租
    drop_on_resolution: bool
```

```python
@dataclass(frozen=True)
class PromptSlice:
    slice_uid: str               # 不随重命名变化的稳定 ID
    slice_name: str              # 可读名称，可演进
    layer: str                   # L0/L1/L1.5/L2/L3/L4
    owner: str                   # system/router/role/tool/memory/recovery
    content_ref: str             # prompt repo path or inline key
    source_hash: str
    stability_class: str         # static|session|round
    cache_segment: str           # prefix_static|prefix_session|tail_dynamic
    inject_when: dict[str, Any]  # phase/risk/evidence/failure conditions
    drop_when: dict[str, Any]
    ttl_policy: SliceTTLPolicy
    priority: int
    conflict_domain: str         # e.g. "tool_policy.exec_mode"
    conflict_tags: list[str]     # e.g. ["read_only", "write_enabled"]
    supersedes: list[str]        # 以 slice_uid 声明替代关系
    aliases: list[str]           # 历史名称，用于兼容与迁移校验
```

```python
@dataclass(frozen=True)
class PromptComposeDecision:
    trace_id: str
    round_num: int
    selected_slices: list[str]
    dropped_slices: list[str]
    reasons: list[str]
    token_budget_before: int
    token_budget_after: int

    # 路由评估追踪字段
    delegation_intent: str       # 预期意图 (e.g., "read_only_exploration")
    target_agent_type: str       # 实际路由目标 (e.g., "ExploreAgent")
    contract_stage: str          # seed|execution
    seed_contract_checksum: str | None
    contract_checksum: str | None

    # 缓存与序列化观测字段
    prefix_hash: str
    tail_hash: str
```

```python
@dataclass(frozen=True)
class PromptACLRule:
    path_pattern: str            # e.g. system/prompts/core/*
    level: str                   # S0_LOCKED | S1_CONTROLLED | S2_FLEXIBLE
    require_ticket: bool
    require_manifest_refresh: bool
    require_gate_verify: bool
    allow_ai_direct_write: bool
```

---

## 9. 组合算法（建议）

1. 收集候选切片。
- DNA、任务、角色、工具策略、记忆回注、恢复策略。

2. 按触发器筛选。
- 仅保留满足 `inject_when` 的切片。

3. 语义冲突消解。
- 先按 `conflict_domain` 分组，再按层级优先级/priority/版本进行选择。
- `supersedes` 仅接受稳定 `slice_uid`，禁止以可变 `slice_name` 做硬依赖。
- 兼容模式下可读取旧 `conflicts_with`，但必须在启动期做 dangling 引用校验并告警。

4. 生命周期处理。
- 按 `ttl_policy` 执行软过期/硬过期。
- 对 `keep_until_error_resolved=true` 的 L4：在“根因未解决且有进展”时续租，避免中途失忆。

5. 预算裁剪。
- 固定保留 `L0/L3`。
- 优先裁剪 `L4`，再裁剪低优先级扩展段。

6. 物理序列化。
- 先输出 `prefix_static/prefix_session`，最后附加 `tail_dynamic`。
- 记录 `prefix_hash`、`tail_hash` 与 `cache_hit_expected`。

7. 产出审计事件。
- `PromptComposeDecisionMade`
- `PromptSliceInjected`
- `PromptSliceDropped`

---

## 10. 与当前代码的最小集成路径

### 10.1 P0（先可用）

1. 在 `autonomous/router_engine.py` 输出中增加：
- `prompt_profile`（role/tool-policy class）
- `injection_mode`（minimal/normal/hardened/recovery）

2. 在 `autonomous/llm_gateway.py` 增加：
- `PromptSlice` 输入
- `compose()` 逻辑与 `PromptComposeDecision` 回执
- `enforcement_mode: shadow | block`
- 逻辑裁剪与物理序列化分离（`resolve()` vs `serialize_for_cache()`）

3. 在 `apiserver/agentic_tool_loop.py`：
- 将 episodic reinjection 迁移为标准 `L1.5` 切片（任务生命周期绑定）
- 引入 `Seed Contract` 到 `Execution Contract` 的升级状态机

4. 灰度模式要求：
- `shadow`：仅记录越权/冲突审计，不拦截。
- `block`：触发即拒绝执行。

5. 准入策略要求：
- Path-A（Outer 只读）默认开启，用于聊天/上传总结/文档检索。
- 仅当满足 Core 升级条件时才进入 Path-C。

### 10.2 P1（可观测）

1. 在 `logs/autonomous/events.jsonl` 写入注入决策事件。
2. 在 `scripts/export_slo_snapshot.py` 增加注入质量指标：
- `prompt_slice_count_by_layer`
- `injection_trigger_distribution`
- `recovery_slice_hit_rate`
- `prompt_conflict_drop_count`
- `delegation_hit_rate`
- `outer_readonly_hit_rate`
- `core_escalation_rate`
- `prompt_prefix_cache_hit_rate`
- `prompt_tail_churn_rate`
- `contract_upgrade_latency_ms`
- `recovery_context_survival_rate`

### 10.3 P2（多代理并行保障）

1. 子代理 spawn 前强制 `contract prompt slice` 对齐。
2. 并行写任务必须带 `contract_checksum`，否则降级为只读探索。
3. 只读代理注入时，写工具暴露率必须可观测并可审计。

### 10.4 P3（动态并发控制，无固定 hard cap）

并发控制不使用固定“每轮最多 N 个子代理”，改为资源驱动：

1. `machine_slots`：由 CPU、内存、IO、队列长度实时计算。
2. `task_slots`：由任务 DAG 可并行宽度计算（仅对无依赖冲突单元并行）。
3. `time_slots`：由任务时间成本预测计算（避免长任务挤占导致雪崩）。

建议并发上限：

`max_parallel = min(machine_slots, task_slots, time_slots)`

说明：

1. 预算（cost/tokens）作为观测项，不作为并发门禁硬条件。
2. 保留熔断器：机器水位超阈值或失败风暴出现时自动下调并发。

### 10.5 P4（专家路由评估管道）

1. 构建 Ground Truth 评测集（建议 >= 500 标准开发/运维场景）。
2. 建立 `Routing Evaluator` 离线回放机制，周期评估 Router 派发质量。
3. 输出 `Precision / Recall / F1 / First-hit-rate`，用于专家代理增删和阈值调优。

### 10.6 文件级改造清单（必须项）

为支持“多 Agent Prompt + 可控改写”，需改造以下模块：

1. `autonomous/router_engine.py`
- 增加：`prompt_profile`、`injection_mode`、`delegation_intent`。
- 输出路由决策时携带 prompt 侧约束元数据。

2. `autonomous/llm_gateway.py`
- 增加：`PromptSlice` 输入结构、`resolve()` 与 `serialize_for_cache()` 双阶段组合。
- 增加：`PromptComposeDecision` 回执与 `prefix_hash/tail_hash` 观测。

3. `system/config.py`
- `build_system_prompt()` 从固定拼接迁移为基于 profile 的切片组合入口。
- 保留旧接口兼容层，避免 `/chat` 与 `/chat/stream` 行为突变。

4. `system/background_analyzer.py`
- `conversation_analyzer_prompt + tool_dispatch_prompt` 从固定模板升级为 profile 可选模板集。
- 保证 analyzer 路由与 Core 路由策略一致。

5. `apiserver/api_server.py`
- `/system/prompts/*` 引入 `prompt_acl.spec` 校验。
- 对 S0/S1 文件实施写入拦截与审批票据校验。

6. `scripts/validate_immutable_dna_gate_ws23_003.py`
- 继续作为 `.spec` 单源门禁，不引入并行 `.json` 事实源。

7. `scripts/update_immutable_dna_manifest_ws23_003.py`
- 作为受控更新入口，后续接入 ACL 与审计元数据（owner/change_reason）。

### 10.7 P0 实施任务卡（按文件+测试项+验收标准）

> 说明：以下任务卡按 `doc/task/00-task-unit-spec.md` 最小字段组织，定位为本设计稿对应的首批可落地改造包。  
> 任务号采用 `NGA-WS28-*` 暂编排，后续并入主任务清单时可按排期重映射。

### NGA-WS28-001 扩展 Router 决策字段并保持兼容
- type: `feature`
- priority: `P0`
- phase: `M13`
- owner_role: `backend`
- scope: `RouterDecision` 输出契约扩展；不改变现有调用方默认行为
- inputs: `doc/task/24-ws-prompt-routing-injection-policy.md` §5/§10.6；`autonomous/router_engine.py`
- depends_on: `-`
- deliverables:
  - 代码文件：`autonomous/router_engine.py`
  - 测试文件：`tests/test_router_engine_prompt_profile_ws28_001.py`
  - 报告产物：`scratch/reports/ws28_001_router_prompt_profile.json`
- acceptance:
  - 新增字段 `prompt_profile`、`injection_mode`、`delegation_intent`，默认值覆盖旧调用链。
  - 旧链路（不传新字段）执行结果与基线一致（行为无突变）。
  - 执行：`.venv/bin/pytest -q tests/test_router_engine_prompt_profile_ws28_001.py`
  - 产物文件存在且 `passed=true`。
- rollback:
  - 回退到仅保留旧字段输出分支，并移除新增字段在序列化中的强依赖。
  - 恢复前需保留本次新增测试作为回归防护（预期改为 xfail 或删除并记录原因）。
- status: `done`（2026-02-26，已通过 `tests/test_router_engine_prompt_profile_ws28_001.py`）

### NGA-WS28-002 落地 Prompt Slice 组合引擎（Resolve/Serialize 双阶段）
- type: `feature`
- priority: `P0`
- phase: `M13`
- owner_role: `backend`
- scope: `LLM Gateway` 的 prompt 组合核心；支持逻辑裁剪与缓存友好序列化解耦
- inputs: `doc/task/24-ws-prompt-routing-injection-policy.md` §6/§9/§10.6；`autonomous/llm_gateway.py`
- depends_on: `NGA-WS28-001`
- deliverables:
  - 代码文件：`autonomous/llm_gateway.py`
  - 可选新增：`autonomous/prompt_slices.py`（若需独立结构定义）
  - 测试文件：`tests/test_llm_gateway_prompt_slice_ws28_002.py`
  - 报告产物：`scratch/reports/ws28_002_prompt_slice_compose.json`
- acceptance:
  - 实现 `resolve()`（逻辑优先级裁剪）与 `serialize_for_cache()`（物理拼接）双阶段。
  - 生成并暴露 `prefix_hash`、`tail_hash` 与 `PromptComposeDecision`。
  - Path-A 请求不得拼接执行态高动态切片（保持快路径轻量）。
  - 执行：`.venv/bin/pytest -q tests/test_llm_gateway_prompt_slice_ws28_002.py`
  - 产物文件存在且 `passed=true`。
- rollback:
  - 保留 `PromptSlice` 数据结构，组合逻辑退回现有三段式 envelope；关闭新字段强校验。
  - 回滚后必须保持 `prefix_hash` 观测可用，避免可观测性退化。
- status: `done`（2026-02-26，已通过 `tests/test_llm_gateway_prompt_slice_ws28_002.py`）

### NGA-WS28-003 建立 Prompt ACL 与 API 写入门禁
- type: `hardening`
- priority: `P0`
- phase: `M13`
- owner_role: `security`
- scope: `/system/prompts/*` 写入控制、审批票据校验、S0/S1/S2 分级落地
- inputs: `doc/task/24-ws-prompt-routing-injection-policy.md` §6.2/§6.3/§10.6；`apiserver/api_server.py`；`system/config.py`
- depends_on: `NGA-WS28-001`
- deliverables:
  - 代码文件：`apiserver/api_server.py`
  - 代码文件：`system/config.py`
  - 配置文件：`system/prompts/prompt_acl.spec`
  - 测试文件：`tests/test_prompt_acl_api_guard_ws28_003.py`
  - 报告产物：`scratch/reports/ws28_003_prompt_acl_guard.json`
- acceptance:
  - `S0_LOCKED` 文件写入被拒绝（无例外）。
  - `S1_CONTROLLED` 文件需携带审批票据（缺失时拒绝）。
  - `S2_FLEXIBLE`（后续放开时）可按策略放行，且审计字段完整。
  - 执行：`.venv/bin/pytest -q tests/test_prompt_acl_api_guard_ws28_003.py`
  - 产物文件存在且 `passed=true`。
- rollback:
  - 失败时先切回 `enforcement_mode=shadow`，仅审计不拦截。
  - 保留 ACL 解析与日志链路，避免完全回退到“无治理”状态。
- status: `done`（2026-02-26，已通过 `tests/test_prompt_acl_api_guard_ws28_003.py`）

### NGA-WS28-004 对齐 Analyzer 与 Core 的路由注入策略
- type: `refactor`
- priority: `P0`
- phase: `M13`
- owner_role: `backend`
- scope: 背景分析器 prompt 选择策略与 Core 路由字段一致化
- inputs: `doc/task/24-ws-prompt-routing-injection-policy.md` §7/§10.6；`system/background_analyzer.py`
- depends_on: `NGA-WS28-001;NGA-WS28-002`
- deliverables:
  - 代码文件：`system/background_analyzer.py`
  - 测试文件：`tests/test_background_analyzer_prompt_parity_ws28_004.py`
  - 报告产物：`scratch/reports/ws28_004_analyzer_parity.json`
- acceptance:
  - Analyzer 侧使用同源 `prompt_profile/injection_mode` 判定，不再硬编码固定模板。
  - Analyzer 与 Core 在同类输入下的切片选择结果可比对（字段一致）。
  - 执行：`.venv/bin/pytest -q tests/test_background_analyzer_prompt_parity_ws28_004.py`
  - 产物文件存在且 `passed=true`。
- rollback:
  - 保留新字段透传，模板选择临时退回 legacy 分支。
  - 记录不一致样本并落盘，作为下一轮修复输入。
- status: `done`（2026-02-26，已通过 `tests/test_background_analyzer_prompt_parity_ws28_004.py`）

### NGA-WS28-005 固化 DNA `.spec` 单源门禁与受控更新链
- type: `hardening`
- priority: `P0`
- phase: `M13`
- owner_role: `qa`
- scope: Manifest 更新脚本与 gate 校验脚本单源一致性
- inputs: `doc/task/24-ws-prompt-routing-injection-policy.md` §4.1/§10.6；现有 ws23 脚本与测试
- depends_on: `NGA-WS28-003`
- deliverables:
  - 代码文件：`scripts/update_immutable_dna_manifest_ws23_003.py`
  - 代码文件：`scripts/validate_immutable_dna_gate_ws23_003.py`
  - 测试文件：`tests/test_update_immutable_dna_manifest_ws23_003.py`
  - 测试文件：`tests/test_ws23_003_immutable_dna_gate.py`
  - 报告产物：`scratch/reports/ws28_005_dna_spec_gate.json`
- acceptance:
  - 校验脚本明确拒绝 `.json` 作为并行事实源。
  - 受控更新链要求 `approval_ticket`，并在产物中记录 `change_reason`（若未传则拒绝 strict 模式）。
  - 执行：`.venv/bin/pytest -q tests/test_update_immutable_dna_manifest_ws23_003.py tests/test_ws23_003_immutable_dna_gate.py`
  - 产物文件存在且 `passed=true`。
- rollback:
  - 保留 `.spec` 单源判断，临时放宽新增审计字段为 warning（不阻断）。
  - 回滚记录需写入 runbook，说明放宽窗口与恢复计划。
- status: `done`（2026-02-26，已通过 DNA `.spec` gate 相关测试）

### NGA-WS28-006 建立 P0 全链回归脚本与统一证据输出
- type: `qa`
- priority: `P0`
- phase: `M13`
- owner_role: `qa`
- scope: 聚合 WS28-001~005 回归，形成一次命令可复验的收口链
- inputs: `doc/task/24-ws-prompt-routing-injection-policy.md` §11；前置 WS28-001~005 产物约定
- depends_on: `NGA-WS28-001;NGA-WS28-002;NGA-WS28-003;NGA-WS28-004;NGA-WS28-005`
- deliverables:
  - 脚本文件：`scripts/release_closure_prompt_routing_ws28_006.py`
  - 测试文件：`tests/test_release_closure_prompt_routing_ws28_006.py`
  - 报告产物：`scratch/reports/release_closure_prompt_routing_ws28_006.json`
- acceptance:
  - 单命令执行完成 P0 关键链路检查并输出 `passed/failed_groups`。
  - 至少覆盖：Router 字段、Slice 组合、ACL 拦截、Analyzer 对齐、DNA gate 五组检查。
  - 执行：`.venv/bin/python scripts/release_closure_prompt_routing_ws28_006.py`
  - 产物文件存在且当 `passed=true` 时允许进入后续排期。
- rollback:
  - 若脚本链不稳定，可拆回分项脚本执行，但必须继续输出统一汇总 JSON。
  - 不允许回退为“人工口头确认”。
- status: `done`（2026-02-26，`scripts/release_closure_prompt_routing_ws28_006.py --strict` 通过）

### 10.7.1 增量状态同步（截至 2026-02-26）

以下增量任务在 P0 基线之后已完成，并已纳入回归链：

1. `NGA-WS28-007` Outer/Core 三路径准入门（Path-A/B/C）  
status: `done`；锚点：`c43b60c`；回归：`tests/test_chat_route_outer_core_ws28_007.py`
2. `NGA-WS28-008` Path-C Contract-only 输入（ExecutionContractInput）  
status: `done`；锚点：`c1ac6af`；回归：`tests/test_chat_core_contract_input_ws28_008.py`
3. `NGA-WS28-009` Path-B 澄清预算与自动升级 Core  
status: `done`；锚点：`b68349a`；回归：`tests/test_run_ws28_path_b_clarify_budget_ws28_009.py`
4. `NGA-WS28-010` Outer/Core 会话桥接（`execution_session_id` 指向 Core 会话）  
status: `done`；锚点：`ff30de5`；回归：`tests/test_run_ws28_outer_core_session_bridge_ws28_010.py`
5. `NGA-WS28-011` 路由桥接可观测性（`/v1/chat/route_bridge/{session_id}` + Debug UI）  
status: `done`；锚点：`c2c5539`、`26b94ff`；回归：`tests/test_chat_route_bridge_snapshot_ws28_011.py`
6. `NGA-WS28-012` Route-Quality 运行态治理闭环（warning/critical 强制策略 + guard 事件入总线）  
status: `done`；锚点：`efda0bc`、`bbaed69`；回归：`tests/test_chat_route_quality_guard_ws28_012.py`

### 10.8 P0 执行顺序（建议）

1. 顺序链：`WS28-001 -> WS28-002 -> WS28-003 -> WS28-004 -> WS28-005 -> WS28-006`。
2. 并行建议：
- `WS28-004` 可在 `WS28-002` 稳定后与 `WS28-003` 并行推进（不同主文件）。
- `WS28-005` 依赖 `WS28-003` 的 ACL 审计字段约定，建议串行。
3. 发布门禁：
- `WS28-006` 通过前，不应将 Prompt ACL enforcement 从 `shadow` 切换到 `block`。
- 当前状态（2026-02-26）：`WS28-006` 已通过，`system/prompts/prompt_acl.spec` 已切为 `enforcement_mode=block`；保留回退 `shadow` 作为应急预案。

---

## 11. 验收标准（讨论版）

1. 同一任务多轮执行中，注入切片来源可完整追溯（100%）。
2. `write_intent` 任务安全策略覆盖率 100%。
3. 恢复切片 TTL 策略生效：`rounds_soft<=3` 且同根因未收敛时允许续租，不得中途硬截断。
4. 多职能并行场景下，接口字段不一致失败率较当前基线下降 60%+。
5. 专家子代理路由命中率：标准意图集首次命中准确率 >= 85%。
6. 权限降级可靠性：只读子代理注入时写权限工具暴露率 = 0%。
7. 聊天快路径性能：`hi` 类请求 P95 `<300ms`（不触发 Core/工具链）。
8. 并发稳定性：动态并发场景下无持续排队放大和无界 agent 膨胀。
9. 缓存稳定性：`P0_STATIC_PREFIX` 命中率在同任务多轮对话中不低于 80%。
10. 交互效率：Path-B 到 Path-C 的升级中位追问次数 <= 1（高风险写操作除外）。
11. 恢复连续性：同根因修复链路中，`L4` 上下文不可在未收敛前被硬过期截断。

---

## 12. 设计决议（本轮闭环）

1. `L2_ROLE` 与技能覆盖关系
- 结论：不允许覆盖 `L3`。
- 规则：`L3_TOOL_POLICY` 拥有物理最高解释权。

2. 记忆回注层级
- 结论：设为 `L1.5_EPISODIC_MEMORY`。
- 规则：绑定任务生命周期，不属于临时补救层 `L4`。

3. Prompt 存储与 DNA 语义
- 结论：DNA 单源统一为 `.spec`，并保留当前 `.txt` 核心 prompt 兼容。
- 规则：在未完成 registry 迁移前，不强制切换到 Frontmatter；后续专家 prompt 可逐步引入 `Markdown + YAML Frontmatter`。

4. 远程环境灰度策略
- 结论：已完成 `shadow -> block` 切换（当前为 `block`）；若误拦截升高，允许临时回退 `shadow` 并要求附变更审计票据。

5. 并发控制策略
- 结论：不设固定 hard cap。
- 规则：按 `machine + task + time` 三因子动态决定并发；预算作为观测项。

6. Prompt 可修改边界
- 结论：当前阶段 `S2_FLEXIBLE=0`，核心 4 prompt 全部按 `S1_CONTROLLED` 执行。
- 规则：任何核心 prompt 变更必须经过审批票据、manifest 同步、gate 通过。

---

## 13. 参考资料

1. Piebald 仓库首页：  
<https://github.com/Piebald-AI/claude-code-system-prompts>
2. 主系统提示（逆向）：  
<https://raw.githubusercontent.com/Piebald-AI/claude-code-system-prompts/main/system-prompts/system-prompt-main-system-prompt.md>
3. 工具使用策略（逆向）：  
<https://raw.githubusercontent.com/Piebald-AI/claude-code-system-prompts/main/system-prompts/system-prompt-tool-usage-policy.md>
4. Explore 子代理提示（逆向）：  
<https://raw.githubusercontent.com/Piebald-AI/claude-code-system-prompts/main/system-prompts/agent-prompt-explore.md>
5. Plan 子代理提示（逆向）：  
<https://raw.githubusercontent.com/Piebald-AI/claude-code-system-prompts/main/system-prompts/agent-prompt-plan-mode-enhanced.md>
6. Task 工具提示（逆向）：  
<https://raw.githubusercontent.com/Piebald-AI/claude-code-system-prompts/main/system-prompts/agent-prompt-task-tool.md>
7. 本项目锚点：
- `system/immutable_dna.py`
- `autonomous/llm_gateway.py`
- `autonomous/router_engine.py`
- `autonomous/working_memory_manager.py`
- `apiserver/agentic_tool_loop.py`
- `system/config.py`
