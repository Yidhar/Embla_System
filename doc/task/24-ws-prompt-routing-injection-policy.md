# WS24x 设计讨论稿：Prompt 路由注入与多职能 Agent 注入时机

文档状态：讨论稿（Design Draft）  
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
- 基于 `immutable_dna_manifest.json` 的 `injection_order` 做顺序装配与 hash 校验。

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
- 执行：Outer 先澄清并补全 Contract（目标、范围、副作用、验收），再决定是否升级 Core。

3. `Path-C: Core Execution`
- 适用：写操作、跨模块编排、多代理协同、需要回滚/重试治理。
- 执行：进入 Core 做路由、门禁、契约校验、权限裁剪与调度。

升级到 Core 的最小条件（建议）：

1. `write_intent=true` 或存在外部副作用。
2. 需要多阶段编排（单轮只读无法完成）。
3. 需要拉起专家子代理并行处理。

---

## 6. Prompt 分层、优先级与覆盖规则

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
2. 拉起时必须声明 `delegation_intent`、`target_agent_type`、`contract_checksum`。
3. 若目标代理为 `Explore` 或 `Security_Review`：
- LLM Gateway 组装时必须剔除写工具 schema（如 `os_bash` 写命令、`edit_file`、`workspace_txn_apply`）。
- Prompt 层追加强只读约束（如 `CRITICAL: READ-ONLY MODE`）。

### 7.3 并行多职能契约屏障（Frontend/Backend/Ops）

1. 并行前先注入共享契约片段（字段名、版本、错误码）。
2. 生成并广播 `contract_checksum` 到所有子任务元数据。
3. 未通过契约一致性时，禁止并行写入，只允许只读探索。

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
class PromptSlice:
    slice_id: str
    layer: str                   # L0/L1/L1.5/L2/L3/L4
    owner: str                   # system/router/role/tool/memory/recovery
    content_ref: str             # prompt repo path or inline key
    source_hash: str
    inject_when: dict[str, Any]  # phase/risk/evidence/failure conditions
    drop_when: dict[str, Any]
    ttl_rounds: int
    priority: int
    conflicts_with: list[str]
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
    contract_checksum: str       # 本轮绑定契约
```

---

## 9. 组合算法（建议）

1. 收集候选切片。
- DNA、任务、角色、工具策略、记忆回注、恢复策略。

2. 按触发器筛选。
- 仅保留满足 `inject_when` 的切片。

3. 冲突消解。
- 按层级优先级和 `conflicts_with` 规则淘汰。

4. 生命周期处理。
- 先移除已过 TTL 或满足 `drop_when` 的切片。

5. 预算裁剪。
- 固定保留 `L0/L3`。
- 优先裁剪 `L4`，再裁剪低优先级扩展段。

6. 产出审计事件。
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

3. 在 `apiserver/agentic_tool_loop.py`：
- 将 episodic reinjection 迁移为标准 `L1.5` 切片（任务生命周期绑定）

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

---

## 11. 验收标准（讨论版）

1. 同一任务多轮执行中，注入切片来源可完整追溯（100%）。
2. `write_intent` 任务安全策略覆盖率 100%。
3. 恢复切片平均生存轮次 <= 3（避免长期污染）。
4. 多职能并行场景下，接口字段不一致失败率较当前基线下降 60%+。
5. 专家子代理路由命中率：标准意图集首次命中准确率 >= 85%。
6. 权限降级可靠性：只读子代理注入时写权限工具暴露率 = 0%。
7. 聊天快路径性能：`hi` 类请求 P95 `<300ms`（不触发 Core/工具链）。
8. 并发稳定性：动态并发场景下无持续排队放大和无界 agent 膨胀。

---

## 12. 设计决议（本轮闭环）

1. `L2_ROLE` 与技能覆盖关系
- 结论：不允许覆盖 `L3`。
- 规则：`L3_TOOL_POLICY` 拥有物理最高解释权。

2. 记忆回注层级
- 结论：设为 `L1.5_EPISODIC_MEMORY`。
- 规则：绑定任务生命周期，不属于临时补救层 `L4`。

3. Prompt 存储位置
- 结论：`Markdown + YAML Frontmatter`。
- 规则：便于业务编辑与热重载，不写死在 Python 常量。

4. 远程环境灰度策略
- 结论：先 `enforcement_mode=shadow`，稳定后再切 `block`。

5. 并发控制策略
- 结论：不设固定 hard cap。
- 规则：按 `machine + task + time` 三因子动态决定并发；预算作为观测项。

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
