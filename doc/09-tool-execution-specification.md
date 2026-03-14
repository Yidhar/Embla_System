---
**文档类型**：As-Is + Target-Aligned（混合文档）
**实施状态**：Phase 3 桥接主链已落地 + Phase 3 Full 收口
**最后更新**：2026-03-10
**执行策略版本**：v3 (Sub-Agent Runtime + NativeExecutionBridge 主路径)
**当前实现**：agentic_tool_loop + SystemAgent + subagent_runtime + execution_bridge + mcp_manager
**目标态参考**：`doc/00-omni-operator-architecture.md` + `doc/task/25-subagent-development-fabric-status-matrix.md`
---

# 09 工具调用与任务执行规范（Embla System 对齐版）

文档状态：开发预备（As-Is + Target-Aligned）
最后更新：2026-03-10

## 1. 目标

统一 Embla System 工具调用治理，确保"模型输出 -> 工具执行 -> 结果回流"全过程可校验、可审计、可收敛。

适用范围：

- `agents/tool_loop.py`
- `apiserver/native_tools.py`
- `system/native_executor.py`
- `mcpserver/mcp_manager.py`
- `agents/pipeline.py`（自治流程中的工具与命令治理）

## 2. 执行总原则

1. 仅接受结构化工具调用（禁止 legacy 文本协议）。
2. 优先本地可控执行，外部调用走受控网关。
3. 所有高风险动作必须可追踪、可回放、可拒绝。
4. 结果必须回流到统一事件通道（SSE/事件日志）。
5. **执行主链优先策略**（v3, 2026-02-27）：编码任务优先进入 `SystemAgent -> Sub-Agent Runtime -> NativeExecutionBridge`，legacy CLI 仅历史兼容参考。

## 3. 当前执行链路（As-Is）

1. LLM 产出结构化 `tool_calls` 或子任务契约（`task contract`）。
2. 交互链路由 `agents/tool_loop.py` 校验并分类：`native_call` / `mcp_call`。
3. 自治链路由 `SystemAgent` 决策 `runtime_mode=subagent` 后进入：
   - `subagent_runtime`（依赖调度、契约校验、事件编排）
   - `execution_bridge`（补丁意图执行、角色门禁、审计回执）
4. 执行层：
   - Embla 原生工具路由：`native_tools -> ExecutionBackend`
   - 默认可写执行后端：`BoxLiteExecutionBackend`（Dev / Review / `core_execution` 会话）
   - 宿主 fallback：`NativeExecutionBackend`（无 session、host-only system 能力、BoxLite 不可用且策略允许时）
   - MCP：`mcp_manager`（本地注册优先，外部 mcporter 兜底）
5. 返回层：输出 `tool_results` / `tool_stage` / `SubTaskExecutionBridgeReceipt` 到前端与事件通道。

### 3.1 Sub-Agent Runtime + NativeExecutionBridge 路由策略（当前）

**触发条件**：
- 检测到编码意图（代码生成、重构、修复）
- 用户明确请求编码任务
- 文件写入操作（`write_file`、`git_checkout_file`）

**路由规则**：
1. **强制执行桥优先**：
   - 编码任务优先进入 `subagent_runtime + execution_bridge` 路径。
   - 子任务写入必须提供 `patch_intents` / `patches`，缺失时拒绝执行。
   - `role_executor_policy` 与 `role_executor_semantic_guard.spec` 生效后才允许落盘。

2. **治理字段注入**：
   - 写入执行回执中统一输出 `execution_bridge_governance_*` 字段。
   - 拒绝原因结构化为 `reason_code/category/severity` 并写入 Runtime/Incident 聚合。

3. **降级策略（切换后）**：
   - legacy CLI 回退已退役，fail-open 不再切回外部 CLI。
   - fail-open 推荐场景统一走 `SubAgentRuntimeFailOpenBlocked + ReleaseGateRejected` 并进入治理告警。
     其中 `SubAgentRuntime*` 已归档为 `archived_legacy` 历史事件命名空间。

**实现位置**：
- `agents/pipeline.py`：主循环路由与 `runtime_mode` 决策
- `agents/runtime/mini_loop.py`：子任务调度与契约门禁
- `agents/tool_loop.py`：内生执行桥与治理回执
- `policy/role_executor_semantic_guard.spec`：语义级门禁策略
- `config/autonomous_runtime.yaml`：`disable_legacy_cli_fallback` 等运行策略

### 3.2 BoxLite-first 执行后端（Target Canonical）

当前默认链已统一为 `host control plane + BoxLite execution plane + host worktree lifecycle`：

- 宿主创建每任务 `git worktree`
- 宿主以稳定 `box_name` 创建/复用 BoxLite box，并记录运行时 `box_id`；随后将 worktree 以 `rw` 挂载到 box 内 `/workspace`
- 宿主额外将主 checkout 以 `ro` 挂载到相同绝对路径，并将主仓库 `.venv` 以 `ro` 挂载到 `/workspace/.venv`，用于 worktree `.git` 解析与 `.venv/bin/python` 复用
- Dev / Review 的 workspace 读写、搜索、命令执行、测试、lint、事务写入通过统一 `ExecutionBackend` 路由；`query_docs`、`file_ast_skeleton`、`file_ast_chunk_read` 也随执行后端进入 box 内 guest helper 路径
- 宿主仅保留 `artifact_reader` / `killswitch_plan` 等系统级 host-bridge 能力，以及 `audit_child_workspace`、`promote_child_workspace`、`teardown_child_workspace`

因此，BoxLite 在 Embla 中承担的是**Embla 默认可写执行后端**角色，而不是替代 worktree lifecycle。`SandboxContext.default()` 保留 `native` 仅用于无 session / 测试 harness 的宿主 fallback。

配套重构原则：

1. `native_tools` 变为 backend router，而不是唯一执行器。
2. `SandboxContext` 成为 session 的单一事实源。
3. `apply_workspace_path_overrides` 仅保留为 native fallback 兼容层。
4. `execution_receipt` 对 `awaiting_workspace_promotion` 的语义保持不变。
5. BoxLite runtime 元数据采用 `box_name`（稳定 session 命名）+ `box_id`（运行时实例 ID）双字段口径。

详细设计见 `doc/15-boxlite-first-execution-sandbox-architecture.md`。

## 4. Tool Contract（统一契约）

目标态字段（来源：Embla System 蓝图）：

- `tool_name`
- `input_schema_version`
- `validated_args`
- `risk_level`（`read_only` / `write_repo` / `deploy` / `secrets` / `self_modify`）
- `timeout_ms`
- `idempotency_key`
- `caller_role`
- `trace_id`

### 4.1 当前落地情况

- 已落地：`tool_name`、参数结构校验、执行结果状态。
- 部分落地：超时控制、幂等能力（自治流程中较完整）。
- 待补齐：`risk_level`、`trace_id`、`input_schema_version` 在所有调用面强制化。

## 5. 风险分级与门禁

### 5.1 风险等级定义

- `read_only`：只读查询，不修改代码/环境。
- `write_repo`：修改仓库文件或 Git 状态。
- `deploy`：部署、发布、环境变更。
- `secrets`：密钥、凭据、敏感配置。

### 5.2 最低门禁要求

- `read_only`：自动执行，可记录审计。
- `write_repo`：需最少校验（lint/test 或等效）。
- `deploy`：需 canary 与回滚策略。
- `secrets`：必须短期凭据 + 严格审计 + 禁止明文回显。

## 6. 安全执行约束（当前实现）

Native 路径（`native_executor`）已具备：

- 项目根目录边界限制
- 危险 token 拦截
- 路径穿越拦截
- 超时/输出控制

MCP 路径（`mcp_manager`）已具备：

- 服务名与工具名规范化
- 本地注册优先
- 外部调用的受控降级与结构化错误回执

## 7. 失败与降级策略

### 7.1 工具调用失败

1. 返回结构化错误状态，不吞错。
2. 将错误摘要进入 `tool_results`。
3. 按策略决定是否重试或终止当前轮次。

### 7.2 Legacy CLI 兼容入口（已退役）

自治流程已切到 subagent-only，不再执行 legacy CLI 兼容降级：

- fail-open 不再触发 CLI 回退，而是产生结构化拒绝与预算告警。
- `verification_fallback` 配置块已从当前主配置移除；不再驱动任何运行时降级。

## 8. 回执与审计模板

建议输出结构：

```text
【执行状态】
- 调用类型：native/mcp
- 风险等级：read_only/write_repo/deploy/secrets
- 是否落盘：是/否

【执行证据】
- tool_name: ...
- trace_id: ...
- idempotency_key: ...
- 结果：success/error

【风险与后续】
- 风险项：...
- 下一步：...
```

### 8.1 子 Agent `completed` payload 契约

多 Agent 运行时对 `report_to_parent(type="completed")` 采用角色化强校验：

- `Dev` 必须附带 `verification_report`
- `Review` 必须附带 `review_result`

```json
{
  "type": "completed",
  "content": "summary",
  "verification_report": {
    "tests": {"passed": 3, "failed": 0, "errors": 0, "attempts": 1, "summary": "targeted tests passed"},
    "lint": {"status": "passed", "errors": 0, "summary": "lint clean"},
    "diff_review": {"complete": true, "summary": "task fully covered", "missing_items": []},
    "changed_files": ["path/to/file.py"],
    "risks": []
  }
}
```

```json
{
  "type": "completed",
  "content": "review summary",
  "review_result": {
    "verdict": "approve",
    "requirement_alignment": [{"requirement": "original task", "status": "passed", "details": "implemented"}],
    "code_quality": {"status": "passed", "summary": "no blocking issues"},
    "regression_risk": {"level": "low", "summary": "callers unaffected"},
    "test_coverage": {"status": "passed", "summary": "core path covered", "missing_cases": []},
    "issues": [],
    "suggestions": [],
    "summary": "approved"
  }
}
```

### 8.2 Review 生命周期事件协议

`agents/pipeline.py` 当前对 Review gate 的 canonical 事件语义如下：

| 阶段 | 事件 | 关键字段 | 说明 |
|------|------|----------|------|
| Review 启动 | `review_spawned` | `expert_id`, `review_agent_id`, `review_cycle` | Expert 为本轮已完成的 Dev 产出创建独立 Review |
| Review 完成 | `review_result` | `result.verdict` | 每次 Review 完成都会发出，包括中间态 `request_changes` / `reject` |
| 要求返修 | `review_rework_requested` | `review_cycle`, `issues`, `review_agent_id` | `request_changes` 后，Expert 恢复原 Dev |
| Dev 返修 | `dev_review_resume_start` / `dev_review_resume_event` / `dev_review_resume_end` | `review_cycle`, `agent_id` | 原 Dev 返修并重新自检 |
| 驳回重做 | `review_reject_respawn` | `task_ids`, `respawn_dev_count`, `reject_respawn_count` | `reject` 且可恢复时，Expert 重新 spawn fresh Dev |
| Dev 回合耗尽恢复 | `dev_loop_max_rounds_resume` | `task_id`, `agent_id`, `resume_attempt`, `findings_summary` | Dev 因 `child_loop_max_rounds_reached` 中断时，Expert 自动恢复原 Dev |
| Dev 回合耗尽重拉 | `dev_loop_max_rounds_respawn` | `task_id`, `agent_id`, `respawn_attempt`, `replacement_agent_ids`, `findings_summary` | 原 Dev 恢复仍失败时，Expert 自动 spawn fresh Dev |
| 阻断上报 | `expert_blocked` | `reason`, `review_cycle`, `result` | `reject` 不可恢复、预算耗尽、无任务可重跑或 respawn 失败/未完成 |
| Expert 汇总 | `expert_report` | `reports[]`, `status` | Expert 给 Core 的聚合报告 |
| 最终回执 | `execution_receipt` | `stop_reason`, `agent_state.review_count`, `agent_state.review_verdicts`, `agent_state.scheduler.parallel_limit`, `agent_state.scheduler.peak_parallelism`, `agent_state.scheduler.layers.dev.peak_parallelism`, `agent_state.heartbeat_summary`, `agent_state.experts_blocked`, `agent_state.blocked_expert_reasons` | 多 Agent gate 的最终结构化结果、分层调度摘要与心跳监管收口 |

### 8.2 心跳监管与自动升级（运行时 canonical）

#### 8.2.0.1 子工具与阈值

- 子 Agent 通过 `publish_task_heartbeat(task_id, status, message, stage, ttl_seconds, progress, details)` 主动发布任务级 heartbeat。
- stale 等级口径：
  - `warning`：`seconds_since_heartbeat > ttl_seconds`
  - `critical`：`seconds_since_heartbeat > max(ttl_seconds * 2, ttl_seconds + 30)`
  - `blocked`：`seconds_since_heartbeat > critical_threshold + 60`
- `poll_child_status`、`/v1/chat/route_session_state/{session_id}` 与 `execution_receipt.agent_state.heartbeat_summary` 使用同一套聚合字段。

#### 8.2.0.2 Expert / Core 升级策略

- `warning`：Expert 先向原 Dev 发送提醒，要求刷新 heartbeat。
- `critical`：Expert 注入更强的恢复指令，要求 Dev 立即汇报当前 stage / 阻塞原因。
- `blocked`：Expert 优先对对应 task `spawn` fresh Dev 做 `heartbeat_respawn`。
- respawn 预算耗尽：Expert 发出 `expert_blocked(reason=task_heartbeat_blocked_respawn_exhausted)`，Core 将其汇总进 `execution_receipt`。

#### 8.2.0.3 Dev mini-loop 回合耗尽自动恢复

- 当 Dev 以 `blocked_reason=child_loop_max_rounds_reached` 结束时，Expert 不直接收口为 blocked。
- 第一次命中：Expert 自动 `resume_child_agent` 原 Dev，并附带压缩后的中间发现，事件为 `dev_loop_max_rounds_resume`。
- 若恢复后的原 Dev 再次命中回合上限：Expert 自动 `spawn` fresh Dev，并附带同样的压缩中间发现，事件为 `dev_loop_max_rounds_respawn`。
- 只有当 `resume` 与 `respawn` 的预算均耗尽或恢复动作失败时，才继续按 blocked / `completion_not_submitted` / `review_missing` 等最终收口路径处理。

### 8.2.1 `destroy_child_agent` 资源清理结果口径

当父节点调用 `destroy_child_agent` 时，运行时返回事实型清理结果：

```json
{
  "agent_id": "agent-xxx",
  "status": "destroyed",
  "box_cleanup_attempted": true,
  "box_cleanup_success": true,
  "box_cleanup_error": "",
  "workspace_cleanup_attempted": false,
  "workspace_cleanup_success": true,
  "workspace_cleanup_error": ""
}
```

约束：

- `box_cleanup_*` 仅描述 BoxLite 执行沙箱释放事实。
- `workspace_cleanup_*` 仅描述 owner worktree 的宿主侧清理事实。
- 这些字段属于父工具结果，不写入 `execution_receipt`。

### 8.3 Verdict 到 stop_reason 的归一口径

| 最终情况 | `execution_receipt.stop_reason` | 语义 |
|----------|--------------------------------|------|
| 全部完成且 Review 通过 | `submitted_completion` | Dev 已完成，自检通过，最终 Review 全部 `approve` |
| Dev 未提交完成态 | `completion_not_submitted` | 至少一个 Dev 没有合法 `completed` 报告 |
| Review 最终 `reject` | `review_rejected` | 最终审查未通过，或被升级为 blocked |
| Review 未完成 | `review_missing` | 预期应有 Review，但没有收到最终生效结论 |
| Review 仍停留在返修要求 | `review_requested_changes` | 返修轮次耗尽或任务在返修态结束 |
| 心跳阻断且 respawn 耗尽 | `task_heartbeat_blocked_respawn_exhausted` | Dev 心跳超过阻断阈值，Expert 自动重拉新 Dev 仍未恢复 |

- `review_result` 事件会保留**每一轮** Review 的输出，便于前端/审计复盘。
- `execution_receipt.agent_state.review_verdicts` 与最终 `review_results` 聚合只记录**每个 Expert 最终生效的 verdict**，不把中间态 `request_changes` 或可恢复 `reject` 当作最终通过结果。
- `execution_receipt.agent_state.scheduler` 仅保留编排层摘要；顶层默认对应 Expert 层，当前至少包含 `layer / parallel_limit / peak_parallelism`，并可通过 `layers.expert` / `layers.dev` 读取分层并发度。
- `execution_receipt.agent_state.heartbeat_summary` 记录本轮心跳监管与自动恢复动作计数（如 `warning_count` / `critical_count` / `blocked_count` / `respawn_count` / `loop_resume_count` / `loop_respawn_count` / `expert_blocked_reasons`）。
- 当最终 verdict 为 `reject` 时，Expert 对 Core 的报告应以前缀 `[BLOCKED] ...` 标记阻断原因。

## 9. 开发预备落地清单

1. 在 `agentic_tool_loop` 增加 Tool Contract 统一封装。
2. 为 `native_call`、`mcp_call` 统一注入 `trace_id` 与 `risk_level`。
3. 为高风险调用增加门禁与审计回放。
4. 将规范落地到测试用例（参数校验、拦截、降级、审计）。

## 10. Token 经济学与成本控制（硬约束）

目标：避免上下文爆炸与长期 Token 亏损；长程运行成本降低 90%+。

### 10.1 Prompt 分层缓存规范

Block 1（静态头部）：

1. 内容：系统角色、全局规范（`CLAUDE.md`）、MCP 工具 Schema。
2. 强制标记：`cache_control: {"type":"ephemeral"}`。
3. 体量基线：约 10k tokens，目标命中率 >= 90%。

Block 2（长期记忆）：

1. 内容：过去 24h 精简摘要。
2. 强制标记：第二个 `ephemeral`，紧跟 Block 1。

Block 3（动态窗口）：

1. 内容：最近 3~5 轮真实交互。
2. 禁止缓存标记。
3. 超过 10k tokens 软阈值时，强制触发 GC（证据保真归档 + 摘要索引 + 历史裁剪）。

### 10.2 异构模型分流规范

系统必须通过统一 `LLM_Gateway` 分流：

1. 主控路由/代码生成 -> 主模型（高成本）。
2. 后台清理/记忆压缩 -> 次模型（低成本）。
3. 重度日志解析 -> 本地开源模型（零 API 成本）。

### 10.3 I/O 防爆规范

1. 禁止全局大文件直读：禁止把 `cat` 作为默认读取工具。
2. 强制结构化读取：优先 `grep`、`awk`、`file_ast_skeleton`。
3. 强制 patch/diff 修改：禁止整文件重写。
4. 命令输出必须结构化封装：返回 `display_preview + truncated + total_chars/lines`。
5. 对 JSON/XML/CSV 等结构化输出，禁止字符级头尾切断；超阈值时必须落盘 artifact，并返回 `raw_result_ref`。
6. 仅纯文本日志允许预览截断；截断结果不可冒充原始结果。
7. 返回 `raw_result_ref` 时，必须同时提供可调用读取路径（如 `artifact_reader`），支持 `jsonpath/line_range/grep`。
8. Artifact Store 必须启用 `TTL + quota + high-watermark`，超过阈值时拒绝新大对象写入并告警。

### 10.4 事件驱动休眠规范

1. 禁止轮询监控。
2. 必须提供 `sleep_and_watch(log_file, regex)`。
3. 监听器必须具备 `tail -F` 语义（inode 变更检测 + 文件重开），防止 logrotate 后假死。
4. 休眠期间销毁会话上下文，由宿主接管监听，触发后再唤醒模型。
5. 每个 watch 必须有心跳与超时告警，防止永久挂起。

## 11. 多 Agent 并发灾难防护（硬约束）

### 11.1 文件指纹乐观锁

1. `read_file` 必须返回 `file_hash`。
2. `edit_file` 必须提交 `original_file_hash`。
3. hash 冲突返回硬错误并强制重新拉取上下文。
4. 巨型文件（例如 >5,000 行）默认走 `file_ast_skeleton` 分层读取，禁止冲突后全量回读。
5. hash 冲突后必须优先 `semantic_rebase + conflict_ticket + exponential_backoff`，防止并发活锁。

### 11.2 全局状态互斥锁

1. 局部行为可并发（受乐观锁保护）。
2. 全局行为（装依赖、分支切换、服务启停等）必须申请 `MUTEX_GLOBAL_STATE`。
3. 冲突请求进入 `QUEUE`，等待锁释放后串行执行。
4. 锁必须具备 TTL + 心跳续租 + fencing token；禁止无过期时间的永久锁。
5. 必须实现 orphan lock 清理：持锁进程异常退出后自动回收。
6. 锁 owner 失去 lease 时，必须终止旧 owner 对应物理执行进程树。
7. 进程回收不能只依赖 PGID；必须绑定 `cgroup/container_id/job_root_id` 做全链路清理。
8. 对 `docker run -d` / `nohup` / `setsid` 双重派生进程，必须通过容器 runtime 或 cgroup 递归回收。

### 11.3 仲裁熔断

1. 平级 Agent 禁止直连沟通，必须经 Router。
2. 设置 `MAX_DELEGATE_TURNS = 3`。
3. 超限后冻结任务并触发 Human-in-the-Loop 裁决。

### 11.4 API 令牌桶流控

1. 在 LLM 客户端层实现 Token Bucket。
2. 设置 `MAX_CONCURRENT_API_CALLS`（例如 5）。
3. 超限请求异步排队，禁止直接放大到上游 429 雪崩。

## 12. 黄金法则（必须执行）

- `逻辑并发，执行串行`

含义：

1. 允许并发思考与只读分析。
2. 所有物理状态改变动作必须经 Event Bus 串行落地。
3. 这是并发 Agent 架构下保障稳定性与成本可控的最终防线。

## 13. 交叉引用

- 总览：`./01-module-overview.md`
- 工具执行管线：`./06-structured-tool-calls-and-local-first-native.md`
- 自治 SDLC（历史归档）：`./07-archived-autonomous-agent-sdlc-architecture.md`
- 目标契约参考：`./00-omni-operator-architecture.md`
- 安全盲区与加固基线：`./13-security-blindspots-and-hardening.md`

## 14. 已识别高风险盲区（补充）

以下风险已被纳入强制治理范围：

1. Regex 黑名单可被命令混淆绕过（变量拼接/编码执行/跨解释器调用）。
2. `register_new_tool` 若在宿主进程内加载不受信插件，存在宿主劫持风险。
3. 全局锁异常退出导致锁泄漏，及旧 epoch 物理任务残留导致 fencing 失效。
4. 暴力截断结构化输出造成数据破损，引发错误重试回路。
5. 自我进化阶段可能通过修改测试“骗过验证”（Test Poisoning）。
6. `sleep_and_watch` 若仅依赖 `tail -f`，在日志轮转后可能永久挂起。
7. `raw_result_ref` 若不可二次读取，会出现“读后即盲”认知死锁。
8. `file_ast` 在巨型单体文件与高并发冲突下可能触发 OOM + 活锁风暴。
9. 脚手架多文件非原子提交会造成半写损坏态（Dirty State）。
10. Artifact Store 若无配额与淘汰策略，可能触发磁盘 DoS。

详细威胁模型、控制项与验收标准见：`./13-security-blindspots-and-hardening.md`。
