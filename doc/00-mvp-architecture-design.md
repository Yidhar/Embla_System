# NagaAgent 多Agent自治架构设计文档（修订版）

---
**文档类型**：As-Is 实施文档（Phase 0 MVP）
**实施状态**：✅ 已实现（autonomous/ 模块）
**最后验证**：2026-02-22
**Codex 策略版本**：v2 (Codex-first 主执行路径)
**目标态参考**：`00-omni-operator-architecture.md` (Sub-Agent Runtime, Phase 3)
---

> **核心变更**：MVP 阶段采用 **单 System Agent + 外部 Agent CLI 工具** 模型。
> 编码工作由 System Agent 通过 **Codex CLI / Codex MCP（主路径）** + Claude Code / Gemini CLI（降级备选）以工具调用形式完成。
> **文档定位**：本文是 `doc/07-autonomous-agent-sdlc-architecture.md` 的 Phase 0（MVP）实施稿，目标态约束以 07 文档为准。
> **演进路径**：Phase 0 (CLI Tools) → Phase 1-2 (增强监控) → Phase 3 (Sub-Agent Runtime)

---

## 1. 现有文档审阅摘要

### 1.1 现有架构四面体

| 平面 | 职责 | 文档引用 |
|------|------|----------|
| **控制面** | 编排、策略、质量门禁 | [§5 总体架构](file:///E:/Programs/NagaAgent/doc/07-autonomous-agent-sdlc-architecture.md#L68) |
| **执行面** | 沙箱执行、工具调用、测试 | [§12 工具执行治理](file:///E:/Programs/NagaAgent/doc/07-autonomous-agent-sdlc-architecture.md#L441) |
| **记忆面** | 事件溯源、投影裁决 | [§9 数据模型](file:///E:/Programs/NagaAgent/doc/07-autonomous-agent-sdlc-architecture.md#L273) |
| **运维面** | 可观测、评测、审计 | [§15 可观测](file:///E:/Programs/NagaAgent/doc/07-autonomous-agent-sdlc-architecture.md#L523) |

### 1.2 Gap Analysis

| Gap | 说明 | 本文解决方式 |
|-----|------|-------------|
| 多Agent通信 | 文档定义角色，未定义通信协议 | System Agent 直接调用 CLI 工具，无需 Agent 间通信 |
| 自我优化闭环 | 缺少对自身代码的分析→优化→验证 | System Agent 感知→规划→CLI执行→评审闭环 |
| Agent生命周期 | 缺少注册/心跳/升级 | MVP 单实例，随 ServiceManager 管理 |
| 编码执行模式 | 执行面抽象但无具体实现路径 | **Agent CLI 作为工具调用**（核心创新） |

---

## 2. MVP 架构：System Agent + Agent CLI Tools

### 2.1 架构总览

```mermaid
flowchart TB
    subgraph Core["NagaAgent Core"]
        SM["ServiceManager<br/>(main.py)"]
        Config["config.json<br/>autonomous 配置"]
    end

    subgraph SA["System Agent (单实例常驻)"]
        Sensor["感知器 Sensor<br/>· 代码质量扫描<br/>· 性能瓶颈检测<br/>· 日志异常分析"]
        Planner["规划器 Planner<br/>· 优化任务生成<br/>· 风险评估<br/>· 优先级排序"]
        Dispatcher["任务派发器 Dispatcher<br/>· CLI 选择策略<br/>· 任务格式化<br/>· 超时管理"]
        Monitor["执行监控器 Monitor<br/>· stdout 流监听<br/>· 停滞检测<br/>· 进度估算"]
        Evaluator["评估器 Evaluator<br/>· diff 审查<br/>· 测试验证<br/>· 合并/回滚决策"]
    end

    subgraph CLI["Agent CLI Tool Layer (外部进程调用)"]
        Adapter["CLI Adapter<br/>(统一接口)"]
        Codex["Codex CLI<br/>codex --full-auto"]
        Claude["Claude Code<br/>claude -p --dangerously-skip-permissions"]
        Gemini["Gemini CLI<br/>gemini -p"]
    end

    subgraph Tools["Shared Infra"]
        Git["Git Operator<br/>branch/diff/merge"]
        TestRunner["Test Runner<br/>pytest/ruff"]
        EventLog["Event Log<br/>(轻量 SQLite/JSON)"]
    end

    SM -->|"启动(如配置启用)"| SA
    Config --> SM

    Sensor --> Planner
    Planner --> Dispatcher
    Dispatcher --> Adapter
    Adapter --> Codex
    Adapter --> Claude
    Adapter --> Gemini
    Dispatcher --> Monitor
    Monitor -->|"实时状态上报"| Evaluator

    Codex -->|"代码变更"| Evaluator
    Claude -->|"代码变更"| Evaluator
    Gemini -->|"代码变更"| Evaluator

    Evaluator --> Git
    Evaluator --> TestRunner
    Evaluator --> EventLog

    SA --> EventLog

    style Core fill:#1a1a2e,stroke:#16213e,color:#e94560
    style SA fill:#0f3460,stroke:#533483,color:#e2e2e2
    style CLI fill:#533483,stroke:#e94560,color:#e2e2e2
    style Tools fill:#16213e,stroke:#0f3460,color:#e2e2e2
```

### 2.2 核心设计决策

> [!IMPORTANT]
> **为什么不在 MVP 引入独立 Coding Agent？**

| 因素 | 独立 Coding Agent | Agent CLI 工具调用 |
|------|-------------------|-------------------|
| 开发成本 | 需实现完整 Agent 框架 + 消息总线 | 仅需 CLI 适配器 (subprocess) |
| 编码能力 | 需从零构建 LLM→代码 管线 | **直接复用** Codex/Claude/Gemini 成熟能力 |
| 模型选择弹性 | 绑定单一模型 | 多模型竞争，择优使用 |
| 安全隔离 | 需自建沙箱 | CLI 自带沙箱 (Codex sandbox, Claude permissions) |
| 可维护性 | 大量自有代码 | 外部工具持续演进，自身代码极少 |

---

## 3. Agent CLI 统一适配器

### 3.1 适配器接口定义

```python
# autonomous/tools/cli_adapter.py

@dataclass
class CliTaskSpec:
    """发送给 Agent CLI 的任务规格"""
    task_id: str
    instruction: str          # 自然语言任务描述
    working_dir: str          # 工作目录
    target_files: list[str]   # 允许修改的文件/目录白名单
    context_files: list[str]  # 参考上下文文件
    timeout_seconds: int = 0  # 0 = 自适应(由System Agent决策), >0 = 硬上限
    complexity_hint: str = "medium"  # low/medium/high/epic - 影响超时预估

@dataclass
class CliExecutionStatus:
    """CLI 实时执行状态（由监控器产出）"""
    elapsed_seconds: float
    last_stdout_line: str
    stdout_line_count: int
    is_stalled: bool          # 超过 stall_threshold 无新输出
    files_touched: list[str]  # 通过 git status 实时检测
    estimated_progress: float # 0.0 ~ 1.0, 基于输出模式推断

@dataclass
class CliTaskResult:
    """Agent CLI 执行结果"""
    task_id: str
    cli_name: str             # "codex" | "claude" | "gemini"
    exit_code: int
    stdout: str
    stderr: str
    files_changed: list[str]  # git diff 检测到的变更文件
    duration_seconds: float
    success: bool
    execution_snapshots: list[CliExecutionStatus]  # 过程中采样的状态快照

class AgentCliAdapter(ABC):
    """Agent CLI 统一适配器基类"""

    @abstractmethod
    async def execute(self, spec: CliTaskSpec,
                      on_status: Callable[[CliExecutionStatus], None] = None
                      ) -> CliTaskResult:
        """执行编码任务，支持实时状态回调"""

    @abstractmethod
    async def check_available(self) -> bool:
        """检测该 CLI 是否已安装可用"""
```

### 3.2 CLI 调用方式与优先级（Codex-first 策略 v2）

> [!IMPORTANT]
> **策略更新**（2026-02-22）：Codex 已从"验证降级"升级为**主执行路径**。

| CLI | 非交互命令 | 关键参数 | 优先级 | 用途 |
|-----|-----------|---------|--------|------|
| **Codex CLI** | `codex --approval-mode full-auto -q "instruction"` | `--full-auto` 无需确认 | **P0 主路径** | 所有编码任务 |
| **Codex MCP** | `ask-codex`（MCP Tool） | `workspace-write + on-failure` | **P0 主路径** | 编码任务（MCP 模式） |
| **Claude Code** | `claude -p "instruction" --dangerously-skip-permissions` | `-p` 非交互管道模式 | P1 降级 | Codex 不可用时 |
| **Gemini CLI** | `gemini -p "instruction"` | `-p` 非交互管道模式 | P2 降级 | Claude 不可用时 |

**执行策略**：
- **编码任务**：优先 Codex CLI/MCP → 降级 Claude → 降级 Gemini
- **诊断任务**：Codex MCP (read-only) → Claude
- **审阅任务**：Codex MCP (read-only) → Claude

> [!NOTE]
> 所有 CLI 调用都在 `auto/<task_id>` Git 分支上执行，变更隔离在分支内。

### 3.3 CLI 选择策略（Codex-first 实现）

```python
# autonomous/tools/cli_selector.py

class CliSelectionStrategy:
    """根据任务特性和可用性选择最优 CLI（Codex-first）"""

    def select(self, spec: CliTaskSpec, available: list[str]) -> str:
        # 优先级（v2 策略，2026-02-22）：
        # 1. 编码任务强制 Codex（codex > codex-mcp）
        # 2. Codex 不可用时降级到 Claude
        # 3. Claude 不可用时降级到 Gemini
        # 4. 所有不可用时返回错误

        if spec.task_type == "coding":
            if "codex" in available:
                return "codex"
            elif "codex-mcp" in available:
                return "codex-mcp"
            elif "claude" in available:
                return "claude"
            elif "gemini" in available:
                return "gemini"
            else:
                raise RuntimeError("No coding CLI available")

        # 诊断/审阅任务优先 read-only 模式
        if spec.task_type in ["diagnosis", "review"]:
            if "codex-mcp" in available:
                return "codex-mcp"  # read-only mode
            elif "claude" in available:
                return "claude"

        # 默认降级链
        return available[0] if available else None
```

### 3.4 Codex 执行模式详解

#### 3.4.1 Codex CLI 模式（主路径）

**适用场景**：
- 完整代码生成/重构任务
- 需要多文件协同修改
- 需要自动测试验证

**调用示例**：
```bash
codex --approval-mode full-auto \
      --working-dir /path/to/repo \
      -q "重构 user_service.py，将同步调用改为异步"
```

**优势**：
- 完整的沙箱环境
- 自动 Git 分支管理
- 内置测试验证

#### 3.4.2 Codex MCP 模式（主路径）

**适用场景**：
- 需要与其他 MCP 工具协同
- 需要精细控制执行参数
- 需要结构化输出

**调用示例**：
```python
result = await mcp_manager.unified_call(
    service_name="codex-cli",
    tool_call={
        "tool_name": "ask-codex",
        "arguments": {
            "prompt": "重构 user_service.py",
            "sandboxMode": "workspace-write",
            "approvalPolicy": "on-failure"
        }
    }
)
```

**优势**：
- 统一的 MCP 工具链
- 结构化错误处理
- 支持 read-only 诊断模式

#### 3.4.3 降级场景处理

**触发条件**：
1. Codex CLI/MCP 不可用（未安装、鉴权失败）
2. Codex 执行超时或崩溃
3. Codex 返回不可恢复错误

**降级流程**：
```python
async def execute_with_fallback(spec: CliTaskSpec):
    try:
        return await codex_adapter.execute(spec)
    except CodexUnavailableError:
        logger.warning("Codex unavailable, falling back to Claude")
        return await claude_adapter.execute(spec)
    except ClaudeUnavailableError:
        logger.warning("Claude unavailable, falling back to Gemini")
        return await gemini_adapter.execute(spec)
```

**历史变更记录**：
- **v1 (2026-02-20 之前)**：Codex MCP 仅用于验证阶段降级
- **v2 (2026-02-22 当前)**：Codex CLI/MCP 升级为主执行路径
2. 调用工具：`ask-codex`，输入包含 `git diff`、失败测试日志、目标文件列表。
3. 推荐参数：`sandboxMode=read-only`、`approvalPolicy=on-failure`。
4. 输出结构化为：`issue`、`evidence`、`suggested_fix`、`risk`。
5. 降级结果必须经过本地 `run_tests + run_lint` 二次验证后才能晋升。

退出条件：
1. 结果可执行且验证通过：回到主流程继续评审与合并。
2. MCP 不可用或建议无效：进入 `TaskRetrying` 或 `TaskFailed`。

---

## 4. 核心时序图

### 4.1 自我优化主循环（System Agent + CLI Tools）

```mermaid
sequenceDiagram
    autonumber
    participant Timer as Cron Timer
    participant SA as System Agent
    participant Git as Git Operator
    participant Adapter as CLI Adapter
    participant Mon as Execution Monitor
    participant CLI as Agent CLI<br/>(Codex/Claude/Gemini)
    participant Test as Test Runner
    participant EL as Event Log

    Note over Timer,EL: === 阶段一：感知与分析 ===

    Timer->>SA: trigger_cycle()
    activate SA
    SA->>SA: sensor.scan_codebase()<br/>ruff check + pytest --cov<br/>+ 性能指标采集
    SA->>SA: sensor.scan_logs(window=24h)<br/>错误模式 + 异常频率
    SA->>EL: emit(AnalysisCompleted, {findings, score})

    Note over Timer,EL: === 阶段二：规划与决策 ===

    SA->>SA: planner.generate_tasks(findings)
    SA->>SA: planner.risk_assess(tasks)
    SA->>SA: planner.prioritize(tasks)
    SA->>SA: planner.estimate_complexity(tasks)
    SA->>EL: emit(PlanDrafted, {tasks, risk_level})

    Note over Timer,EL: === 阶段三：通过 CLI 执行编码 ===

    loop 每个优化任务
        SA->>Git: create_branch("auto/{task_id}")
        Git-->>SA: branch_ready

        SA->>Adapter: select_cli(task_spec)
        Adapter-->>SA: selected: "claude"

        SA->>SA: compute_timeout(complexity_hint)<br/>low=30m, medium=1h,<br/>high=2h, epic=4h

        SA->>Adapter: execute(task_spec, on_status)
        activate Adapter
        Adapter->>CLI: subprocess.Popen(cli_command)
        Adapter->>Mon: start_monitoring(proc)
        activate Mon

        loop 实时监控 (每10秒)
            Mon->>Mon: read_stdout_nonblocking()
            Mon->>Git: git status --short
            Mon->>Mon: detect_stall + estimate_progress
            Mon->>SA: on_status(CliExecutionStatus)
            SA->>EL: emit(CliProgress, {progress})

            alt 停滞检测
                SA->>SA: evaluate: 有文件产出?
                alt 有产出继续等待
                    SA->>Mon: extend_patience(+5min)
                else 无产出判定卡死
                    SA->>CLI: terminate()
                end
            end
        end

        CLI-->>Adapter: exit_code, stdout
        deactivate Mon
        deactivate Adapter
        Adapter-->>SA: CliTaskResult{success, snapshots[]}

        SA->>EL: emit(CliExecutionCompleted, {task_id, cli, duration})

        Note over Timer,EL: === 阶段四：评审与验证 ===

        SA->>Git: diff("auto/{task_id}", "main")
        Git-->>SA: diff_content, files_changed

        SA->>SA: evaluator.assess_diff_scope(diff, spec)<br/>自适应: 与任务预期对比

        SA->>Test: run_tests()
        Test-->>SA: TestResult{pass_rate, coverage}

        SA->>Test: run_lint()
        Test-->>SA: LintResult{errors}

        alt 评审通过 and 测试通过
            SA->>Git: merge("auto/{task_id}", "main")
            SA->>Git: delete_branch("auto/{task_id}")
            SA->>EL: emit(ChangePromoted, {task_id})
        else 主CLI不可用 and codex_mcp_enabled
            SA->>EL: emit(VerificationDegradedToCodexMCP, {task_id})
            SA->>SA: verifier.invoke_codex_mcp()
            Note right of SA: 仅做审阅/诊断建议，不直接改主分支
        else 评审/测试失败 and 可重试
            SA->>EL: emit(TaskRetrying, {task_id, feedback})
            Note right of SA: 带反馈重新调用 CLI
        else 彻底失败
            SA->>Git: delete_branch("auto/{task_id}")
            SA->>EL: emit(TaskFailed, {task_id, reason})
        end
    end
    deactivate SA
```

### 4.2 CLI 执行与实时监控流程

```mermaid
sequenceDiagram
    autonumber
    participant SA as System Agent
    participant Sel as CLI Selector
    participant Adapt as CLI Adapter
    participant Mon as Execution Monitor
    participant Proc as subprocess
    participant Git as Git
    participant EL as Event Log

    SA->>Sel: select(spec, config.preferred_cli)
    Sel->>Sel: check_available(all_clis)
    Sel-->>SA: selected="claude"

    SA->>Adapt: execute(spec, on_status=monitor_callback)
    activate Adapt

    Adapt->>Proc: Popen(["claude", "-p",<br/> "--dangerously-skip-permissions"],<br/> stdout=PIPE, stderr=PIPE,<br/> cwd=spec.working_dir)
    activate Proc

    Adapt->>Mon: start_monitoring(proc, interval=10s)
    activate Mon

    loop 每 10 秒采样
        Mon->>Proc: readline(stdout) 非阻塞读取
        Mon->>Git: git status --short
        Git-->>Mon: files_touched[]
        Mon->>Mon: detect_stall(last_output_time)
        Mon->>Mon: estimate_progress(output_pattern)

        Mon->>SA: on_status(CliExecutionStatus{<br/>  elapsed, last_line,<br/>  is_stalled, files_touched,<br/>  estimated_progress})
        SA->>EL: emit(CliProgress, {task_id, progress})

        alt CLI 正常工作中
            Note right of SA: 继续等待
        else 停滞超过 stall_threshold
            SA->>SA: evaluate_stall_action()<br/>检查已产出文件<br/>判断是否值得继续
            alt 有产出, 值得继续
                SA->>Mon: extend_patience(+5min)
            else 无产出, 判定卡死
                SA->>Proc: terminate()
                SA->>EL: emit(CliStallKilled, {elapsed})
            end
        else CLI 自行完成
            Proc-->>Adapt: exit_code, stdout, stderr
        end
    end
    deactivate Mon
    deactivate Proc

    Adapt->>Adapt: parse_result(stdout, exit_code)
    Adapt-->>SA: CliTaskResult{success, snapshots[]}
    deactivate Adapt
```

### 4.3 安全自修改与灰度验证

```mermaid
sequenceDiagram
    autonumber
    participant SA as System Agent
    participant Policy as Policy Engine
    participant CLI as Agent CLI
    participant Git as Git
    participant Test as Tests
    participant EL as Event Log

    Note over SA,EL: === 自修改安全检查 ===

    SA->>SA: identify_self_improvement(target=autonomous/)
    SA->>Policy: check_self_modify_allowed(target_paths)

    Policy->>Policy: validate_whitelist(paths)
    Policy->>Policy: check_daily_budget(tokens, soft_limit)
    Policy->>Policy: verify_no_core_module_touch()

    alt 策略拒绝
        Policy-->>SA: DENIED(reason)
        SA->>EL: emit(SelfModifyDenied, {reason})
    else 策略允许
        Policy-->>SA: ALLOWED(constraints)

        Note over SA,EL: === 隔离执行 ===

        SA->>Git: create_branch("auto/self-opt/{task_id}")
        SA->>Git: snapshot(commit_sha_before)

        SA->>CLI: execute(self_optimization_task)
        Note right of CLI: 实时监控流同 4.2
        CLI-->>SA: result

        Note over SA,EL: === 自适应变更评估 ===

        SA->>Git: diff_stats()
        Git-->>SA: {lines_added, lines_removed, files_count}

        SA->>SA: assess_diff_risk(stats, task_spec)<br/>· 变更规模与任务复杂度匹配?<br/>· 涉及哪些模块?<br/>· 是否超出预期文件范围?

        alt 判定变更范围异常
            SA->>EL: emit(SelfModifyWarning, "unexpected scope")
            SA->>SA: 二次确认: 是否仍可接受?
        end

        SA->>Test: run_full_suite()
        Test-->>SA: all_passed

        SA->>SA: evaluator.deep_review()<br/>· 语义不变量检查<br/>· 接口契约验证<br/>· 回归检测

        alt 全部通过
            SA->>Git: merge("auto/self-opt/{task_id}", "main")
            SA->>EL: emit(SelfUpgradePromoted)
        else 验证失败
            SA->>Git: revert_branch()
            SA->>EL: emit(SelfUpgradeRolledBack, {reason})
        end
    end
```

### 4.4 System Agent 完整生命周期

```mermaid
sequenceDiagram
    autonumber
    participant Main as main.py<br/>ServiceManager
    participant SA as System Agent
    participant Config as Config
    participant EL as Event Log

    Main->>Config: load("autonomous")
    Config-->>Main: {enabled: true, cycle_interval: 3600}

    Main->>SA: create(config)
    activate SA
    SA->>SA: self_check()<br/>· 检查 CLI 可用性<br/>· 检查 Git 状态<br/>· 检查磁盘空间

    alt 自检失败
        SA-->>Main: InitFailed(reason)
        SA->>EL: emit(AgentInitFailed)
    else 自检通过
        SA->>EL: emit(AgentStarted)

        loop 永驻运行
            SA->>SA: await sleep(cycle_interval)
            SA->>SA: run_optimization_cycle()
            SA->>EL: emit(CycleCompleted, {task_count, success_count})

            alt KillSwitch triggered
                SA->>SA: graceful_shutdown()
                SA->>EL: emit(AgentKilled)
            end
        end
    end
    deactivate SA
```

### 4.5 验证阶段降级时序（Codex MCP）

```mermaid
sequenceDiagram
    autonumber
    participant SA as System Agent
    participant MCP as codex-mcp-server
    participant Test as Test Runner
    participant EL as Event Log

    SA->>SA: detect_verification_degrade()<br/>CLI不可用 or 重试耗尽
    SA->>EL: emit(VerificationDegradedToCodexMCP)

    SA->>MCP: ask-codex(@diff, @test_log, @target_files)<br/>sandboxMode=read-only
    MCP-->>SA: structured_suggestions{issue,evidence,suggested_fix,risk}

    SA->>Test: run_tests()
    Test-->>SA: result
    SA->>Test: run_lint()
    Test-->>SA: result

    alt 验证通过
        SA->>EL: emit(VerificationRecovered)
    else 验证失败
        SA->>EL: emit(VerificationFallbackFailed)
    end
```

---

## 5. System Agent 状态机

```mermaid
stateDiagram-v2
    [*] --> Initializing: ServiceManager 启动
    Initializing --> Ready: 自检通过 and CLI可用
    Initializing --> Failed: 自检失败

    Ready --> Sensing: 周期触发
    Sensing --> Planning: 发现优化点
    Sensing --> Ready: 无需优化

    Planning --> Dispatching: 生成任务
    Dispatching --> Monitoring: CLI 启动, 开始监控
    Monitoring --> Monitoring: 采样状态(每10s)
    Monitoring --> Evaluating: CLI 正常完成
    Monitoring --> Dispatching: CLI 停滞被终止, 重试
    Monitoring --> Ready: 重试耗尽

    Evaluating --> Merging: 评审通过
    Evaluating --> Dispatching: 需要返工(带反馈)
    Evaluating --> Ready: 评审拒绝

    Merging --> Ready: 合并成功
    Merging --> Ready: 合并失败(回滚)

    Ready --> ShuttingDown: KillSwitch / 手动停止
    ShuttingDown --> [*]
    Failed --> [*]
```

---

## 6. 目录结构

```text
NagaAgent/
├── autonomous/                       # [NEW] 自治Agent框架
│   ├── __init__.py
│   ├── system_agent.py               # System Agent 主类
│   ├── sensor.py                     # 感知器
│   ├── planner.py                    # 规划器 (LLM辅助任务生成)
│   ├── evaluator.py                  # 评估器 (diff审查 + 测试验证)
│   ├── dispatcher.py                 # 任务派发器
│   ├── monitor.py                    # [NEW] CLI执行监控器
│   ├── tools/                        # CLI 工具层
│   │   ├── __init__.py
│   │   ├── cli_adapter.py            # 适配器基类 + 数据类
│   │   ├── codex_adapter.py          # Codex CLI 适配
│   │   ├── claude_adapter.py         # Claude Code 适配
│   │   ├── gemini_adapter.py         # Gemini CLI 适配
│   │   ├── cli_selector.py           # CLI 选择策略
│   │   ├── git_operator.py           # Git操作封装
│   │   └── test_runner.py            # 测试执行封装
│   ├── policy/                       # 策略
│   │   ├── gate_policy.yaml
│   │   └── self_modify_whitelist.yaml
│   ├── config/
│   │   └── autonomous_config.yaml    # 自治框架配置
│   └── event_log/                    # 轻量事件存储
│       └── event_store.py            # SQLite/JSON事件存储
├── doc/
│   ├── 07-autonomous-agent-sdlc-architecture.md
│   └── 00-mvp-architecture-design.md  # [NEW] 本文档
└── ...
```

---

## 7. 配置模板

```yaml
# autonomous/config/autonomous_config.yaml
autonomous:
  enabled: false                      # 默认关闭
  cycle_interval_seconds: 3600        # 优化周期(秒)

  cli_tools:
    preferred: "claude"               # 首选CLI
    fallback_order: ["codex", "gemini"]
    max_retries: 3

  cli_execution:
    # 超时策略: 自适应 + 可配硬上限
    timeout_mode: "adaptive"          # adaptive | fixed
    fixed_timeout_seconds: 7200       # fixed模式下的硬上限(2小时)
    adaptive:
      base_timeout_seconds: 1800     # 基础超时(30分钟)
      per_complexity:                 # 按任务复杂度乘数
        low: 1.0                      # 30分钟
        medium: 2.0                   # 1小时
        high: 4.0                     # 2小时
        epic: 8.0                     # 4小时
      max_timeout_seconds: 14400     # 绝对上限(4小时)
    monitoring:
      poll_interval_seconds: 10      # 状态采样间隔
      stall_threshold_seconds: 300   # 无输出超过此值判定停滞(5分钟)
      stall_max_extensions: 3        # 停滞后最多延长次数
      stall_extension_seconds: 300   # 每次延长时长(5分钟)

  budget:
    # 令牌预算: 软限制告警 + 硬限制熔断（与07文档一致）
    daily_token_soft_limit: 100000000   # 软限制(10M), 超出触发告警
    daily_token_hard_limit: 500000000   # 硬限制(50M), 超出停止本周期
    warn_on_exceed: true

  verification_fallback:
    enable_codex_mcp: true
    mcp_server_name: "codex-cli"
    tool_name: "ask-codex"
    trigger_on:
      cli_unavailable: true
      retry_exhausted: true
    sandbox_mode: "read-only"
    approval_policy: "on-failure"

  security:
    self_modify_whitelist:
      - "autonomous/"
      - "doc/"
      - "tests/"
    core_readonly:                     # 默认只读，特殊改动需走Gate审批
      - "main.py"
      - "apiserver/"
      - "system/config.py"
    diff_review_mode: "adaptive"      # adaptive | fixed
    fixed_max_diff_lines: 5000        # fixed模式下硬上限
    require_human_approval: false     # 是否需要人工确认合并

  git:
    branch_prefix: "auto/"
    auto_cleanup_branches: true

  event_log:
    backend: "sqlite"                 # sqlite | json_file
    retention_days: 90
```

---

## 8. 与现有代码集成

### 8.1 ServiceManager 扩展点

```diff
 # main.py - ServiceManager.start_all_servers()
+    # 启动自治Agent (如果配置启用)
+    if config.get("autonomous", {}).get("enabled", False):
+        from autonomous.system_agent import SystemAgent
+        self.system_agent = SystemAgent(config["autonomous"])
+        asyncio.create_task(self.system_agent.start())
```

### 8.2 与 TaskScheduler 集成

现有 [task_scheduler.py](file:///E:/Programs/NagaAgent/agentserver/task_scheduler.py) 提供任务管理和 LLM 压缩能力。System Agent 的规划器可复用其 LLM 调用基础设施。

---

## 9. 安全约束

### 9.1 不可协商的硬规则

| 规则 | 约束 |
|------|------|
| **白名单目录** | CLI 仅能修改 `self_modify_whitelist` 中的目录 |
| **核心模块受控改动** | [main.py](file:///E:/Programs/NagaAgent/main.py)、`apiserver/`、[system/config.py](file:///E:/Programs/NagaAgent/system/config.py) 默认不改；若确需改动，必须通过 Gate + 审计事件 + 回滚预案 |
| **Git 分支隔离** | 所有变更在 `auto/*` 分支，不直接写 `main` |
| **回滚保障** | 合并前 Git snapshot，失败时 `git revert` |
| **KillSwitch** | 配置项随时可关闭自治循环 |

### 9.2 自适应弹性约束

| 维度 | 策略 | 说明 |
|------|------|------|
| **变更规模** | System Agent **自主评估**，不设固定行数上限 | 根据任务复杂度和目标范围判断 diff 是否合理，异常放大时告警而非硬截断 |
| **Token 预算** | 每日 **100 万软限制 + 500 万硬限制** | 软限制告警，硬限制熔断，避免无限消耗 |
| **CLI 执行时间** | **自适应超时**：按任务复杂度 30min ~ 4h，System Agent 实时监控 | 停滞检测 + 智能续期，而非盲目截断 |
| **验证降级** | 主 CLI 不可用时切换到 Codex MCP `ask-codex` | 仅用于 Verifying 阶段，且默认 read-only |

### 9.3 CLI 执行监控机制

System Agent 在 CLI 执行期间**不是盲等**，而是主动监控：

| 监控维度 | 采集方式 | 决策依据 |
|----------|----------|----------|
| **stdout 输出流** | 非阻塞 readline，10s 采样 | 有新输出 = 正常工作 |
| **文件变更** | `git status --short` 定期检查 | 有新文件变更 = 正在产出 |
| **停滞检测** | 超过 5 分钟无任何新输出 | 触发停滞评估流程 |
| **进度估算** | 基于输出模式（日志关键词）推断 | 辅助超时决策 |

**停滞处理流程：**
1. 检测到停滞 → 检查 `git status`，若有新文件变更则视为"慢但在工作"，延长等待
2. 延长最多 3 次（每次 +5 分钟）
3. 若延长后仍无产出 → `terminate()` 并记录事件
4. 所有决策写入 Event Log，支持事后审阅

---

## 10. MVP 阶段里程碑（2 周，映射 07 文档的 Phase 0）

| 天 | 任务 | 产物 |
|----|------|------|
| D1-D2 | 实现 CLI Adapter 基类 + Claude 适配器 + Monitor | `autonomous/tools/` + `autonomous/monitor.py` |
| D3-D4 | 实现 Sensor (ruff + pytest 扫描) | `autonomous/sensor.py` |
| D5-D6 | 实现 Planner (LLM 辅助任务生成) | `autonomous/planner.py` |
| D7-D8 | 实现 Evaluator + Git Operator | `autonomous/evaluator.py` |
| D9-D10 | 实现 System Agent 主循环 + ServiceManager 集成 | `autonomous/system_agent.py` |
| D11-D12 | Codex + Gemini 适配器 | 完整 CLI 支持 |
| D13-D14 | 端到端测试 + 安全验证 | 可交付 MVP |

---

## Verification Plan

### Automated Tests
- `python -m pytest autonomous/tests/ -v`（新建单元测试）
- `ruff check autonomous/`（代码质量）
- 端到端：System Agent 启动→感知→生成任务→CLI 执行(含监控)→评审→合并
- 降级链路：模拟主 CLI 不可用，验证触发 `ask-codex` 并写入 `VerificationDegradedToCodexMCP`

### Manual Verification
- `autonomous.enabled=false` 时确认无额外进程
- `autonomous.enabled=true` 时确认 System Agent 启动并完成至少一次循环
- 验证 CLI 停滞检测：模拟长时间无输出，确认自动终止
- CLI 不可用时确认降级到 Codex MCP（`codex-cli` 服务 + `ask-codex`）
- 触发 KillSwitch 确认立即停止
