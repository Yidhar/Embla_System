# Prompt 任务排期协议（TSP-v1）

## 1. 目标

为当前自主运行 agent 架构提供统一的“提示词级任务排期协议”，确保以下能力一致：
- 多步骤任务可拆解、可排序、可回退
- 工具调用顺序与验收链路一致
- 结果可追溯到证据路径（报告/日志/产物）

本协议用于约束 `system/prompts/*.txt` 的行为口径，不替代代码层状态机。

## 2. 适用范围

- `system/prompts/conversation_style_prompt.txt`
- `system/prompts/conversation_analyzer_prompt.txt`
- `system/prompts/tool_dispatch_prompt.txt`
- `system/prompts/agentic_tool_prompt.txt`

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

## 5. 四份 Prompt 职责分层

1. `conversation_style_prompt`
- 定义执行优先、证据优先、发布语义边界。
- 约束回答层如何呈现排期与结果。

2. `conversation_analyzer_prompt`
- 将“最新用户消息”转换为可执行 JSON 调用。
- 复合任务按 `T0->T1->T2->T3` 顺序拆分数组。

3. `tool_dispatch_prompt`
- 决策 native/mcp 的路由。
- 强化“先发现再实施再验证再证据”的调度规则。

4. `agentic_tool_prompt`
- 约束函数调用模式与执行闭环。
- 强化 schema 合法性、自治发布治理、交付口径。

## 6. 与自治工作流状态机的关系

Prompt 排期协议与状态机互补：
- Prompt 决定“如何组织任务与调用顺序”
- 状态机决定“哪些状态允许推进、哪些条件必须拒绝”

发布语义仍以代码门禁为准：
- `ReleaseCandidate` 仅代表待灰度
- `CanaryRunning` 通过后才可宣告“已发布/已晋升”

## 7. 变更落地步骤

1. 修改四份 Prompt 文件
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

- 2026-02-25
