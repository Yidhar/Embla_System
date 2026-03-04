---
**文档类型**：🎯 目标态架构设计（Target Architecture - Phase 2-3）
**实施状态**：Phase 2-3 规划（当前 Phase 0 轻量实现）
**最后更新**：2026-02-22
**当前替代方案**：Event Store (autonomous/event_log/) + Native Executor (system/)
**实施路径**：Phase 0 (轻量事件) → Phase 1-2 (本文档) → Phase 3 (完整守护)
---

# 10 - 脑干层模块详细架构 (Brainstem Layer Modules)

> **定位**：脑干层是 Embla_system 的不可变守护进程区。Agent 无法修改该层的任何代码。所有模块编译后打包为二进制运行，由人类工程师维护。
>
> **实施状态**：
> - 🟢 **Phase 0 已实现**：Event Store (SQLite)、Native Executor、基础安全沙箱
> - 🟡 **Phase 1-2 规划**：Event Bus、Watchdog、Security Kernel（本文档）
> - 🔴 **Phase 3 目标态**：Immutable DNA、KillSwitch、完整守护进程
>
> **当前实现映射**：
> - Event Bus → Event Store (core/event_bus/event_store.py)
> - Watchdog → 无（目标态）
> - Immutable DNA → Prompt 文件 (system/prompts/)
> - Security Kernel → Native Executor (system/native_executor.py)
> - KillSwitch → 无（目标态）

---

## 1. Event Bus 事件驱动总线

### 1.1 模块职责

取代传统"一问一答"模式，实现系统级事件的发布/订阅/路由。所有系统告警、定时任务、Agent 间通信均通过 Event Bus 流转。

### 1.2 内部架构

```mermaid
flowchart TB
    subgraph EventBus["Event Bus 核心"]
        direction TB
        PUB["Publisher API<br/>publish(channel, payload)"]
        BROKER["Message Broker<br/>频道路由 · 优先级队列 · 死信队列"]
        SUB["Subscriber Registry<br/>订阅管理 · 通配符匹配"]

        subgraph Channels["内置频道"]
            CH_SYS["system.*<br/>CPU·内存·磁盘·网络"]
            CH_LOG["log.*<br/>日志告警·错误模式"]
            CH_CRON["cron.*<br/>定时任务触发"]
            CH_AGENT["agent.*<br/>Agent间通信·状态变更"]
            CH_TOOL["tool.*<br/>工具执行事件"]
            CH_EVO["evolution.*<br/>自我进化事件"]
            CH_MUTEX["mutex.*<br/>全局锁申请·释放"]
            CH_BUDGET["budget.*<br/>配额告警·令牌桶状态"]
            CH_WAKE["wake.*<br/>休眠唤醒·条件触发"]
        end

        DLQ["Dead Letter Queue<br/>失败事件暂存"]
        PERSIST["Event Persistence<br/>SQLite 事件持久化"]
    end

    subgraph Producers["事件生产者"]
        P_WD["Watchdog"]
        P_CRON["Cron Scheduler"]
        P_TOOL["MCP Tools"]
        P_AGENT["Agent Processes"]
        P_OS["OS Signal Handler"]
    end

    subgraph Consumers["事件消费者"]
        C_META["Meta-Agent"]
        C_GC["GC Engine"]
        C_DAILY["Daily Checkpoint"]
        C_ALERT["Alert Manager"]
    end

    P_WD & P_CRON & P_TOOL & P_AGENT & P_OS -->|publish| PUB
    PUB --> BROKER
    BROKER --> CH_SYS & CH_LOG & CH_CRON & CH_AGENT & CH_TOOL & CH_EVO & CH_MUTEX & CH_BUDGET & CH_WAKE
    CH_SYS & CH_LOG & CH_CRON & CH_AGENT & CH_TOOL & CH_EVO & CH_MUTEX & CH_BUDGET & CH_WAKE --> SUB
    SUB --> C_META & C_GC & C_DAILY & C_ALERT

    BROKER -->|投递失败| DLQ
    BROKER -->|所有事件| PERSIST

    style EventBus fill:#0a1a2e,stroke:#4488ff,color:#cce0ff
```

### 1.3 事件生命周期时序

```mermaid
sequenceDiagram
    participant Producer as 事件生产者
    participant EB as Event Bus
    participant Broker as Message Broker
    participant Registry as Subscriber Registry
    participant DLQ as Dead Letter Queue
    participant Persist as Event Persistence
    participant Consumer as 事件消费者

    Producer->>EB: publish("system.cpu.overload", {usage: 95%})
    EB->>Persist: 持久化事件 (event_id, timestamp, payload)
    EB->>Broker: 路由到 system.* 频道

    Broker->>Registry: 查询 system.* 订阅者列表
    Registry-->>Broker: [Meta-Agent, Alert Manager]

    par 并行分发
        Broker->>Consumer: deliver(event, subscriber=Meta-Agent)
        Note right of Consumer: timeout=5000ms
        Consumer-->>Broker: ACK ✅
    and
        Broker->>Consumer: deliver(event, subscriber=Alert Manager)
        Consumer-->>Broker: ACK ✅
    end

    alt 投递失败 (超时/异常)
        Broker->>Broker: retry(max=3, backoff=1000ms)
        alt 重试耗尽
            Broker->>DLQ: 移入死信队列
            DLQ->>DLQ: scheduled_retry(interval=60s)
        end
    end
```

### 1.4 核心接口

```typescript
// src/core/event_bus.ts
interface EventBus {
  publish(channel: string, payload: EventPayload): Promise<string>;  // 返回 event_id
  subscribe(pattern: string, handler: EventHandler, opts?: SubscribeOpts): Subscription;
  unsubscribe(subscription: Subscription): void;
  replay(fromSeq: number, toSeq?: number): AsyncIterable<Event>;    // 事件回放
  getDeadLetters(limit?: number): Promise<Event[]>;
  retryDeadLetter(eventId: string): Promise<boolean>;
  enqueueSerialAction(action: SerialAction): Promise<QueueTicket>;   // 串行执行入口
  waitForQueueTicket(ticketId: string): Promise<QueueState>;
}

interface EventPayload {
  event_type: string;
  source: string;
  severity: "info" | "warn" | "error" | "critical";
  data: Record<string, unknown>;
  idempotency_key: string;
  timestamp: number;
}

interface SubscribeOpts {
  priority: number;           // 消费优先级 (1=最高)
  maxConcurrency: number;     // 最大并发处理数
  timeout_ms: number;         // 单次处理超时
  retryPolicy: RetryPolicy;   // 失败重试策略
}

interface SerialAction {
  action_id: string;
  actor: string;
  scope: "local" | "global";
  action_type: "write_file" | "install_dep" | "git_branch" | "restart_service" | "other";
  requires_global_mutex: boolean;
  payload: Record<string, unknown>;
}

interface QueueTicket {
  ticket_id: string;
  position: number;
  eta_ms: number;
}

interface QueueState {
  ticket_id: string;
  status: "queued" | "running" | "done" | "failed";
}
```

---

## 2. Watchdog 看门狗进程

### 2.1 模块职责

独立于所有 Agent 进程运行，监控资源占用、检测死循环、追踪 API 成本。当检测到异常时强制干预（截断/重启/熔断）。

### 2.2 内部架构

```mermaid
flowchart TB
    subgraph Watchdog["Watchdog 看门狗"]
        direction TB
        RM["🖥️ Resource Monitor<br/>CPU · RAM · Disk · Network<br/>采集间隔: 5s"]
        LD["🔄 Loop Detector<br/>连续错误计数器<br/>Token/轮次比异常检测"]
        CM["💰 Cost Monitor<br/>API 调用成本追踪<br/>按模型·按任务·按日"]
        DC["📅 Daily Checkpoint<br/>24h全局Summarization<br/>上下文重置"]

        subgraph Thresholds["熔断阈值配置"]
            T_CPU["CPU > 90% 持续 60s"]
            T_MEM["RAM > 85% 持续 30s"]
            T_ERR["连续错误 ≥ 5 次"]
            T_COST["单任务 > $5"]
            T_TOKEN["日Token > 50M"]
            T_LOOP["同一工具调用 > 10次/分钟"]
        end

        subgraph Actions["干预动作"]
            A_WARN["⚠️ 发布告警事件"]
            A_PAUSE["⏸️ 暂停当前任务"]
            A_KILL["❌ 终止Agent进程"]
            A_RESTART["🔄 重启Agent"]
            A_BUDGET["🚫 冻结预算"]
        end
    end

    RM --> T_CPU & T_MEM
    LD --> T_ERR & T_LOOP
    CM --> T_COST & T_TOKEN

    T_CPU & T_MEM -->|超阈值| A_WARN
    T_ERR -->|首次| A_PAUSE
    T_ERR -->|持续| A_KILL
    T_LOOP --> A_KILL
    T_COST --> A_KILL
    T_TOKEN --> A_BUDGET

    A_WARN & A_PAUSE & A_KILL & A_RESTART & A_BUDGET -->|广播| EB["Event Bus"]

    style Watchdog fill:#1a0a0a,stroke:#ff4444,color:#ffcccc
```

### 2.3 监控采集与干预时序

```mermaid
sequenceDiagram
    participant WD as Watchdog
    participant RM as Resource Monitor
    participant LD as Loop Detector
    participant CM as Cost Monitor
    participant EB as Event Bus
    participant AGENT as Agent Process
    participant OS as Host OS

    loop 每 5 秒采集
        WD->>RM: collect_metrics()
        RM->>OS: 读取 /proc/stat, /proc/meminfo
        OS-->>RM: {cpu: 92%, mem: 78%, disk: 45%}

        RM->>RM: 评估: cpu > 90% 持续 60s?
        alt CPU 过载
            RM->>EB: publish("system.cpu.overload", {usage: 92%})
            RM->>AGENT: 降低并发 (throttle)
        end
    end

    loop 每次 Agent 工具调用后
        WD->>LD: check_loop(tool_name, result)
        LD->>LD: 更新连续错误计数器

        alt 连续错误 ≥ 5
            LD->>EB: publish("agent.loop.detected", {count: 5})
            LD->>AGENT: ⛔ SIGTERM
            LD->>EB: publish("agent.restarting", {reason: "loop"})
            LD->>AGENT: 重启 (带新策略)
        end
    end

    loop 每次 API 调用后
        WD->>CM: track_cost(model, tokens, cost)
        CM->>CM: 累计当日消耗

        alt 单任务 > $5
            CM->>AGENT: ⛔ 强制终止当前任务
            CM->>EB: publish("budget.task.exceeded")
        end

        alt 日总 > $50
            CM->>CM: 冻结所有非关键预算
            CM->>EB: publish("budget.daily.exhausted")
        end
    end
```

### 2.4 核心接口

```typescript
// src/watchdog/resource_monitor.ts
interface ResourceMonitor {
  collectMetrics(): Promise<SystemMetrics>;
  setThresholds(config: ThresholdConfig): void;
  onThresholdBreach(handler: (metric: string, value: number) => void): void;
}

interface SystemMetrics {
  cpu_percent: number;
  memory_percent: number;
  disk_percent: number;
  network_bytes_sent: number;
  network_bytes_recv: number;
  open_file_descriptors: number;
  agent_process_count: number;
  timestamp: number;
}

// src/watchdog/loop_detector.ts
interface LoopDetector {
  recordToolCall(tool: string, success: boolean, session_id: string): void;
  isLooping(session_id: string): boolean;
  getConsecutiveErrors(session_id: string): number;
  reset(session_id: string): void;
}

// src/watchdog/cost_monitor.ts
interface CostMonitor {
  trackCall(model: string, input_tokens: number, output_tokens: number): void;
  getTaskCost(task_id: string): number;
  getDailyCost(): number;
  getRemainingBudget(): { daily: number; task: number };
  isBudgetExhausted(): boolean;
}
```

---

## 3. Immutable DNA 不可变基因

### 3.1 模块职责

维护一段极短的核心安全 Prompt，每次 LLM 对话强制前置注入。Agent 无权读取源文件路径、无权修改此内容。确保 Agent 在任何情况下都不会违反安全底线。

### 3.2 内部架构

```mermaid
flowchart LR
    subgraph DNA["Immutable DNA 模块"]
        LOADER["DNA Loader<br/>启动时从加密文件加载"]
        CACHE["内存缓存<br/>(只读·不可导出)"]
        INJECTOR["Prompt Injector<br/>每次API调用前自动注入"]
        HASH["Integrity Check<br/>SHA-256 完整性校验"]
    end

    CONFIG["embla_system.yaml<br/>(加密DNA路径)"] --> LOADER
    LOADER -->|"解密·校验"| CACHE
    CACHE --> INJECTOR
    INJECTOR -->|"强制前置"| LLM["LLM Client"]

    HASH -->|"每60s校验"| CACHE
    HASH -->|"篡改告警"| EB["Event Bus"]

    style DNA fill:#2a1a0a,stroke:#ffaa44,color:#ffddbb
```

### 3.3 DNA 注入时序

```mermaid
sequenceDiagram
    participant DNA as Immutable DNA
    participant LLM as LLM Client
    participant API as Anthropic/OpenAI API

    Note over DNA: 启动时加载 DNA 规则到内存

    LLM->>LLM: 准备 API Payload
    LLM->>DNA: requestInjection()
    DNA->>DNA: SHA-256 完整性校验
    alt 校验失败
        DNA-->>LLM: ❌ INTEGRITY_VIOLATION
        DNA->>DNA: 紧急熔断 → 拒绝所有请求
    else 校验通过
        DNA-->>LLM: DNA Prompt (只读副本)
    end

    LLM->>LLM: messages = [<br/>  {role: "system", content: DNA_PROMPT, cache: true},<br/>  {role: "system", content: agent_prompt},<br/>  ...user_messages<br/>]

    LLM->>API: 发送请求 (DNA 始终在最前)
    Note right of API: Agent 看到的 system prompt<br/>始终以 DNA 开头
```

### 3.4 DNA 规则示例

```markdown
## 绝对安全规则 (不可变·不可覆盖)

1. 禁止修改 root 密码或创建 root 级权限账户
2. 禁止关闭 SSH 端口或防火墙
3. 禁止删除 /etc, /boot, /usr 下任何文件
4. 禁止未经审批执行 DROP TABLE / DROP DATABASE
5. 禁止外发敏感数据到非白名单域名
6. 禁止修改本段 DNA 规则或其加载机制
7. 所有破坏性操作前必须创建系统快照
8. 单次任务 Token 成本超过 $5 必须停止并报告
```

---

## 4. Security Kernel 安全内核

### 4.1 模块职责

由四个子模块组成的安全纵深防御体系：命令策略门禁、成本熔断、爆炸半径控制、人类审批旁路。

### 4.2 安全纵深架构

```mermaid
flowchart TB
    subgraph SecurityKernel["Security Kernel 安全内核"]
        direction TB
        subgraph Layer1["第一层: 命令策略门禁 (Policy Firewall)"]
            RF_INPUT["输入扫描<br/>命令·文件路径·SQL"]
            RF_RULES["规则引擎<br/>能力白名单 + 参数Schema<br/>正则仅辅助信号"]
            RF_OUTPUT["输出扫描<br/>工具返回内容敏感信息"]
        end

        subgraph Layer2["第二层: 成本熔断 (Token Breaker)"]
            TB_TASK["任务级熔断<br/>单任务 > $5"]
            TB_DAILY["日级熔断<br/>日总 > $50"]
            TB_MODEL["模型级配额<br/>大模型使用限额"]
        end

        subgraph Layer3["第三层: 爆炸半径 (Blast Radius)"]
            BR_SNAP["快照管理<br/>多后端快照链路"]
            BR_SCOPE["影响范围评估<br/>变更文件数·行数"]
            BR_ROLLBACK["回滚策略<br/>自动/手动回滚"]
        end

        subgraph Layer4["第四层: 人类审批 (Human Approval)"]
            HA_RULES["审批规则<br/>哪些操作需要人工确认"]
            HA_NOTIFY["通知渠道<br/>Slack · 手机 · Email"]
            HA_TIMEOUT["超时策略<br/>默认拒绝 · 默认允许"]
        end
    end

    TOOL_CALL["工具调用请求"] --> RF_INPUT
    RF_INPUT -->|"通过"| TB_TASK
    RF_INPUT -->|"拦截"| DENIED["❌ Denied"]
    TB_TASK -->|"预算内"| HA_RULES
    TB_TASK -->|"超限"| DENIED
    HA_RULES -->|"低风险·自动放行"| BR_SNAP
    HA_RULES -->|"高风险·需审批"| HA_NOTIFY
    HA_NOTIFY -->|"批准"| BR_SNAP
    HA_NOTIFY -->|"拒绝/超时"| DENIED
    BR_SNAP -->|"快照完成"| EXECUTE["✅ 执行"]

    style SecurityKernel fill:#1a0a0a,stroke:#ff4444,color:#ffcccc
    style Layer1 fill:#2a0a0a,stroke:#ff6666
    style Layer2 fill:#2a0a1a,stroke:#ff66aa
    style Layer3 fill:#1a0a2a,stroke:#aa66ff
    style Layer4 fill:#0a1a2a,stroke:#66aaff
```

### 4.3 安全拦截全链路时序

```mermaid
sequenceDiagram
    participant AGENT as Agent
    participant RF as Policy Firewall
    participant TB as Token Breaker
    participant HA as Human Approval
    participant BR as Blast Radius
    participant EB as Event Bus
    participant OS as Host OS

    AGENT->>RF: tool_call("os_bash", {cmd: "rm -rf /var/log/old"})

    Note over RF: === 第一层: 命令策略门禁 ===
    RF->>RF: 解析 argv/解释器入口
    RF->>RF: 校验能力白名单 + 参数 Schema
    RF->>RF: 拒绝动态执行入口: python -c / sh -c / EncodedCommand
    RF->>RF: 正则黑名单仅做补充信号

    alt 违反策略 (高危能力/参数不合规/动态入口)
        RF->>EB: emit(SecurityBlocked, {rule: "policy_violation", cmd})
        RF-->>AGENT: ❌ BLOCKED: 危险命令被拦截
    else 策略校验通过
        Note over TB: === 第二层: 成本评估 ===
        RF->>TB: 放行至成本检查
        TB->>TB: 检查当前任务已消耗预算
        alt 预算超限
            TB-->>AGENT: ❌ BUDGET_EXCEEDED
        else 预算充足
            Note over HA: === 第三层: 审批判定 ===
            TB->>HA: 放行至审批检查
            HA->>HA: risk_level = "write_repo"<br/>匹配审批规则: 删除操作 → 需审批?

            alt 需人工审批
                HA->>HA: 推送审批请求到 Slack
                HA->>HA: ⏳ 等待 (timeout=300s)
                alt 审批通过
                    HA-->>BR: APPROVED
                else 拒绝或超时
                    HA-->>AGENT: ❌ APPROVAL_DENIED
                end
            else 自动放行
                HA-->>BR: AUTO_APPROVED
            end

            Note over BR: === 第四层: 快照保护 ===
            BR->>OS: create_snapshot("pre-rm-var-log")
            OS-->>BR: snapshot_id=snap_20260222_001
            BR->>BR: 记录恢复点

            BR->>OS: 执行: rm -rf /var/log/old
            OS-->>BR: exit_code=0

            BR->>EB: emit(ToolExecuted, {tool, snapshot_id})
            BR-->>AGENT: ✅ 执行成功 (snapshot可回滚)
        end
    end
```

### 4.4 Policy Firewall 规则配置

```yaml
# embla_system.yaml → security.policy_firewall
policy_firewall:
  capability_allowlist:
    - name: "filesystem.read"
      tool: "os_bash"
      allowed_commands: ["ls", "cat", "grep", "find", "awk", "sed"]
    - name: "filesystem.write"
      tool: "file_ast"
      requires_approval: true

  interpreter_gate:
    deny_patterns:
      - 'python\s+(-c|-m)\b'
      - 'powershell(\.exe)?\s+(-Command|-EncodedCommand)\b'
      - '(bash|sh)\s+-c\b'

  argv_schema:
    enforce: true
    max_args: 32
    max_arg_length: 512

  regex_heuristics:
    enabled: true
    command_blacklist:
      - pattern: 'rm\s+(-[a-zA-Z]*f|-[a-zA-Z]*r)'
        severity: critical
        message: "递归/强制删除命令高风险"
      - pattern: 'mkfs\.|dd\s+if='
        severity: critical
        message: "磁盘格式化/覆写高风险"
      - pattern: 'iptables\s+(-F|-X|-Z|--flush)'
        severity: critical
        message: "防火墙规则清除高风险"
      - pattern: '(DROP|TRUNCATE)\s+(TABLE|DATABASE)'
        severity: critical
        message: "数据库破坏性操作高风险"
      - pattern: 'chmod\s+777|chmod\s+-R'
        severity: high
        message: "危险权限变更高风险"
      - pattern: 'curl.*\|\s*bash|wget.*\|\s*sh'
        severity: critical
        message: "远程脚本执行高风险"

  path_policy:
    whitelist:
      - "workspace/**"
      - "/tmp/agent_dev/**"
      - "/var/log/agent/**"
    blacklist:
      - "/etc/**"
      - "/boot/**"
      - "/usr/bin/**"
      - "/root/**"

  output_scrubbing:
    - pattern: '(?:password|secret|token|api_key)\s*[=:]\s*\S+'
      action: redact
      replacement: "[REDACTED]"
```

---

## 5. KillSwitch 物理熔断器

### 5.1 模块职责

完全独立于 Agent 系统之外的最后防线。监控网络 IO 与磁盘 IO 异常，检测到勒索病毒行为、数据外泄等灾难性场景时，瞬间杀掉所有 Agent 进程。

### 5.2 内部架构

```mermaid
flowchart TB
    subgraph KillSwitch["KillSwitch 物理熔断器 (独立进程)"]
        direction TB
        NET_MON["🌐 Network Monitor<br/>出站流量实时监控<br/>目标域名/IP追踪"]
        IO_MON["💾 Disk IO Monitor<br/>写入速率·加密特征检测<br/>大规模文件操作"]
        PROC_MON["🔍 Process Monitor<br/>Agent 进程树监控<br/>子进程异常 fork 检测"]

        subgraph Triggers["触发条件"]
            T_NET["出站 > 100MB/min<br/>到非白名单域名"]
            T_CRYPT["检测到大规模文件<br/>扩展名批量变更"]
            T_FORK["Agent 进程 fork<br/>> 50 子进程"]
            T_MANUAL["人工触发<br/>API/控制台/硬件按钮"]
        end

        subgraph Response["熔断响应"]
            R_KILL["SIGKILL 所有 Agent"]
            R_NET["冻结高风险出站<br/>保留 OOB 管理网段"]
            R_OOB["保持带外管理通道<br/>堡垒机/SSM/云管探针"]
            R_SNAP["恢复最近快照"]
            R_NOTIFY["紧急通知管理员"]
            R_LOG["写入不可篡改日志"]
        end
    end

    NET_MON --> T_NET
    IO_MON --> T_CRYPT
    PROC_MON --> T_FORK

    T_NET & T_CRYPT & T_FORK & T_MANUAL --> R_KILL
    R_KILL --> R_NET
    R_KILL --> R_OOB
    R_KILL --> R_SNAP
    R_KILL --> R_NOTIFY
    R_KILL --> R_LOG

    style KillSwitch fill:#2a0000,stroke:#ff0000,color:#ffaaaa
```

### 5.3 KillSwitch 触发时序

```mermaid
sequenceDiagram
    participant KS as KillSwitch<br/>(独立看门进程)
    participant NET as Network Monitor
    participant IO as Disk IO Monitor
    participant AGENTS as All Agent Processes
    participant FW as Firewall Rules
    participant OOB as OOB Channel
    participant SNAP as Snapshot System
    participant ADMIN as 管理员

    loop 持续监控 (每 2 秒)
        KS->>NET: 采集出站流量
        NET-->>KS: {bytes_out: 150MB/min, dest: unknown_ip}

        KS->>IO: 采集磁盘写入
        IO-->>KS: {write_rate: normal, extension_changes: 0}
    end

    alt 🚨 检测到异常出站
        KS->>KS: anomaly_detected!<br/>出站 150MB/min > 阈值 100MB/min
        KS->>KS: ⚡ 进入紧急熔断模式

        par 同时执行所有响应
            KS->>AGENTS: kill -9 (全部 Agent 进程)
            KS->>FW: apply emergency egress policy<br/>deny non-allowlist OUTPUT
            KS->>OOB: keep allowlist routes alive<br/>(bastion/ssm/console)
            KS->>SNAP: 回滚到最近安全快照
            KS->>ADMIN: 🚨 紧急通知<br/>"检测到异常数据外发"
        end

        KS->>KS: 写入 WORM 审计日志<br/>(不可篡改)
        KS->>KS: 等待人工响应后才能恢复<br/>OOB 通道可执行 disarm/recover
    end
```

### 5.4 核心接口

```typescript
// src/security/kill_switch.ts
interface KillSwitch {
  // 状态查询
  getStatus(): KillSwitchStatus;        // armed | triggered | disarmed
  isArmed(): boolean;

  // 手动控制
  arm(): void;                          // 启用监控
  disarm(adminToken: string): void;     // 需管理员令牌才能解除
  trigger(reason: string): void;        // 手动触发熔断

  // 配置
  setNetworkThreshold(mbPerMin: number): void;
  setDiskThreshold(mbPerMin: number): void;
  setWhitelistDomains(domains: string[]): void;
  setOobAllowlistCIDR(cidrs: string[]): void;
  verifyOobHealth(): Promise<{ healthy: boolean; channels: string[] }>;

  // 恢复
  recover(adminToken: string, snapshotId?: string): Promise<RecoveryResult>;
}

interface KillSwitchStatus {
  state: "armed" | "triggered" | "disarmed";
  last_triggered_at: number | null;
  last_trigger_reason: string | null;
  monitoring: {
    network_out_mb_per_min: number;
    disk_write_mb_per_min: number;
    agent_process_count: number;
  };
}
```

---

## 6. 脑干层模块交互全景

```mermaid
flowchart TB
    subgraph Brainstem["脑干层模块协作全景"]
        EB["Event Bus"]
        WD["Watchdog"]
        DNA["Immutable DNA"]
        KS["KillSwitch"]

        subgraph SK["Security Kernel"]
            RF["Policy Firewall"]
            TB_["Token Breaker"]
            BR["Blast Radius"]
            HA["Human Approval"]
        end
    end

    %% 上层连接
    BRAIN["🧠 大脑层"] -->|"工具调用请求"| RF
    RF -->|"安全放行"| TB_
    TB_ -->|"预算放行"| HA
    HA -->|"审批放行"| BR
    BR -->|"快照后执行"| LIMBS["🦾 手脚层"]

    %% 事件流
    WD -->|"资源告警"| EB
    RF -->|"拦截事件"| EB
    TB_ -->|"超限事件"| EB
    EB -->|"事件分发"| BRAIN

    %% DNA 注入
    DNA -->|"每次对话注入"| BRAIN

    %% 终极熔断
    KS -->|"杀掉一切"| BRAIN & LIMBS
    WD -->|"灾难信号"| KS

    style Brainstem fill:#1a0a0a,stroke:#ff4444,color:#ffcccc
```

---

## 7. 成本与并发守门模块（新增）

> 本节承接 Tokenomics 与多 Agent 并发硬约束，属于 Brainstem 的 Daemon 常驻能力。

### 7.1 模块职责

1. `Global State Mutex`：全局环境变更动作串行化（安装依赖、分支切换、服务启停）。
2. `Rate Limit Gateway`：LLM API 令牌桶限流，防止并发洪峰触发 429。
3. `Sleep Watch Daemon`：接管 `sleep_and_watch(log_file, regex)`，实现零 Token 休眠。

### 7.2 守门架构

```mermaid
flowchart TB
    subgraph Guard["Brainstem Guard Layer"]
        MUTEX["🔒 Global State Mutex<br/>MUTEX_GLOBAL_STATE"]
        QUEUE["📬 Serial Queue<br/>物理执行串行化"]
        BUCKET["🪣 Token Bucket<br/>MAX_CONCURRENT_API_CALLS"]
        SLEEPD["💤 Sleep Watch Daemon<br/>tail -F semantics + safe-regex + timeout budget"]
        EB["Event Bus"]
    end

    AGENTS["Logical Parallel Agents"] --> MUTEX
    MUTEX -->|global action| QUEUE
    QUEUE --> HOST["Physical Host Mutation"]

    AGENTS --> BUCKET
    BUCKET --> LLM["LLM Providers"]

    AGENTS --> SLEEPD
    SLEEPD -->|wake.*| EB
    EB --> AGENTS
```

### 7.3 核心接口

```typescript
// src/core/global_state_mutex.ts
interface GlobalStateMutex {
  acquire(actor: string, actionType: string, timeoutMs?: number): Promise<string>; // lock_id
  release(lockId: string): Promise<void>;
  currentOwner(): Promise<{ actor: string; actionType: string; acquiredAt: number } | null>;
  enqueueIfBusy(request: GlobalActionRequest): Promise<QueueTicket>;
}

interface GlobalActionRequest {
  request_id: string;
  actor: string;
  action_type: "install_dep" | "git_branch" | "restart_service" | "system_update" | "other";
  payload: Record<string, unknown>;
}

// src/core/llm_rate_gate.ts
interface TokenBucketGate {
  configure(maxConcurrentApiCalls: number, refillPerSecond: number): void;
  acquirePermit(requestId: string): Promise<{ permit_id: string; wait_ms: number }>;
  releasePermit(permitId: string): void;
  getQueueDepth(): number;
}

// src/core/sleep_watch_daemon.ts
interface SleepWatchDaemon {
  sleepAndWatch(params: {
    log_file: string;
    regex: string;
    regex_timeout_ms?: number;
    regex_profile?: "safe" | "strict";
    timeout_ms?: number;
    wake_event: string;
  }): Promise<{ watch_id: string; suspended: true }>;
  cancelWatch(watchId: string): Promise<boolean>;
}
```

### 7.4 执行原则

1. 逻辑并发允许并行“思考/只读分析”。
2. 物理写操作必须通过 `Serial Queue` 串行落地。
3. 休眠阶段模型会话内存释放，Token 消耗归零。
4. `Global State Mutex` 必须使用 TTL + 心跳续租，禁止永久锁；异常退出后由清道夫回收 orphan lock。
5. Lease/Fencing 失效时，Brainstem 必须触发旧 epoch 进程树回收，避免物理层并发写入冲突。
6. `Sleep Watch Daemon` 必须实现日志轮转容错（`tail -F` 语义：inode 变更重开 + 心跳告警）。
7. `sleep_and_watch` 的 regex 必须经过复杂度门禁并设置匹配超时，防止 ReDoS。
8. KillSwitch 冻结网络时必须保留 OOB 管理通道，禁止“一刀切”导致云主机失联。

补充参考：`./13-security-blindspots-and-hardening.md`
