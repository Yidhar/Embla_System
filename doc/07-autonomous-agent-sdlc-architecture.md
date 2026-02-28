---
**文档类型**：As-Is + Target-Aligned（混合文档）
**实施状态**：Phase 3 桥接主链已落地（Sub-Agent + NativeExecutionBridge），Phase 3 Full 持续收口
**最后更新**：2026-02-27
**当前实现**：autonomous/ 模块（System Agent + Sub-Agent Runtime + NativeExecutionBridge + Workflow Store + Lease/Fencing）
**目标态参考**：00-omni-operator-architecture.md (Phase 3)
---

# 07 Autonomous Agent SDLC 架构（开发预备对齐版）

文档状态：开发预备（As-Is + Target-Aligned）
最后更新：2026-02-27

## 1. 文档定位

本文不再把目标态与现状混写。

- `As-Is`：当前 `autonomous/` 已落地能力（可运行）。
- `Target`：Embla_system 目标架构（`00-omni-operator-architecture.md` + 10/11/12）。
- `Gap`：从当前到目标态的实施差距。
- `状态判定`：是否属于 `BRIDGE_DONE` / `TARGET_DONE` 以 `doc/task/25-subagent-development-fabric-status-matrix.md` 为准。

## 1.1 autonomous/ 模块统一定位

**核心职责**：
- System Agent 自治闭环（感知 → 规划 → 执行 → 评估）
- SDLC 工作流状态管理（Workflow Store + Event Log）
- 单活 Lease/Fencing 防双主
- Canary 发布与自动回滚

**架构定位**：
- 属于 **Brainstem 层**（控制与接入）
- 与 apiserver 平级，独立后台运行
- 通过 Event Bus 与其他模块通信（目标态）
- 当前默认执行链：`Sub-Agent Runtime + NativeExecutionBridge`；CLI Adapter 仅历史兼容入口

**运行模式**：
- **Phase 0（当前）**：单实例常驻，按配置周期执行
- **Phase 1-2**：增加 Standby 实例，Lease 抢占
- **Phase 3**：完整 Event Bus 驱动

**执行模型演进路径**：
- **Phase 0（历史基线）**：CLI Adapter + 外部 CLI 执行
  - 仅保留兼容参考，不作为当前默认执行层
- **Phase 1-2（✅ 已完成）**：Sub-Agent Runtime 桥接接管
  - Runtime/Contract/Scaffold/Rollout 主链收敛
- **Phase 3（🟡 进行中）**：NativeExecutionBridge 治理闭环 + 角色语义执行器深化
  - 现状：内生执行桥为默认主路径（已去 CLI 黑盒）
  - 参考：`00-omni-operator-architecture.md`、`doc/task/25-subagent-development-fabric-status-matrix.md`

## 2. 当前已实现能力（As-Is）

### 2.1 System Agent 主循环

核心实现：`autonomous/system_agent.py`

- 按配置周期执行自治循环。
- 默认通过 `runtime_mode=subagent` 进入 `Sub-Agent Runtime + NativeExecutionBridge`。
- legacy CLI 回退路径已从主流程退役（subagent-only cutover）。
- Verifying 阶段 legacy 外部执行降级已从主流程退役（不再作为运行时可选分支）。

**执行策略更新**（2026-02-27）：
- **v1 (历史)**：验证阶段存在外部降级分支
- **v2 (历史)**：外部 CLI 作为主执行路径
- **v3 (当前)**：内生执行桥主路径（Sub-Agent Runtime + NativeExecutionBridge），外部 CLI 仅历史参考

说明：
- 上述为当前代码 `As-Is` 能力，不代表目标态设计。
- 目标态开发任务编排已在 `00-omni-operator-architecture.md + 10/11/12` 中切换为"子代理 + 脚手架"方案，不再以 CLI 节点作为主执行设计。
- **演进路径**：Phase 0 (CLI Tools, historical) → Phase 1-2 (bridge cutover) → Phase 3 (governance & full target closure)

### 2.2 状态机与工作流持久化

核心实现：`autonomous/state/workflow_store.py`

- 工作流创建与状态迁移。
- 命令幂等（`workflow_command + idempotency_key`）。
- 终态覆盖：`Promoted`、`RolledBack`、`FailedExhausted`、`FailedHard`、`Killed`。

### 2.3 单活与防双主

核心实现：`orchestrator_lease` + `fencing_epoch`

- lease 续租/抢占。
- fencing epoch 写入与校验。
- 失去 lease 后阻断继续写入。

### 2.4 事件与分发可靠性

核心实现：

- `autonomous/event_log/event_store.py`
- `outbox_event` + `inbox_dedup` 机制

能力点：

- 事件追加写入。
- outbox 读取与分发。
- consumer 去重与幂等完成。

### 2.5 发布治理

核心实现：`autonomous/release/controller.py`

- canary 观察窗口判定。
- 阈值策略评估（错误率、延迟、KPI）。
- 自动回滚命令执行与结果记录。

## 3. 与 Embla_system 目标态对齐矩阵

| 目标能力 | 当前状态 | 当前落点 | 说明 |
|---|---|---|---|
| Single Active + Lease/Fencing | 已实现 | `autonomous/system_agent.py` + `workflow_store.py` | 可运行 |
| Workflow + Command 幂等 | 已实现 | `workflow_store.py` | 已有 `idempotency_key` |
| Outbox/Inbox 可靠分发 | 已实现 | `workflow_store.py` | 已具备去重与补偿入口 |
| Canary + Rollback | 已实现 | `release/controller.py` | 支持阈值判定 |
| Tool Contract 全字段强校验 | 部分实现 | `agentic_tool_loop.py` | 仍缺统一强制契约对象 |
| 多租户强隔离（tenant/project） | 未实现 | - | 目标态要求，当前单租户语义 |
| 完整投影与读屏障（watermark） | 部分实现 | `event_store` / `workflow_store` | 尚未形成全链投影治理 |
| 人工审批/Policy Override 全链路 | 部分实现 | policy 配置 + release 逻辑 | 审批流程仍需系统化 |

## 4. 目标态引用关系

以下文档是目标蓝图，不等价于当前实现：

- `./00-omni-operator-architecture.md`
- `./10-brainstem-layer-modules.md`
- `./11-brain-layer-modules.md`
- `./12-limbs-layer-modules.md`

本文件用于标注“已实现子集”与“下一步落地顺序”。

## 5. 开发预备路线（建议）

### Phase A：契约收敛

1. 将 Tool Contract 统一接入 `agentic_tool_loop`。
2. 统一 `trace_id/caller_role/risk_level` 字段在工具执行链透传。

### Phase B：治理收敛

1. 将 release gate 与策略文件绑定到统一 policy 层。
2. 将 `autonomous` 事件与 API 工具事件做统一审计格式。

### Phase C：目标态补齐

1. 引入 tenant/project 隔离字段。
2. 补齐 projection watermark 与读屏障。
3. 打通审批门禁与失败补偿 runbook。

### Phase D：并发安全墙落地（新增）

1. 文件指纹乐观锁：`read_file` 返回 hash，`edit_file` 必传 `original_file_hash`。
2. 全局状态互斥锁：`npm install/git branch/systemctl` 等全局行为串行执行。
3. Router 仲裁熔断：同任务子 Agent 相互驳回超过 `MAX_DELEGATE_TURNS=3` 即进入人工裁决。
4. 令牌桶流控：统一网关限制并发 API 调用，超限请求排队等待。

## 6. 多 Agent 并发灾难防护机制（目标态细化）

状态标记：`目标态规范`，当前项目仅部分具备（单活 + 幂等 + outbox 基础），以下为待落地强约束。

### 6.1 文件指纹乐观锁

目标：避免并发写覆盖。

规则：

1. `read_file` 响应必须包含 `file_hash`（MD5 或 last-modified 指纹）。
2. `edit_file` 请求必须携带 `original_file_hash`。
3. hash 不一致时返回硬错误：`Error: File modified by another process. Refresh your context.`

### 6.2 全局环境状态互斥锁

目标：隔离局部改动与全局环境变化。

规则：

1. 局部行为（单文件编辑）可并发，但受乐观锁限制。
2. 全局行为（如 `npm install`、`apt-get update`、`git branch`、`systemctl restart`）必须申请 `MUTEX_GLOBAL_STATE`。
3. 冲突请求进入 `QUEUE` 等待，不可抢占执行。

### 6.3 仲裁干预与防死循环

目标：阻断子 Agent 相互拉扯导致的 Token 失控。

规则：

1. 平级 Agent 禁止直接对话，必须经 Router 中转。
2. 配置 `MAX_DELEGATE_TURNS=3`。
3. 超限后冻结任务并输出冲突摘要，进入 Human-in-the-Loop 裁决。

### 6.4 API 雪崩防护（令牌桶）

目标：防止并发爆发触发上游 429。

规则：

1. 在 LLM 客户端层实现 Token Bucket。
2. 设置 `MAX_CONCURRENT_API_CALLS`（例如 5）。
3. 超出配额请求在宿主内存队列异步等待，避免子 Agent 级联失败。

## 7. 本版本结论

`autonomous/` 已不是“纯设计占位”，而是可运行的 SDLC 子系统。

当前文档语义应视为：

- 已具备控制闭环骨架（可用于开发预备）
- 尚未达到目标态全量治理能力

## 8. 交叉引用

- 总览：`./01-module-overview.md`
- 工具执行管线：`./06-structured-tool-calls-and-local-first-native.md`
- 前后端入口边界：`./08-frontend-backend-separation-plan.md`
- 工具治理规范：`./09-tool-execution-specification.md`
- 安全盲区与加固基线：`./13-security-blindspots-and-hardening.md`
