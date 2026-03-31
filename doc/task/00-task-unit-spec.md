# 00 任务单元规范（Task Unit Spec）

## 1. 任务 ID 规范

格式：`NGA-WS{工作流编号}-{三位序号}`  
示例：`NGA-WS14-006`

## 2. 最小字段（必须完整）

每个任务单元必须包含以下字段：

| 字段 | 说明 |
|---|---|
| `task_id` | 全局唯一任务编号 |
| `title` | 任务标题（动词开头） |
| `type` | `migration` / `feature` / `hardening` / `refactor` / `qa` / `ops` |
| `priority` | `P0` / `P1` / `P2` / `P3` |
| `phase` | `M0`-`M5`（里程碑阶段） |
| `scope` | 影响模块与边界 |
| `inputs` | 设计输入（文档/接口/风险项） |
| `deliverables` | 代码/配置/文档/脚本产物 |
| `depends_on` | 前置任务 ID（可为空） |
| `acceptance` | 验收标准（可执行） |
| `rollback` | 失败回退路径 |
| `owner_role` | 建议负责角色（backend/security/infra/qa） |
| `status` | 当前状态 |

## 3. 任务粒度规则

1. 单个任务应在 0.5-2 人日内可独立完成并验证。
2. 若任务跨 3 个以上模块，必须拆分为父任务 + 子任务。
3. 验收不可描述为“看起来正常”，必须有可执行检查项。
4. 所有 `P0/P1` 任务必须定义回滚方案。

## 4. 依赖与并行规则

1. 同一文件高冲突任务默认串行。
2. 不同模块且契约稳定的任务可并行。
3. 涉及数据库/全局状态变更的任务必须在发布窗口内执行。

## 5. DoD（完成定义）

任务标记 `done` 必须同时满足：

1. 功能达成：输出满足 `acceptance`。
2. 安全达成：相关风险项无回归。
3. 可观测达成：有日志/指标/审计记录。
4. 回退可用：回滚路径经过最少一次演练。
5. 文档达成：更新对应文档或 runbook。

## 6. 任务模板

```markdown
### {task_id} {title}
- type: {type}
- priority: {priority}
- phase: {phase}
- owner_role: {owner_role}
- scope: {scope}
- inputs: {inputs}
- depends_on: {depends_on}
- deliverables: {deliverables}
- acceptance: {acceptance}
- rollback: {rollback}
- status: {status}
```
