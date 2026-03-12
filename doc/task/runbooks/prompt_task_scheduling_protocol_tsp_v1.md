# Routing / Dispatch Prompt 任务排期协议（TSP-v1）

## 1. 目标

为当前自主运行 agent 架构提供统一的“路由 / 调度提示词级任务排期协议”，确保以下能力一致：
- 多步骤任务可拆解、可排序、可回退
- 工具调用顺序与验收链路一致
- 结果可追溯到证据路径（报告/日志/产物）

本协议用于约束 routing / dispatch prompt 的行为口径，不替代代码层状态机。

## 2. 适用范围

- `system/prompts/core/routing/conversation_analyzer_prompt.md`
- `system/prompts/core/routing/tool_dispatch_prompt.md`

不适用范围（当前 canonical）：
- `system/prompts/dna/shell_persona.md`
- `system/prompts/dna/core_values.md`
- `system/prompts/core/dna/conversation_style_prompt.md`
- `system/prompts/core/dna/agentic_tool_prompt.md`

说明：
- 上述四份 DNA / contract prompt 只负责身份、表达组织与工具调用真值约束，不承载 `T0->T1->T2->T3` 的任务编排语义。

## 3. TSP-v1 字段定义（最小集）

- `task_id`: 稳定任务标识（示例：`TASK-20260225-1930-A1`）
- `priority`: `P0|P1|P2`
- `owner`: 默认 `agent`
- `depends_on`: 依赖任务列表
- `eta_minutes`: 预计时长
- `acceptance`: 验收标准
- `rollback`: 回退策略
- `evidence_path`: 证据路径（推荐 `scratch/reports/...`）
- `status`: `queued|running|blocked|verifying|done|failed|rolled_back`

说明：
- Prompt 层可以以“排期卡”方式表达上述字段，不要求逐字段落入工具调用 schema。
- 工具调用参数必须遵守运行时 schema，不得注入未声明字段。

## 4. 阶段化执行模型

复杂任务默认拆成 4 个阶段：
1. `T0 发现`：读取上下文、定位代码/配置/日志、明确约束
2. `T1 实施`：执行修改或动作
3. `T2 验证`：最小必要回归（lint/test/脚本）
4. `T3 证据`：输出报告路径、关键日志、剩余风险

约束：
- 不得绕过 `T0` 直接高风险写入。
- `T2` 失败时优先修复或回退。
- `T3` 必须可审计。

## 5. Prompt 职责分层（当前 canonical）

1. `shell_persona` / `core_values`
- 身份 DNA。
- 只定义人格、自我驱动与稳定价值，不定义路由、排期或工具协议。

2. `conversation_style_prompt`
- 表达编排 DNA。
- 只定义回答结构、信息密度与真实性边界，不定义任务排期、路由或发布语义。

3. `conversation_analyzer_prompt`
- 将“最新用户消息”转换为可执行 JSON 调用。
- 复合任务按 `T0->T1->T2->T3` 顺序拆分数组。

4. `tool_dispatch_prompt`
- 决策 native/mcp 的路由。
- 强化“先发现再实施再验证再证据”的调度规则。

5. `agentic_tool_prompt`
- 工具调用契约 DNA。
- 只约束 schema 合法性、工具真值表达与失败处理，不承载 `TSP-v1` 排期或角色分工。

## 6. 与自治工作流状态机的关系

Prompt 排期协议与状态机互补：
- Prompt 决定“如何组织任务与调用顺序”
- 状态机决定“哪些状态允许推进、哪些条件必须拒绝”

发布语义仍以代码门禁为准：
- `ReleaseCandidate` 仅代表待灰度
- `CanaryRunning` 通过后才可宣告“已发布/已晋升”

## 7. 变更落地步骤

1. 修改 routing / dispatch prompt 文件
2. 更新 DNA manifest 哈希（`system/prompts/immutable_dna_manifest.spec`）
3. 执行最小验证：
- `python scripts/validate_immutable_dna_gate_ws23_003.py --strict`（或等价命令链）
- 相关 prompt/API 回归（按当前阶段测试集）

推荐一键命令：
- `python scripts/update_immutable_dna_manifest_ws23_003.py --approval-ticket CHG-2026-XXXX --strict`

## 8. 回退策略

当新 prompt 引发误调度、工具调用失败率明显上升时：
1. 依据 DNA 审计记录回退到上一个已批准版本
2. 保留失败样本（输入消息 + 解析输出 + 错误栈）
3. 修订后重新走审批与哈希更新

## 9. 最后更新

- 2026-03-12（按当前 canonical 分层修订）
