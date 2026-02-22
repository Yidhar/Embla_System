---
**文档类型**：🎯 目标态架构设计（Target Architecture）
**实施状态**：Phase 3 规划（当前 Phase 0 已实现 CLI Adapter 过渡方案）
**最后更新**：2026-02-22
**当前替代方案**：见 `架构与时序设计.md` (CLI Tools + Codex-first)
**实施路径**：Phase 0 (CLI) → Phase 1-2 (增强) → Phase 3 (本文档)
---

本文档是 **Omni-Operator v2.0** 的全景架构设计蓝图，面向研发落地交付。包含完整架构拓扑图、交互时序图、系统树节点结构、数据模型、模块化原子规范与开发 Gantt 排期。可直接作为技术评审（TR）与敏捷开发的基线文档。

> [!IMPORTANT]
> **文档定位**：本文档描述 **Phase 3 目标态架构**，非当前实现。
>
> **当前实现**（Phase 0）：
> - 执行模型：CLI Adapter (Codex/Claude/Gemini CLI)
> - 子代理：无独立 Sub-Agent，通过 CLI 工具调用
> - 脚手架：无 Scaffold Engine
>
> **演进路径**：
> - Phase 0 (✅ 已实现)：CLI Tools + System Agent
> - Phase 1-2 (🟡 规划中)：增强监控、降级、Token 经济学
> - Phase 3 (🔴 本文档)：Sub-Agent Runtime + Scaffold Engine + Event Bus
>
> **参考文档**：
> - 当前实现：`架构与时序设计.md`
> - SDLC 对齐：`07-autonomous-agent-sdlc-architecture.md`

---

# Omni-Operator v2.0 全景架构设计蓝图（Phase 3 目标态）

## 1. 核心系统架构：三层"脑干-大脑-手脚"拓扑

系统采用 **三层进程隔离模型**：脑干层（不可变守护进程）、大脑层（认知路由与记忆）、手脚层（MCP 动态工具协议）。结合 **事件驱动总线 + 分布式微 Agent + 自我编译循环** 设计模式。

```mermaid
graph TB
    subgraph BrainstemLayer["🧬 脑干层 Brainstem — 不可变守护进程区"]
        direction TB
        WD["🐕 Watchdog<br/>资源监控 · 死循环检测<br/>API成本熔断 · 强制重启"]
        DNA["🧬 Immutable DNA<br/>不可变核心 Prompt<br/>安全底线规则集"]
        EB["📡 Event Bus<br/>事件驱动总线<br/>PubSub · Cron · Alert"]
        KS["🔴 KillSwitch<br/>物理熔断器<br/>独立于Agent的监控"]

        subgraph SecurityKernel["安全内核"]
            RF["🛡️ Regex Firewall<br/>Bash注入拦截<br/>危险命令阻断"]
            TB_["💰 Token Breaker<br/>账单熔断器<br/>单任务>$5强制kill"]
            BRC["💥 Blast Radius Ctrl<br/>爆炸半径控制<br/>ZFS快照 · 回滚"]
        end
    end

    subgraph BrainLayer["🧠 大脑层 Brain — 认知路由与记忆系统"]
        direction TB
        subgraph CognitiveCore["认知引擎"]
            META["👑 Meta-Agent<br/>元控节点 · 全天候主进程<br/>反思 · 目标拆解 · 子Agent派发"]
            ROUTER["🔀 Router<br/>多Agent路由控制器<br/>任务分类 · 模型选择"]
            LLM["🤖 LLM Client<br/>Anthropic/OpenAI/Google<br/>Prompt Cache · 多模型路由"]
        end

        subgraph TriMemory["三维记忆系统"]
            WM["📋 Working Memory<br/>短期记忆 · 滑动窗口<br/>当前任务上下文"]
            EM["📚 Episodic Memory<br/>长期经验库 · ChromaDB<br/>复盘报告 · RAG检索"]
            SG["🗺️ Semantic Graph<br/>系统拓扑图<br/>目录 · 端口 · 依赖关系"]
        end

        subgraph StateMachine["状态机引擎"]
            SM["⚙️ State Machine<br/>SessionState 状态流转<br/>IDLE→THINKING→EXECUTING"]
            LF["🔐 Lease/Fencing<br/>单活多备 · 世代令牌<br/>防脑裂双写"]
        end
    end

    subgraph LimbsLayer["🦾 手脚层 Limbs — MCP 动态工具协议"]
        direction TB
        subgraph SystemMCP["Host-OS 系统工具"]
            BASH["⌨️ os_bash<br/>带超时截断的Bash执行器"]
            AST["🔧 file_ast<br/>AST精确代码编辑器"]
            SYS["📦 systemd_manager<br/>后台进程管理"]
        end

        subgraph WebMCP["Web 调度与搜索工具"]
            SEARCH["🔍 search_engine<br/>Google/Tavily API"]
            BROWSER["🌐 headless_browser<br/>Playwright无头浏览器"]
        end

        subgraph ChronosMCP["时空控制工具"]
            SLEEP["💤 sleep_until<br/>条件/时间挂起"]
            CRON["⏰ schedule_cron<br/>定期巡检任务"]
        end

        subgraph EvolveMCP["自我进化工具"]
            RPROMPT["📖 read_my_prompt<br/>读取Agent提示词"]
            UPROMPT["✏️ update_my_prompt<br/>修改子Agent提示词"]
            REGTOOL["🔌 register_new_tool<br/>动态注册新工具"]
        end

        subgraph SubAgentFabric["子代理与脚手架层"]
            SA_RUNTIME["🤝 Sub-Agent Runtime<br/>子代理编排·状态同步"]
            SCAFFOLD["🏗️ Scaffold Engine<br/>模板生成·补丁骨架"]
            SA_FRONT["Frontend Sub-Agent"]
            SA_BACK["Backend Sub-Agent"]
            SA_OPS["Ops Sub-Agent"]
        end
    end

    %% 核心数据流
    EB -->|"系统事件<br/>CPU过载·日志报错·定时器"| META
    META -->|"目标拆解·任务派发"| ROUTER
    ROUTER -->|"加载角色规范"| LLM
    LLM -->|"任务下发"| SA_RUNTIME
    SA_RUNTIME --> SA_FRONT & SA_BACK & SA_OPS
    SA_RUNTIME -->|"生成脚手架补丁"| SCAFFOLD
    SA_RUNTIME --> BASH & AST & SEARCH & BROWSER

    %% 安全控制流
    BASH & AST -->|"执行前校验"| RF
    RF -->|"危险命令拦截"| WD
    WD -->|"强制截断/熔断"| EB
    TB_ -->|"成本超限"| KS

    %% 记忆流
    LLM -->|"上下文超载"| WM
    WM -->|"GC归档"| EM
    META -->|"环境扫描"| SG

    %% 自我进化流
    UPROMPT & REGTOOL -->|"热更新"| ROUTER

    %% 状态管理
    SM --> LF
    META --> SM

    style BrainstemLayer fill:#1a0a0a,stroke:#ff4444,color:#ffcccc
    style BrainLayer fill:#0a1a2e,stroke:#4488ff,color:#cce0ff
    style LimbsLayer fill:#0a2e1a,stroke:#44ff88,color:#ccffee
    style SecurityKernel fill:#2a0a0a,stroke:#ff6666,color:#ffdddd
    style CognitiveCore fill:#0a2a4e,stroke:#6699ff,color:#ddeeff
    style TriMemory fill:#1a2a3e,stroke:#5588cc,color:#ccddee
```

---

## 2. 工程目录与节点树结构 (Directory Tree Node)

脑干层（`src/core/`）编译后打包为不可变二进制；工作空间（`workspace/`）对 Agent 具有读写权限。同时保留并扩展现有 NagaAgent `autonomous/` 骨架结构。

```text
omni-operator-v2/
├── package.json
├── tsconfig.json
├── omni.config.json                    # [全局静态配置] 预算上限·黑名单正则·白名单目录
│
├── src/                                # ═══ 脑干层 ═══ (不可变代码，由人类工程师维护)
│   ├── index.ts                        # 进程入口 (初始化 EventBus, 启动 Watchdog)
│   │
│   ├── core/
│   │   ├── event_bus.ts                # 事件驱动总线 (PubSub + Cron + Alert 订阅)
│   │   ├── mcp_host.ts                 # MCP 协议宿主，动态解析工具 Schema
│   │   ├── llm_client.ts               # 多模型 SDK 封装 (Anthropic/OpenAI/Google)
│   │   ├── state_machine.ts            # SessionState 状态机 (IDLE→THINKING→EXECUTING)
│   │   ├── router.ts                   # 多Agent路由控制器 (任务分类·模型选择)
│   │   └── lease_manager.ts            # Lease/Fencing 单活多备管理器
│   │
│   ├── security/
│   │   ├── regex_firewall.ts           # Bash 注入·危险命令(rm -rf)阻断
│   │   ├── token_breaker.ts            # 账单熔断器 (单次任务>$5 强制kill)
│   │   ├── blast_radius.ts             # 爆炸半径控制 (ZFS/Btrfs 快照管理)
│   │   ├── kill_switch.ts              # 物理熔断 (异常IO/网络外发 → 全杀)
│   │   └── human_approval.ts           # 人类核准旁路 (Slack/手机推送)
│   │
│   ├── memory/
│   │   ├── sqlite_driver.ts            # 结构化数据 CRUD (Session日志·Token统计)
│   │   ├── chroma_driver.ts            # ChromaDB 向量检索 (RAG)
│   │   ├── graph_driver.ts             # 系统拓扑图 (JSON-Graph / Neo4j)
│   │   └── gc_engine.ts                # 上下文垃圾回收 (压缩·归档·截断)
│   │
│   └── watchdog/
│       ├── resource_monitor.ts         # CPU/RAM/Disk 资源监控
│       ├── loop_detector.ts            # 死循环检测 (连续错误计数)
│       ├── cost_monitor.ts             # API 成本实时追踪
│       └── daily_checkpoint.ts         # 日结归档 (24h全局Summarization)
│
├── workspace/                          # ═══ 大脑+手脚层 ═══ (Agent可修改区)
│   ├── prompts/                        # Agent 角色设定区 (支持热加载)
│   │   ├── immutable_dna.md            # [只读] 绝对底层安全规则
│   │   ├── meta_agent.md               # 元控节点决策逻辑
│   │   ├── router_agent.md             # 路由Agent决策逻辑
│   │   ├── sys_admin.md                # 运维Agent工具链说明
│   │   ├── developer.md                # 开发Agent角色规范
│   │   └── researcher.md               # 搜索研究Agent角色
│   │
│   ├── tools/                          # MCP 动态工具区
│   │   ├── built_in/                   # 内置基础工具
│   │   │   ├── os_bash.ts              # 带超时截断的 Bash 执行器
│   │   │   ├── file_ast.ts             # AST 精确文件编辑器
│   │   │   ├── web_scraper.ts          # Playwright 无头浏览器
│   │   │   ├── search_engine.ts        # Google/Tavily 搜索
│   │   │   ├── sleep_until.ts          # 条件/时间挂起
│   │   │   ├── schedule_cron.ts        # 定期巡检调度
│   │   │   ├── snapshot_manager.ts     # 快照创建/恢复
│   │   │   ├── systemd_manager.ts      # 后台进程管理
│   │   │   └── git_operator.ts         # Git 操作封装
│   │   └── plugins/                    # Agent 自主生成的扩展工具 (动态 import)
│   │       └── .gitkeep
│   │
│   ├── evolution/                      # 自我进化沙盒
│   │   ├── dev_sandbox/                # 隔离开发目录 (Docker/tmpfs)
│   │   ├── test_suite/                 # 自我验证测试用例
│   │   └── version_control/            # prompt/tool 版本历史 (git)
│   │
│   └── storage/                        # 运行期持久化数据
│       ├── omni_sqlite.db
│       ├── vector_db/
│       ├── graph_db/
│       └── daily_logs/                 # 日结归档日志
│
└── NagaAgent/                          # ═══ 现有项目集成层 ═══
    ├── autonomous/                     # 🟢 System Agent 自治闭环 (Phase 0 已实现)
    │   ├── system_agent.py             # 主循环：感知 → 规划 → 执行 → 评估
    │   ├── sensor.py / planner.py      # 感知器 / 规划器
    │   ├── evaluator.py / dispatcher.py # 评估器 / 派发器
    │   ├── monitor.py                  # 子代理执行监控器
    │   ├── release/controller.py       # 发布灰度控制器
    │   ├── state/workflow_store.py     # 工作流持久化 + Lease/Fencing
    │   ├── tools/
    │   │   ├── cli_adapter.py          # 🟢 CLI 统一适配器 (Phase 0 当前实现)
    │   │   ├── codex_adapter.py        # 🟢 Codex CLI/MCP 主执行器 (Codex-first v2)
    │   │   ├── claude_adapter.py       # 🟢 Claude Code 降级备选
    │   │   └── gemini_adapter.py       # 🟢 Gemini CLI 降级备选
    │   └── tools/subagent_runtime.py   # 🔴 Sub-Agent Runtime (Phase 3 目标态，当前未实现)
    ├── apiserver/                      # API 服务层 (FastAPI)
    ├── mcpserver/                      # MCP 工具注册与调度
    ├── memory/                         # 记忆 schema 与投影
    └── policy/                         # 策略引擎配置
```

**图例说明**：
- 🟢 **已实现** (Phase 0)：当前代码可运行
- 🟡 **部分实现** (Phase 1-2)：骨架存在，功能待增强
- 🔴 **未实现** (Phase 3)：本文档目标态设计
- ⚪ **已弃用**：保留兼容但不推荐使用

**Phase 0 → Phase 3 实施路径映射**：

| 目标态组件 (Phase 3) | 当前实现 (Phase 0) | 实施阶段 | 状态 |
|---------------------|-------------------|---------|------|
| **Sub-Agent Runtime** | CLI Adapter | Phase 0 | 🟢 CLI 过渡方案已实现 |
| Frontend Sub-Agent | Codex CLI | Phase 0 | 🟢 通过 CLI 调用实现 |
| Backend Sub-Agent | Codex CLI | Phase 0 | 🟢 通过 CLI 调用实现 |
| Ops Sub-Agent | Codex CLI | Phase 0 | 🟢 通过 CLI 调用实现 |
| **Scaffold Engine** | 无 | Phase 3 | 🔴 未实现 |
| **Execution Bridge** | CLI Adapter | Phase 0 | 🟢 CLI 适配器实现 |
| **Event Bus** | 轻量 Event Log | Phase 0 | 🟡 SQLite 事件存储 |
| **Meta-Agent** | System Agent | Phase 0 | 🟡 单实例主循环 |
| **Router** | CLI Selector | Phase 0 | 🟡 CLI 选择策略 |
| **Watchdog** | 无 | Phase 2 | 🔴 未实现 |
| **Immutable DNA** | Prompt 文件 | Phase 0 | 🟡 静态 Prompt |
| **Security Kernel** | Native Executor | Phase 0 | 🟡 基础沙箱 |

---

## 3. 核心机制交互时序图 (Sequence Diagrams)

### 3.1 事件驱动任务全链路 — 从系统事件到工具执行

定义事件总线接收告警后，Meta-Agent 拆解目标、Router 分发子Agent、工具执行与安全拦截的完整链路。

```mermaid
sequenceDiagram
    participant SysEvent as 系统事件源<br/>(CPU告警·日志Error·Cron)
    participant EB as Event Bus
    participant META as Meta-Agent<br/>(元控节点)
    participant ROUTER as Router<br/>(路由控制器)
    participant LLM as LLM Client<br/>(多模型)
    participant MCP as MCP Host
    participant SEC as Security Kernel
    participant OS as Host OS

    SysEvent->>EB: publish(event_type, payload)
    EB->>META: 订阅匹配 → 触发认知

    META->>META: 反思: 当前目标优先级?<br/>经验库 RAG 检索类似案例
    META->>ROUTER: dispatch_task(goal, sub_tasks[])

    loop 每个子任务
        ROUTER->>ROUTER: 选择角色(sys_admin/developer/researcher)
        ROUTER->>LLM: 组装 Payload<br/>(SystemPrompt[Cache] + Tools[Cache] + Message)

        loop ReAct 推理循环
            LLM-->>MCP: 返回 <tool_use> JSON
            MCP->>SEC: 安全校验(regex_firewall + blast_radius)

            alt 💥 触发安全规则
                SEC-->>MCP: ❌ Permission Denied
                MCP-->>LLM: <tool_result> Error
            else ✅ 校验通过
                MCP->>OS: 执行命令 (timeout=30s)
                OS-->>MCP: stdout/stderr
                MCP->>MCP: 截断算法 (Head200行 + Tail200行)
                MCP-->>LLM: <tool_result> 截断后结果
            end

            LLM->>LLM: 判断: 是否需要更多工具?
        end

        LLM-->>ROUTER: Final Answer
        ROUTER->>META: 子任务完成报告
    end

    META->>EB: 广播 TaskCompleted 事件
    META->>META: 生成复盘报告 → 写入 Episodic Memory
```

### 3.2 上下文垃圾回收与 RAG 归档 (Memory GC)

当 messages 数组 Token 超限时，触发后台小模型压缩、向量化归档、上下文瘦身的完整流程。

```mermaid
sequenceDiagram
    participant CTX as Context Window<br/>(Working Memory)
    participant GC as Memory GC Engine
    participant Haiku as 小模型<br/>(Claude 3.5 Haiku)
    participant SQLite as SQLiteDB
    participant Chroma as ChromaDB<br/>(向量库)
    participant Graph as Semantic Graph

    CTX->>CTX: 每轮循环检查 Token 长度

    opt 🔴 Token > 80,000 触发熔断
        CTX->>GC: 发送挂起信号 (Pause Session)
        GC->>CTX: 提取前50轮历史工具调用记录

        GC->>Haiku: "将以下试错过程压缩为300字复盘摘要"
        Haiku-->>GC: 返回 Markdown 摘要

        par 并行持久化
            GC->>Chroma: 向量化并长期存储 (供RAG检索)
            GC->>SQLite: 记录 Token 消耗与压缩点位
            GC->>Graph: 更新系统拓扑 (新发现的依赖关系)
        end

        GC->>CTX: messages.splice(0, 50) 删除冗长
        GC->>CTX: messages.unshift(摘要) 注入压缩记忆
        GC->>CTX: 解除挂起 (Resume Session)
    end
```

### 3.3 自我进化 CI/CD 闭环 — 双重沙盒验证

Agent 修改自身 Prompt 或工具代码时的安全闭环：发现痛点 → 切片克隆 → 沙盒测试 → 热更新 → 回滚保障。

```mermaid
sequenceDiagram
    participant Worker as Task Agent<br/>(发现痛点)
    participant META as Meta-Agent
    participant DEV as Dev Worker<br/>(开发者子Agent)
    participant SANDBOX as Docker Sandbox
    participant GIT as Git (版本控制)
    participant FS as File System
    participant WATCH as Chokidar<br/>(FS Watcher)
    participant LLM as LLM Client

    Worker->>META: 报告: "日志分析脚本效率低"<br/>或 "某段Prompt导致幻觉"

    Note over META,DEV: === 阶段一: 切片克隆 (Forking) ===
    META->>META: 风险评估: 修改范围·影响面
    META->>DEV: 派生独立开发者子Agent
    META->>FS: 复制代码/Prompt到 /tmp/agent_dev/
    META->>GIT: git branch auto/self-opt/{task_id}

    Note over META,DEV: === 阶段二: 沙盒修改与测试 ===
    DEV->>FS: 修改工具代码或 Prompt
    DEV->>SANDBOX: 在受限 Docker 中运行自动化测试
    SANDBOX-->>DEV: 测试结果 (通过/失败)

    alt ❌ 测试失败
        DEV->>META: 报告失败 + 错误日志
        META->>GIT: git branch -D (清理)
        META->>META: 搜索引擎查阅新方案 → 重试
    else ✅ 测试通过
        Note over META,LLM: === 阶段三: 热更新加载 ===
        DEV->>GIT: git commit "self-opt: 优化日志分析"
        DEV->>FS: 写入 workspace/tools/ 或 workspace/prompts/

        FS-->>WATCH: 触发 change 事件
        WATCH->>WATCH: 防抖处理 (Debounce 1000ms)
        WATCH->>LLM: reloadPrompt() 或 reloadTool()
        LLM->>LLM: 清理旧 Cache ID, 重新读取

        Note over META,LLM: === 阶段四: 运行时验证 ===
        META->>META: 监控新版本首10次任务成功率

        alt 📈 成功率正常
            META->>GIT: merge to main
            META->>META: 记录进化日志
        else 📉 失败率飙升 (>30%)
            META->>GIT: git revert → 回退稳定版本
            META->>WATCH: reloadPrompt(上一版本)
            META->>META: 记录回滚原因
        end
    end
```

### 3.4 长程运行防发散机制 — 反思与休眠

解决大模型"提示词漂移"和"死胡同"的防发散架构。

```mermaid
sequenceDiagram
    participant META as Meta-Agent
    participant TASK as Task Agent
    participant WD as Watchdog
    participant SEARCH as search_engine
    participant SLEEP as sleep_until
    participant DAILY as Daily Checkpoint
    participant EL as Event Log

    Note over META,EL: === 反思与重试机制 ===

    loop Task 执行
        META->>TASK: 派发子任务
        TASK->>TASK: 执行中...

        alt 连续报错 ≥5 次
            WD->>TASK: ⛔ 强制终止进程
            WD->>META: 通知: 子任务陷入死循环
            META->>SEARCH: 重新查阅资料 (错误信息)
            SEARCH-->>META: 新的解决方案
            META->>META: 生成新策略
            META->>TASK: 重新派发 (带新策略)
        end
    end

    Note over META,EL: === 条件休眠节省Token ===
    META->>SLEEP: sleep_until("日志出现Error")
    Note right of SLEEP: Agent挂起, 零Token消耗<br/>由EventBus监控日志
    SLEEP-->>META: 条件触发, 唤醒

    Note over META,EL: === 日结归档 (每24h) ===
    DAILY->>META: trigger_daily_checkpoint()
    META->>META: 总结过去24h的操作·学习·发现
    META->>EL: 写入日结日志 (Markdown)
    META->>META: 清空主上下文
    META->>META: 注入"昨日摘要" → 进入新一天
```

### 3.5 多Agent协作与Token经济调度（Tokenomics v2）

为防止长程运行中的“Token 破产”和上下文爆炸，系统必须启用四重拦截：

1. 网关层：Prompt 分层组装 + 缓存标记 + 预算校验。
2. 大模型调度层：任务分流到主模型/次模型/本地零成本模型。
3. 工具层：I/O 截断、结构化读取、Patch 写入约束。
4. 事件层：休眠监听替代轮询，空闲期间 Token 消耗归零。

Prompt 分层规范：

- Block 1（静态头部）：系统角色 + `CLAUDE.md` + MCP Tools Schema，约 10k tokens，`cache_control={"type":"ephemeral"}`。
- Block 2（长期记忆）：过去 24h 精简摘要，第二个 `ephemeral`。
- Block 3（动态窗口）：最近 3~5 轮对话，禁止缓存；超过 10k tokens 软阈值强制 GC。

异构模型分流规范：

| 任务类型 | 绑定模型 | 成本评级 | 典型场景 |
|---|---|---|---|
| 主控路由/代码生成 | `{用户设置主要模型}` | 极高 | Router 拆解、核心代码修改 |
| 后台清理/记忆压缩 | `{次要模型}` | 低 | 对话树压缩、乱码清洗 |
| 重度日志解析 | 本地开源模型 | 零 | 几万行日志关键栈提取 |

```mermaid
sequenceDiagram
    participant META as Meta-Agent
    participant ROUTER as Router
    participant GW as LLM Gateway
    participant BUDGET as Token Budget
    participant PRIMARY as Primary Model
    participant SECONDARY as Secondary Model
    participant LOCAL as Local OSS Model
    participant GC as GC Engine
    participant EL as Event Log

    META->>ROUTER: 新任务(type, severity, io_cost_hint)
    ROUTER->>GW: route(task_spec)
    GW->>BUDGET: 预算检查 + 并发配额检查

    alt task == "code_generation"
        GW->>PRIMARY: 发送 Block1+Block2+Block3
        PRIMARY-->>GW: tool_calls / patch plan
    else task == "memory_cleanup"
        GW->>SECONDARY: 压缩历史上下文
        SECONDARY-->>GW: 24h 精简摘要
    else task == "heavy_log_parse"
        GW->>LOCAL: 本地日志解析
        LOCAL-->>GW: 关键错误栈
    end

    GW->>GW: 动态窗口 > 10k?
    alt 超阈值
        GW->>GC: 强制触发上下文 GC
        GC-->>GW: 回注摘要 + 裁剪窗口
    end

    GW-->>ROUTER: 结果 + 成本报告
    ROUTER-->>META: 执行结果
    GW->>EL: emit(TokenBudgetUpdated)
```

### 3.6 安全控制全链路 — KillSwitch 与人类核准

```mermaid
sequenceDiagram
    participant AGENT as Agent
    participant MCP as MCP Host
    participant SEC as Security Kernel
    participant APPROVAL as Human Approval<br/>(Slack/手机)
    participant KS as KillSwitch<br/>(独立进程)
    participant SNAP as Snapshot Manager

    AGENT->>MCP: tool_use(rm -rf /var/log/old)

    MCP->>SEC: 正则匹配检查
    SEC->>SEC: 匹配黑名单: rm -rf ✓

    SEC->>APPROVAL: 🚨 推送审批请求<br/>"Agent尝试删除 /var/log/old"
    Note right of APPROVAL: Agent 挂起等待

    alt 管理员批准 (Y)
        APPROVAL-->>SEC: APPROVED
        SEC->>SNAP: create_snapshot("pre-delete")
        SNAP-->>SEC: snapshot_id
        SEC-->>MCP: 放行执行
    else 管理员拒绝 (N)
        APPROVAL-->>SEC: DENIED
        SEC-->>MCP: Permission Denied
        MCP-->>AGENT: <tool_result> Error: 需要人工批准
    end

    Note over KS: === 独立物理熔断 ===
    KS->>KS: 持续监控网络IO + 磁盘IO
    alt 检测到异常大规模数据外发
        KS->>KS: ⚡ 立即杀掉所有Agent进程
        KS->>KS: 冻结网络出口
    end
```

### 3.7 多Agent并发灾难防护（Daemon Layer）

横向扩展子 Agent 时，守护进程层必须启用四道隔离墙：

1. 文件指纹乐观锁：`read_file` 返回 `file_hash`，`edit_file` 必传 `original_file_hash`，冲突即硬错误。
2. 全局状态互斥锁：`npm install`、`apt-get`、`git branch`、`systemctl restart` 等动作必须串行。
3. Router 仲裁熔断：`MAX_DELEGATE_TURNS = 3`，超限后冻结并进入人工裁决。
4. API 令牌桶流控：`MAX_CONCURRENT_API_CALLS` 限流，超额请求排队，防 429 雪崩。

```mermaid
flowchart TB
    subgraph DaemonLayer["Daemon Layer 并发防护"]
        LOCK["Optimistic File Lock<br/>read_hash / write_hash_check"]
        MUTEX["Global State Mutex<br/>MUTEX_GLOBAL_STATE"]
        ARBITER["Router Arbiter<br/>MAX_DELEGATE_TURNS=3"]
        BUCKET["Token Bucket Gateway<br/>MAX_CONCURRENT_API_CALLS"]
        QUEUE["Serial Execution Queue"]
        HITL["Human-in-the-Loop"]
    end

    AGENTS["Parallel Agents"] --> LOCK
    LOCK -->|local writes| QUEUE
    AGENTS --> MUTEX
    MUTEX -->|global actions| QUEUE
    AGENTS --> ARBITER
    ARBITER -->|conflict>3| HITL
    AGENTS --> BUCKET
    BUCKET -->|rate-limited calls| LLMAPI["LLM Providers"]
    QUEUE --> HOST["Physical Host Mutations"]
```

---

## 4. 数据存储设计 (ER Diagram)

使用 SQLite 持久化关系型数据，ChromaDB 持久化向量数据，JSON-Graph 维护系统拓扑。

```mermaid
erDiagram
    SESSION {
        string session_id PK
        string status "IDLE|RUNNING|SLEEPING|EVOLVING"
        string active_agent "meta|sys_admin|developer|researcher"
        int total_input_tokens
        int total_output_tokens
        float total_cost_usd
        datetime created_at
        datetime last_active_at
    }

    MESSAGE_LOG {
        string msg_id PK
        string session_id FK
        string role "user|assistant|system|tool"
        string agent_role "meta|sys_admin|developer"
        text content "JSON block or text"
        boolean is_summarized
        int token_count
        datetime timestamp
    }

    TOOL_EXECUTION {
        string exec_id PK
        string session_id FK
        string tool_name "os_bash|file_ast|search_engine|..."
        string risk_level "read_only|write_repo|deploy|secrets"
        text input_args "JSON"
        text output_result "JSON truncated"
        int exit_code
        float duration_ms
        boolean was_blocked "安全拦截"
        string approval_status "auto|pending|approved|denied"
        datetime executed_at
    }

    VECTOR_MEMORY {
        string vector_id PK
        string session_id FK
        string memory_type "episodic|skill|error_pattern"
        text markdown_summary "LLM生成的复盘"
        vector embeddings "dim=1536"
        float confidence
        datetime created_at
    }

    EVOLUTION_LOG {
        string evo_id PK
        string target_type "prompt|tool|config"
        string target_path "workspace/prompts/sys_admin.md"
        text change_diff "git diff"
        string test_result "pass|fail"
        string deploy_status "hot_loaded|reverted|pending"
        string git_commit_sha
        datetime evolved_at
    }

    DAILY_CHECKPOINT {
        string checkpoint_id PK
        date checkpoint_date
        text summary_markdown "24h工作摘要"
        int tasks_completed
        int tasks_failed
        float tokens_consumed
        float cost_usd
        text lessons_learned "JSON array"
    }

    TOKEN_BUDGET {
        string budget_id PK
        date budget_date
        string model_tier "haiku|sonnet|opus"
        int allocated_tokens
        int consumed_tokens
        float allocated_usd
        float consumed_usd
        boolean hard_limit_hit
    }

    SESSION ||--o{ MESSAGE_LOG : contains
    SESSION ||--o{ TOOL_EXECUTION : executes
    SESSION ||--o{ VECTOR_MEMORY : archives
    SESSION ||--o{ EVOLUTION_LOG : evolves
    DAILY_CHECKPOINT ||--o{ TOKEN_BUDGET : tracks
```

---

## 5. 自治状态机 (State Machine)

融合现有 SDLC 状态机与新增的自我进化、休眠、日结状态。

```mermaid
stateDiagram-v2
    [*] --> Initializing: 守护进程启动

    state "🟢 正常运行态" as NormalOps {
        Initializing --> Ready: Watchdog·EventBus·Memory 就绪
        Ready --> Sensing: 事件触发 / Cron定时
        Sensing --> Planning: 发现优化点 / 告警事件
        Sensing --> Ready: 无需处理
        Planning --> Dispatching: 生成子任务
        Dispatching --> Executing: 子Agent启动
        Executing --> Evaluating: 执行完成
        Evaluating --> Merging: 评审+测试通过
        Evaluating --> Dispatching: 需返工(带反馈)
        Merging --> Ready: 合并成功
        Merging --> Ready: 合并失败(回滚)
    }

    state "🔵 自我进化态" as EvolutionOps {
        Ready --> SelfAnalyzing: 发现自身痛点
        SelfAnalyzing --> Forking: 风险评估通过
        Forking --> SandboxTesting: 沙盒修改完成
        SandboxTesting --> HotReloading: 测试通过
        SandboxTesting --> Ready: 测试失败(放弃)
        HotReloading --> Monitoring10: 热加载成功
        Monitoring10 --> Ready: 10次任务成功率正常
        Monitoring10 --> Reverting: 失败率>30%
        Reverting --> Ready: 回退到稳定版本
    }

    state "🟡 休眠态" as SleepOps {
        Ready --> Sleeping: sleep_until(条件)
        Sleeping --> Ready: 条件触发唤醒
    }

    state "🟠 日结态" as DailyOps {
        Ready --> DailyCheckpoint: 24h定时触发
        DailyCheckpoint --> ContextReset: 归档完成
        ContextReset --> Ready: 注入昨日摘要
    }

    state "🔴 终止态" as TerminalStates {
        Ready --> Killed: KillSwitch触发
        Executing --> Killed: KillSwitch触发
        Ready --> ShuttingDown: 手动停止
        Initializing --> FailedInit: 自检失败
    }
```

---

## 6. 模块化原子规范 (Atomic Module Spec)

每个模块必须满足以下原子化接口契约，确保可独立测试、可热替换、可降级。

### 6.1 模块注册契约

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `module_id` | string | ✅ | 全局唯一标识 (如 `tools.os_bash`) |
| `module_type` | enum | ✅ | `tool` / `agent` / `memory` / `security` / `infra` |
| `risk_level` | enum | ✅ | `read_only` / `write_repo` / `deploy` / `secrets` / `self_modify` |
| `input_schema` | JSONSchema | ✅ | 输入参数的严格 Schema 定义 |
| `output_schema` | JSONSchema | ✅ | 输出格式的严格 Schema 定义 |
| `timeout_ms` | int | ✅ | 默认超时毫秒数 |
| `retry_policy` | object | ❌ | `{max_attempts, backoff_ms, retryable_errors[]}` |
| `health_check` | function | ✅ | 返回 `{status: "ok"/"degraded"/"down"}` |
| `dependencies` | string[] | ❌ | 依赖的其他 module_id 列表 |
| `hot_reloadable` | boolean | ✅ | 是否支持运行时热替换 |

### 6.2 工具执行契约 (Tool Contract)

每次工具调用必须携带以下治理字段（承接 07 文档 §12.1）：

```typescript
interface ToolCallEnvelope {
  // === 调用标识 ===
  tool_name: string;
  call_id: string;               // UUID
  trace_id: string;              // 全链路追踪
  workflow_id: string;           // 所属工作流

  // === 安全治理 ===
  risk_level: "read_only" | "write_repo" | "deploy" | "secrets";
  fencing_epoch: number;         // 防双主写入
  idempotency_key: string;       // 幂等键
  caller_role: string;           // 调用方角色

  // === 执行参数 ===
  validated_args: Record<string, unknown>;
  timeout_ms: number;
  input_schema_version: string;
  execution_scope: "local" | "global"; // local=文件级变更, global=环境级变更
  requires_global_mutex?: boolean;      // global 动作必须为 true
  original_file_hash?: string;          // 写文件时必填，用于乐观锁
  queue_ticket?: string;                // 进入串行队列后的票据编号

  // === 预算控制 ===
  estimated_token_cost: number;
  budget_remaining: number;
  io_truncation_policy?: {
    max_chars: number;      // 如 8000
    head_chars: number;     // 如 3000
    tail_chars: number;     // 如 3000
  };
}
```

### 6.3 MCP 工具生命周期

```mermaid
flowchart LR
    A["📦 工具脚本<br/>(*.ts)"] -->|"动态 import()"| B["📋 Schema 解析<br/>(参数·返回值)"]
    B -->|"注册"| C["🗂️ Tool Registry"]
    C -->|"健康检查"| D{"✅ Available?"}
    D -->|Yes| E["🔧 就绪可用"]
    D -->|No| F["⚠️ 降级标记"]
    E -->|"调用时"| G["🛡️ 安全校验"]
    G -->|"通过"| H["⚡ 执行"]
    G -->|"拦截"| I["🚫 Denied"]
    H -->|"超时"| J["⏰ 强制终止"]
    H -->|"完成"| K["📊 结果截断"]
    K --> L["📝 写入 Event Log"]

    style A fill:#2a4a2a,stroke:#66aa66
    style G fill:#4a2a2a,stroke:#aa6666
    style L fill:#2a2a4a,stroke:#6666aa
```

### 6.4 Prompt Envelope 规范 (Caching + GC)

```typescript
interface PromptEnvelope {
  block_static_header: {
    content: string;
    cache_control: { type: "ephemeral" }; // Block 1
    token_budget_hint: 10000;
  };
  block_long_term_memory: {
    content: string;
    cache_control: { type: "ephemeral" }; // Block 2
  };
  block_dynamic_window: {
    messages: Array<{ role: string; content: string }>; // Block 3
    cache_control?: never; // 禁止缓存标记
    soft_token_limit: 10000;
  };
}
```

执行规则：

1. Block 3 超过 `soft_token_limit` 时，必须先执行 GC，再进入主模型调用。
2. `sleep_and_watch(log_file, regex)` 进入休眠时，释放动态窗口内存，仅保留可恢复摘要。
3. 恢复唤醒后重新组装 `PromptEnvelope`，禁止直接恢复旧长上下文。

---

## 7. 项目落地 8 周敏捷开发排期 (Gantt Chart)

对齐 `07-autonomous-agent-sdlc-architecture.md` 的 Phase 0-4 里程碑，扩展脑干层与自我进化能力。

```mermaid
gantt
    title Omni-Operator v2.0 全景研发排期 (8 Weeks)
    dateFormat YYYY-MM-DD
    axisFormat %m-%d

    section Phase 0 (W1-W2): 守护进程基座
    初始化 Node/TS 工程环境           :done,    p0a, 2026-02-23, 1d
    封装多模型 LLM Client             :active,  p0b, 2026-02-24, 2d
    实现 Prompt Caching 标记逻辑      :         p0c, 2026-02-26, 2d
    构建 Event Bus 事件总线           :         p0d, 2026-02-28, 2d
    实现 State Machine 状态流转       :         p0e, 2026-03-02, 2d
    Watchdog 资源监控进程             :         p0f, 2026-03-04, 2d
    Immutable DNA 安全规则加载        :         p0g, 2026-03-06, 1d
    集成现有 NagaAgent autonomous/    :         p0h, 2026-03-07, 1d

    section Phase 1 (W3-W4): MCP工具链与安全
    搭建 MCP Host 本地服务端          :         p1a, 2026-03-09, 2d
    开发 os_bash 工具(含截断算法)     :         p1b, 2026-03-11, 2d
    开发 file_ast 精确编辑器          :         p1c, 2026-03-13, 2d
    开发 web_scraper (Playwright)     :         p1d, 2026-03-15, 1d
    Regex Firewall 安全拦截器         :         p1e, 2026-03-16, 2d
    Token Breaker 账单熔断            :         p1f, 2026-03-18, 1d
    Human Approval 审批旁路           :         p1g, 2026-03-19, 2d
    KillSwitch 物理熔断器             :         p1h, 2026-03-21, 1d

    section Phase 2 (W5-W6): 记忆与路由
    集成 SQLite 存储对话树            :         p2a, 2026-03-23, 2d
    GC Engine 上下文压缩归档          :         p2b, 2026-03-25, 2d
    ChromaDB RAG 向量检索             :         p2c, 2026-03-27, 2d
    Semantic Graph 系统拓扑           :         p2d, 2026-03-29, 1d
    Router Agent 多任务分派           :         p2e, 2026-03-30, 2d
    Token Budget 经济调度             :         p2f, 2026-04-01, 1d
    sleep_until 条件休眠              :         p2g, 2026-04-02, 1d
    Daily Checkpoint 日结归档         :         p2h, 2026-04-03, 2d

    section Phase 3 (W7-W8): 自我进化与验收
    Chokidar 文件监听热加载           :         p3a, 2026-04-06, 2d
    动态 import() 插件注册            :         p3b, 2026-04-08, 2d
    Sandbox 沙盒测试环境              :         p3c, 2026-04-10, 2d
    自我进化 CI/CD 全链路             :         p3d, 2026-04-12, 2d
    Blast Radius 快照管理             :         p3e, 2026-04-14, 1d
    72h 无人值守耐久测试              :crit,    p3f, 2026-04-15, 3d
    DoD 自动化验收流水线              :         p3g, 2026-04-18, 2d
```

---

## 8. 交付基线要求 (Exit Criteria)

### 8.1 功能验收

| # | 验收项 | 验证方法 | 通过标准 |
|---|--------|----------|----------|
| 1 | **事件驱动** | 模拟 CPU 告警事件 | Agent 自动响应并执行诊断 |
| 2 | **工具执行** | Agent 使用 `os_bash` 遍历系统 | 找到指定 Log 并通过 `file_ast` 修复代码 |
| 3 | **防爆性** | 执行输出 10 万行的 Bash 脚本 | Context 不崩溃，精确截断 |
| 4 | **记忆持久** | 触发 GC 后检查 ChromaDB | 压缩摘要可被 RAG 成功检索 |
| 5 | **自我进化** | Agent 修改自己的 `sys_admin.md` | 下一条交互展现新认知，进程无需重启 |
| 6 | **安全拦截** | 发送 `rm -rf /` 命令 | 被 Regex Firewall 拦截，推送审批 |
| 7 | **条件休眠** | 调用 `sleep_until(Error出现)` | Agent 挂起零 Token，条件满足后唤醒 |
| 8 | **日结归档** | 运行 24h+ | 自动生成日结摘要，上下文重置 |
| 9 | **回滚保障** | 自我进化后失败率飙升 | 自动 git revert 回退稳定版本 |

### 8.2 非功能验收

| 指标 | 目标 | 统计窗口 |
|------|------|----------|
| WorkflowSuccessRate | ≥ 85% | 7天滚动 |
| CanaryDecisionAccuracy | ≥ 95% | 人工复核真值集 |
| RetrievalP95 | ≤ 250ms | 热路径 |
| PromptOOMRate | ≤ 0.1% | 按请求数 |
| 72h 无人值守 | 零崩溃 | 连续运行 |

### 8.3 必要交付物

1. `doc/gemin-结构图.md` (本文档)
2. `doc/07-autonomous-agent-sdlc-architecture.md`
3. `autonomous/state_machine.md`
4. `memory/schema.sql`
5. `policy/gate_policy.yaml`
6. `policy/slot_policy.yaml`
7. `config/retrieval_budget.yaml`
8. `runbooks/rollback.md`
9. `runbooks/incident.md`
10. `scripts/dod_check.ps1`
