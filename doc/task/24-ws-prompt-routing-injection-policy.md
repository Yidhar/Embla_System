# WS24x 设计讨论稿：Prompt 路由注入与多职能 Agent 注入时机

文档状态：讨论稿（Design Draft）  
最后更新：2026-02-26  
适用范围：`SystemAgent / Router / LLM Gateway / Agentic Loop`  

---

## 1. 背景与问题

当前项目已具备若干 prompt 相关能力，但“何时注入、注入什么、注入多久、谁来注入”仍缺统一策略，导致以下风险：

1. 注入时机不统一：同一请求在不同链路（`/chat` vs `/chat/stream` vs `agentic_loop`）注入行为不一致。
2. 注入粒度偏粗：system prompt 常按“整段拼接”处理，缺少按阶段和风险的细粒度装配。
3. 生命周期不清：临时补救 prompt 未显式 TTL，容易污染后续轮次。
4. 多职能并发盲写：前后端/Ops 子代理并行时缺注入契约屏障，字段和验收口径容易错位。
5. 可审计性不足：缺少“本轮最终 prompt 由哪些片段组成”的可回放证据。

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

设计启发：

1. Prompt 不是单一字符串，而是“角色化、阶段化、工具化”的片段集合。
2. 子代理 prompt 必须角色隔离，且具备硬限制（只读/禁止写）。
3. 工具策略应作为独立层，而非掺杂在对话风格中。

---

## 4. 目标态设计原则（To-Be）

1. 事件驱动注入：按阶段与风险触发，不按“固定模板全量拼接”。
2. 最小必要注入：默认最小，缺证据再补充。
3. 生命周期可控：每个片段有 TTL、drop 条件、冲突策略。
4. 可审计可回放：每轮输出注入快照（含来源、版本、hash）。
5. 安全不可被覆盖：安全层优先级高于技能层与任务层。

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

## 6. Prompt 片段分层与优先级

建议引入五层（与现有 `PromptEnvelope` 对齐）：

1. `L0_DNA`（不可变）
- 来源：`ImmutableDNALoader.inject()`
- 优先级最高，不可覆盖。

2. `L1_TASK_BASE`
- 任务目标、验收标准、输出格式。

3. `L2_ROLE`
- `sys_admin / developer / researcher` 专用约束。
- 由 `RouterDecision.selected_role` 触发。

4. `L3_TOOL_POLICY`
- 与本轮工具/执行模式直接相关的规则（并行、参数完整性、只读模式等）。

5. `L4_RECOVERY`
- 失败后短期补救策略，必须 TTL 限制。

优先级：`L0 > L3 > L2 > L1 > L4`  
说明：`L4` 为临时策略，优先级低于安全和工具策略，避免“补救 prompt”破坏安全基线。

---

## 7. 多职能 Agent 注入时机（关键）

### 7.1 主控 Agent（Router/SystemAgent）

1. 路由前：只注入 `L0 + 极简任务上下文`，避免角色偏置影响路由。
2. 路由后：注入 `L2_ROLE`。
3. 进入执行前：按工具集合注入 `L3_TOOL_POLICY`（JIT 注入）。

### 7.2 子代理（Task/SubAgent）

1. spawn 时只下发最小上下文包：
- task objective
- contract/schema
- target files / boundaries
- acceptance checks

2. 不继承父代理完整历史（默认禁用），仅继承可审计摘要引用。

### 7.3 并行多职能（Frontend/Backend/Ops）

并行前必须经过“契约注入屏障”：

1. 先注入并确认共享契约片段（字段名、版本、错误码）。
2. 生成 `contract_checksum` 写入子任务元数据。
3. 未通过契约一致性时禁止并行写入（只允许只读探索）。

---

## 8. 建议数据结构（新增）

```python
@dataclass(frozen=True)
class PromptSlice:
    slice_id: str
    layer: str                   # L0/L1/L2/L3/L4
    owner: str                   # system/router/role/tool/recovery
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
```

---

## 9. 组合算法（建议）

1. 收集候选切片：
- DNA、任务、角色、工具策略、记忆回注、恢复策略

2. 按触发器筛选：
- 仅保留满足 `inject_when` 的切片

3. 冲突消解：
- 按层级优先级和 `conflicts_with` 规则淘汰

4. 生命周期处理：
- 先移除已过 TTL 或满足 `drop_when` 的切片

5. 预算裁剪：
- 保留 `L0/L3`，优先裁剪 `L4` 再裁剪低优先级 `L1/L2` 扩展段

6. 产出审计事件：
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

3. 在 `apiserver/agentic_tool_loop.py`：
- 将 episodic reinjection 改为标准 `L4` 临时切片（带 TTL）

### 10.2 P1（可观测）

1. 在 `logs/autonomous/events.jsonl` 写入注入决策事件。
2. 在 `scripts/export_slo_snapshot.py` 增加注入质量指标：
- `prompt_slice_count_by_layer`
- `injection_trigger_distribution`
- `recovery_slice_hit_rate`
- `prompt_conflict_drop_count`

### 10.3 P2（多代理并行保障）

1. 子代理 spawn 前强制 `contract prompt slice` 对齐。
2. 并行写任务必须带 `contract_checksum`，否则降级为只读探索。

---

## 11. 验收标准（讨论版）

1. 同一任务多轮执行中，注入切片来源可完整追溯（100%）。
2. `write_intent` 任务安全策略覆盖率 100%。
3. 恢复切片平均生存轮次 <= 3（避免长期污染）。
4. 多职能并行场景下，接口字段不一致失败率较当前基线下降 60%+。

---

## 12. 开放讨论问题

1. `L2_ROLE` 与技能 prompt 的覆盖关系是否允许“局部覆盖”？
2. 记忆回注是否应默认放在 `L4`，还是拆分为 `L2.5`（角色相关长期记忆）？
3. `PromptSlice` 存储位置是配置文件（YAML）还是代码常量（Python）？
4. 远程测试环境中是否先启用“只审计不拦截”模式进行灰度？

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
