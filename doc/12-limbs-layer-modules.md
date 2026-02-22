# 12 - 手脚层模块详细架构 (Limbs Layer Modules)

> **定位**：手脚层是 Omni-Operator 的执行末端，所有能力以 MCP (Model Context Protocol) 形式挂载，支持热插拔和动态注册。

---

## 1. MCP Host 与 Tool Registry

### 1.1 模块职责

MCP 协议宿主服务端，负责工具的注册/发现/调度/生命周期管理。所有工具统一通过 MCP 协议暴露给 LLM。

### 1.2 内部架构

```mermaid
flowchart TB
    subgraph MCPHost["📡 MCP Host & Tool Registry"]
        direction TB
        REGISTRY["🗂️ Tool Registry<br/>工具注册表<br/>Schema · 状态 · 版本"]
        SCANNER["📂 Directory Scanner<br/>扫描 workspace/tools/<br/>自动发现新工具"]
        LOADER["📦 Dynamic Loader<br/>dynamic import()<br/>TypeScript 模块加载"]
        HEALTH["❤️ Health Monitor<br/>工具健康检查<br/>降级标记"]
        DISPATCHER["🔀 Call Dispatcher<br/>调用分发 · 超时控制<br/>结果封装"]
        SCHEMA_GEN["📋 Schema Generator<br/>从工具代码提取 JSON Schema<br/>供 LLM tools 参数"]
    end

    subgraph BuiltIn["内置工具 (built_in/)"]
        T_BASH["os_bash"]
        T_AST["file_ast"]
        T_WEB["web_scraper"]
        T_SEARCH["search_engine"]
        T_SLEEP["sleep_until"]
        T_CRON["schedule_cron"]
        T_SNAP["snapshot_mgr"]
        T_SYS["systemd_mgr"]
        T_GIT["git_operator"]
    end

    subgraph Plugins["动态插件 (plugins/)"]
        P1["Agent 自生成工具 A"]
        P2["Agent 自生成工具 B"]
        P_NEW["... (动态增长)"]
    end

    SCANNER -->|"发现 .ts 文件"| LOADER
    LOADER -->|"加载模块"| SCHEMA_GEN
    SCHEMA_GEN -->|"注册"| REGISTRY
    LLM["LLM Client"] -->|"tool_use"| DISPATCHER
    DISPATCHER -->|"查询"| REGISTRY
    DISPATCHER -->|"路由执行"| T_BASH & T_AST & T_WEB & P1

    HEALTH -->|"定期检查"| REGISTRY
    HEALTH -->|"标记降级"| REGISTRY

    T_BASH & T_AST & T_WEB & T_SEARCH & T_SLEEP & T_CRON & T_SNAP & T_SYS & T_GIT --- BuiltIn
    P1 & P2 & P_NEW --- Plugins

    style MCPHost fill:#0a2e1a,stroke:#44ff88,color:#ccffee
```

### 1.3 工具注册与热加载时序

```mermaid
sequenceDiagram
    participant FS as File System
    participant WATCH as Chokidar Watcher
    participant SCAN as Directory Scanner
    participant LOAD as Dynamic Loader
    participant SCHEMA as Schema Generator
    participant REG as Tool Registry
    participant HEALTH as Health Monitor

    Note over FS,HEALTH: === 启动时批量注册 ===

    SCAN->>FS: readdir("workspace/tools/built_in/")
    FS-->>SCAN: [os_bash.ts, file_ast.ts, web_scraper.ts, ...]

    loop 每个工具文件
        SCAN->>LOAD: import("./os_bash.ts")
        LOAD-->>SCAN: module {name, schema, execute, healthCheck}
        SCAN->>SCHEMA: extractSchema(module)
        SCHEMA-->>SCAN: JSONSchema {name, params, returns}
        SCAN->>REG: register({<br/>  name: "os_bash",<br/>  schema: jsonSchema,<br/>  handler: module.execute,<br/>  health: module.healthCheck,<br/>  version: "1.0.0",<br/>  risk_level: "write_repo"<br/>})
    end

    Note over FS,HEALTH: === 运行时热加载 ===

    FS->>WATCH: Agent 写入新文件 plugins/log_parser.ts
    WATCH->>WATCH: debounce(1000ms)
    WATCH->>LOAD: import("plugins/log_parser.ts")
    LOAD-->>SCHEMA: module
    SCHEMA->>REG: register(new_tool)
    REG->>REG: 通知 LLM Client: tools 列表已更新
    Note right of REG: 下次 API 请求将包含新工具

    Note over FS,HEALTH: === 健康检查 ===
    loop 每 60 秒
        HEALTH->>REG: listAllTools()
        loop 每个已注册工具
            HEALTH->>HEALTH: tool.healthCheck()
            alt 检查失败
                HEALTH->>REG: markDegraded("web_scraper", reason)
                Note right of REG: 降级工具不会出现在 LLM tools 列表中
            end
        end
    end
```

### 1.4 工具标准接口

```typescript
// workspace/tools/tool_interface.ts
interface MCPTool {
  // 元数据
  name: string;
  description: string;
  version: string;
  risk_level: "read_only" | "write_repo" | "deploy" | "secrets" | "self_modify";

  // Schema (自动转为 LLM tools 参数)
  inputSchema: JSONSchema;
  outputSchema: JSONSchema;

  // 执行
  execute(args: Record<string, unknown>, ctx: ToolContext): Promise<ToolResult>;

  // 生命周期
  healthCheck(): Promise<HealthStatus>;
  initialize?(): Promise<void>;
  cleanup?(): Promise<void>;
}

interface ToolContext {
  call_id: string;
  trace_id: string;
  session_id: string;
  fencing_epoch: number;
  timeout_ms: number;
  budget_remaining: number;
  caller_role: string;
}

interface ToolResult {
  success: boolean;
  output: string;             // 可能被截断
  exit_code?: number;
  files_changed?: string[];
  duration_ms: number;
  truncated: boolean;
  raw_length?: number;
}
```

---

## 2. os_bash 系统命令执行器

### 2.1 模块职责

带超时、输出截断、安全校验的 Bash/Shell 命令执行器。Agent 所有系统操作的基础能力。

### 2.2 执行流程架构

```mermaid
flowchart TB
    subgraph OsBash["⌨️ os_bash 工具"]
        direction TB
        VALIDATE["参数校验<br/>命令非空 · 合法字符"]
        SECURITY["安全预检<br/>调用 Regex Firewall"]
        SPAWN["进程管理<br/>child_process.spawn<br/>设定 timeout / cwd / env"]
        STREAM["输出采集<br/>stdout + stderr 实时读取<br/>内存上限 10MB"]
        TRUNCATE["智能截断<br/>Head 200行 + Tail 200行<br/>中间标注 [TRUNCATED N lines]"]
        FORMAT["结果封装<br/>exit_code + truncated_output"]
    end

    LLM["LLM tool_use"] -->|"cmd, timeout, cwd"| VALIDATE
    VALIDATE --> SECURITY
    SECURITY -->|"放行"| SPAWN
    SECURITY -->|"拦截"| ERROR["❌ Security Denied"]
    SPAWN --> STREAM
    STREAM --> TRUNCATE
    TRUNCATE --> FORMAT
    FORMAT -->|"tool_result"| LLM

    style OsBash fill:#1a2a1a,stroke:#44aa44
```

### 2.3 执行与截断时序

```mermaid
sequenceDiagram
    participant LLM as LLM Client
    participant BASH as os_bash
    participant SEC as Security Kernel
    participant PROC as child_process
    participant TRUNC as Truncator

    LLM->>BASH: tool_use("os_bash", {<br/>  cmd: "find / -name '*.log' -exec cat {} +",<br/>  timeout: 30000,<br/>  cwd: "/var/log"<br/>})

    BASH->>SEC: validate(cmd)
    SEC-->>BASH: ✅ PASS

    BASH->>PROC: spawn("bash", ["-c", cmd], {<br/>  timeout: 30000,<br/>  maxBuffer: 10MB,<br/>  cwd: "/var/log"<br/>})

    activate PROC
    PROC-->>BASH: stdout 流 (持续输出)

    BASH->>BASH: 实时计行: line_count++

    alt 输出 > 10MB
        BASH->>PROC: kill(SIGTERM)
        Note right of BASH: 内存保护截断
    else 超时 > 30s
        BASH->>PROC: kill(SIGTERM)
        Note right of BASH: 超时截断
    else 正常结束
        PROC-->>BASH: exit_code=0
    end
    deactivate PROC

    BASH->>TRUNC: truncate(stdout, {head: 200, tail: 200})
    Note right of TRUNC: 原始: 50,000 行<br/>截断后: 400 行 +<br/>[... TRUNCATED 49,600 lines ...]

    TRUNC-->>BASH: truncated_output

    BASH-->>LLM: tool_result({<br/>  success: true,<br/>  output: truncated_output,<br/>  exit_code: 0,<br/>  truncated: true,<br/>  raw_length: 50000,<br/>  duration_ms: 8500<br/>})
```

---

## 3. file_ast AST 精确代码编辑器

### 3.1 模块职责

基于 AST（抽象语法树）精准修改代码，而非危险的全量覆盖。支持按函数/类/行范围的精确替换。

### 3.2 编辑流程架构

```mermaid
flowchart TB
    subgraph FileAST["🔧 file_ast 工具"]
        direction TB
        PARSE["AST 解析器<br/>TypeScript: ts-morph<br/>Python: ast / LibCST<br/>Markdown: mdast"]
        LOCATE["定位器<br/>按函数名 · 类名 · 行号<br/>精确定位修改目标"]
        PATCH["补丁引擎<br/>AST 级别精确替换<br/>保持格式化"]
        VALIDATE["变更校验<br/>语法检查 · 类型检查<br/>diff 生成"]
        WRITE["原子写入<br/>tmp写入 → rename<br/>防止部分写入"]
    end

    LLM["LLM tool_use"] -->|"file, target, patch"| PARSE
    PARSE --> LOCATE
    LOCATE --> PATCH
    PATCH --> VALIDATE
    VALIDATE -->|"✅ 语法正确"| WRITE
    VALIDATE -->|"❌ 语法错误"| ERROR["返回错误详情"]
    WRITE --> DIFF["返回 diff 结果"]

    style FileAST fill:#2a2a1a,stroke:#aaaa44
```

### 3.3 精确编辑时序

```mermaid
sequenceDiagram
    participant LLM as LLM Client
    participant AST as file_ast
    participant PARSER as AST Parser
    participant FS as File System

    LLM->>AST: tool_use("file_ast", {<br/>  path: "src/server.ts",<br/>  target: {type: "function", name: "handleRequest"},<br/>  patch: "function handleRequest(req) {\n  // 新实现\n}"<br/>})

    AST->>FS: readFile("src/server.ts")
    FS-->>AST: source_code

    AST->>PARSER: parse(source_code, "typescript")
    PARSER-->>AST: AST tree

    AST->>AST: locate: 查找 function handleRequest<br/>找到: 行 45-72

    AST->>AST: apply_patch:<br/>替换行 45-72 为 patch 内容
    AST->>PARSER: re_parse(patched_code)

    alt 语法错误
        PARSER-->>AST: SyntaxError at line 48
        AST-->>LLM: tool_result({<br/>  success: false,<br/>  error: "Syntax error at line 48"<br/>})
    else 语法正确
        AST->>FS: writeFileAtomic("src/server.ts", patched_code)
        AST->>AST: generate_diff(original, patched)
        AST-->>LLM: tool_result({<br/>  success: true,<br/>  diff: "- old line\n+ new line",<br/>  lines_changed: 28<br/>})
    end
```

---

## 4. search_engine 搜索引擎

### 4.1 模块职责

接入 Google / Tavily API 搜索最新资讯，帮助 Agent 获取错误解决方案和最新文档。

### 4.2 搜索与结果处理时序

```mermaid
sequenceDiagram
    participant LLM as LLM Client
    participant SE as search_engine
    participant API as Tavily/Google API
    participant FILTER as Result Filter

    LLM->>SE: tool_use("search_engine", {<br/>  query: "nginx 502 bad gateway upstream timeout fix",<br/>  max_results: 10,<br/>  search_depth: "advanced"<br/>})

    SE->>API: POST /search {query, max_results}
    API-->>SE: raw_results[10]

    SE->>FILTER: filterAndRank(raw_results)
    FILTER->>FILTER: 过滤:<br/>· 移除广告/SEO垃圾<br/>· 优先 Stack Overflow / GitHub / 官方文档
    FILTER->>FILTER: 摘要截断: 每条 ≤ 500 字
    FILTER-->>SE: filtered_results[8]

    SE-->>LLM: tool_result({<br/>  results: [<br/>    {title, url, snippet, relevance_score},<br/>    ...<br/>  ],<br/>  total_results: 8<br/>})
```

---

## 5. headless_browser 无头浏览器

### 5.1 模块职责

内置 Playwright 驱动的无头浏览器，Agent 可直接浏览官方文档、点击网页按钮、截图取证。

### 5.2 浏览器操作时序

```mermaid
sequenceDiagram
    participant LLM as LLM Client
    participant HB as headless_browser
    participant PW as Playwright Engine
    participant WEB as Target Website

    LLM->>HB: tool_use("headless_browser", {<br/>  url: "https://nginx.org/en/docs/http/ngx_http_proxy_module.html",<br/>  actions: ["scroll_to_bottom", "extract_text"],<br/>  screenshot: true<br/>})

    HB->>PW: newContext({viewport: 1280x720})
    PW->>WEB: navigate(url)
    WEB-->>PW: page loaded

    loop 执行 actions
        HB->>PW: scrollToBottom()
        PW-->>HB: done
        HB->>PW: extractText("main")
        PW-->>HB: page_text (可能很长)
    end

    HB->>PW: screenshot({fullPage: false})
    PW-->>HB: screenshot_bytes

    HB->>HB: 截断 page_text (max 5000 chars)
    HB->>PW: closeContext()

    HB-->>LLM: tool_result({<br/>  text: truncated_page_text,<br/>  screenshot_path: "/tmp/screenshot_001.png",<br/>  url: "...",<br/>  title: "..."<br/>})
```

---

## 6. sleep_until / schedule_cron 时空控制工具

### 6.1 模块职责

让 Agent 能够挂起自身等待特定条件或时间，以及设定定期巡检任务。这是长程自主运行的关键能力。

### 6.2 条件休眠架构

```mermaid
flowchart TB
    subgraph Chronos["⏰ 时空控制工具"]
        direction TB
        subgraph SleepUntil["sleep_until"]
            S_TIME["时间条件<br/>sleep_until('2026-03-01 08:00')"]
            S_EVENT["事件条件<br/>sleep_until('log.error出现')"]
            S_METRIC["指标条件<br/>sleep_until('CPU > 90%')"]
            S_COMBO["组合条件<br/>sleep_until('Error OR 30min')"]
        end

        subgraph Cron["schedule_cron"]
            C_PATROL["巡检任务<br/>'0 */6 * * *' 每6h"]
            C_BACKUP["备份任务<br/>'0 3 * * *' 每天3点"]
            C_HEALTH["健康检查<br/>'*/5 * * * *' 每5min"]
        end

        WATCHER["条件监控器<br/>EventBus 订阅 + 轮询"]
    end

    S_EVENT -->|"订阅"| EB["Event Bus"]
    S_METRIC -->|"轮询"| WD["Watchdog Metrics"]
    WATCHER -->|"条件满足"| WAKE["唤醒 Agent"]
    C_PATROL & C_BACKUP & C_HEALTH -->|"定时触发"| EB

    style Chronos fill:#1a1a2e,stroke:#6666ff
```

### 6.3 条件休眠时序

```mermaid
sequenceDiagram
    participant LLM as LLM Client
    participant SLEEP as sleep_until
    participant EB as Event Bus
    participant LOG_MON as 日志监控器
    participant META as Meta-Agent

    LLM->>SLEEP: tool_use("sleep_until", {<br/>  condition: {type: "event", pattern: "log.error.*nginx"},<br/>  timeout: "24h",<br/>  on_wake: "诊断 nginx 错误"<br/>})

    SLEEP->>EB: subscribe("log.error.*nginx")
    SLEEP->>SLEEP: 挂起 Agent 会话<br/>🔇 零 Token 消耗

    Note over SLEEP,META: Agent 完全休眠中...<br/>可能持续数小时<br/>Event Bus 持续监控

    LOG_MON->>EB: publish("log.error.nginx", {<br/>  message: "upstream timed out"<br/>})

    EB->>SLEEP: 条件匹配! 触发唤醒

    SLEEP->>META: wake_up({<br/>  trigger: "nginx upstream timed out",<br/>  slept_duration: "4h 23min",<br/>  original_instruction: "诊断 nginx 错误"<br/>})

    META->>META: 恢复认知上下文<br/>执行指定任务
```

---

## 7. Self-Evolution 自我进化工具集

### 7.1 模块职责

允许 Agent 读取/修改子 Agent 的提示词，以及自己编写新工具并注册。

### 7.2 自我进化工具架构

```mermaid
flowchart TB
    subgraph SelfEvo["🧬 自我进化工具集"]
        direction TB
        READ_P["📖 read_my_prompt<br/>读取指定角色的 Prompt"]
        UPDATE_P["✏️ update_my_prompt<br/>修改 Prompt 内容"]
        REG_TOOL["🔌 register_new_tool<br/>Agent 编写并注册新工具"]

        subgraph SafeGuards["安全护栏"]
            DNA_CHECK["DNA 保护<br/>禁止修改 immutable_dna.md"]
            DIFF_REVIEW["变更审查<br/>修改前后 diff 记录"]
            VERSION["版本管理<br/>Git 提交每次变更"]
            ROLLBACK["回滚能力<br/>任何时候可 revert"]
        end
    end

    READ_P -->|"读取"| PROMPTS["workspace/prompts/*.md"]
    UPDATE_P -->|"写入"| PROMPTS
    UPDATE_P -->|"校验"| DNA_CHECK
    UPDATE_P -->|"记录"| DIFF_REVIEW
    UPDATE_P -->|"提交"| VERSION
    REG_TOOL -->|"写入"| PLUGINS["workspace/tools/plugins/"]
    REG_TOOL -->|"触发"| LOADER["MCP Dynamic Loader"]

    style SelfEvo fill:#2e1a2e,stroke:#aa44aa
```

### 7.3 Prompt 修改时序

```mermaid
sequenceDiagram
    participant AGENT as Agent
    participant EVO as update_my_prompt
    participant DNA as DNA Check
    participant FS as File System
    participant GIT as Git
    participant WATCH as File Watcher
    participant LLM as LLM Client

    AGENT->>EVO: tool_use("update_my_prompt", {<br/>  role: "sys_admin",<br/>  changes: "添加: 遇到 OOM 优先检查 swap"<br/>})

    EVO->>DNA: 目标是 immutable_dna.md?
    DNA-->>EVO: No → 允许

    EVO->>FS: read("workspace/prompts/sys_admin.md")
    FS-->>EVO: current_content

    EVO->>EVO: 应用修改 (追加新规则)
    EVO->>FS: write("workspace/prompts/sys_admin.md", new_content)

    EVO->>GIT: git add + commit<br/>"self-evo: sys_admin 添加 OOM 规则"

    FS-->>WATCH: 文件变更事件
    WATCH->>LLM: reloadPrompt("sys_admin")
    LLM->>LLM: 清理旧 Cache → 下次请求使用新 Prompt

    EVO-->>AGENT: tool_result({<br/>  success: true,<br/>  diff: "+遇到 OOM 优先检查 swap",<br/>  commit: "abc1234"<br/>})

    Note over AGENT: 下次推理时，Agent 已具备新认知
```

### 7.4 动态工具注册时序

```mermaid
sequenceDiagram
    participant AGENT as Agent
    participant REG as register_new_tool
    participant FS as File System
    participant SANDBOX as Sandbox
    participant LOADER as MCP Loader
    participant REGISTRY as Tool Registry

    AGENT->>REG: tool_use("register_new_tool", {<br/>  name: "log_pattern_analyzer",<br/>  code: "export default { name: 'log_pattern_analyzer', ... }",<br/>  description: "分析日志中的重复错误模式"<br/>})

    REG->>FS: write("workspace/tools/plugins/log_pattern_analyzer.ts", code)

    Note over REG,SANDBOX: === 沙盒安全验证 ===
    REG->>SANDBOX: 在隔离环境中加载并测试
    SANDBOX->>SANDBOX: 语法检查 ✅
    SANDBOX->>SANDBOX: 安全扫描 (无危险导入) ✅
    SANDBOX->>SANDBOX: 基础执行测试 ✅
    SANDBOX-->>REG: 验证通过

    REG->>LOADER: dynamicImport("plugins/log_pattern_analyzer.ts")
    LOADER->>REGISTRY: register(new_tool_module)
    REGISTRY->>REGISTRY: 更新 LLM tools 列表

    REG-->>AGENT: tool_result({<br/>  success: true,<br/>  tool_name: "log_pattern_analyzer",<br/>  message: "工具已注册，可在后续对话中使用"<br/>})

    Note over AGENT: Agent 现在多了一个新能力!
```

---

## 8. CLI Adapter 外部 Agent CLI 适配层

### 8.1 模块职责

统一封装 Codex CLI / Claude Code / Gemini CLI 的调用接口，包含选择策略、实时监控、停滞检测。承接现有 `autonomous/tools/cli_adapter.py` 架构。

### 8.2 CLI 适配层架构

```mermaid
flowchart TB
    subgraph CLILayer["🔗 CLI Adapter Layer"]
        direction TB
        SELECTOR["CLI Selector<br/>选择最优 CLI<br/>可用性·任务匹配·负载"]
        ADAPTER["Unified Adapter<br/>统一接口封装<br/>subprocess 管理"]
        MONITOR["Execution Monitor<br/>实时监控 stdout<br/>停滞检测 · 进度估算"]

        subgraph CLIs["支持的 CLI"]
            CODEX["Codex CLI<br/>codex --full-auto"]
            CLAUDE["Claude Code<br/>claude -p --dangerously-skip-permissions"]
            GEMINI["Gemini CLI<br/>gemini -p"]
        end

        subgraph Monitoring["监控维度"]
            M_STDOUT["stdout 输出流<br/>10s 采样"]
            M_GIT["git status<br/>文件变更检测"]
            M_STALL["停滞检测<br/>5min 无输出告警"]
            M_PROGRESS["进度估算<br/>基于输出模式"]
        end
    end

    DISPATCHER["Dispatcher"] -->|"任务规格"| SELECTOR
    SELECTOR -->|"选择 CLI"| ADAPTER
    ADAPTER -->|"启动进程"| CODEX & CLAUDE & GEMINI
    ADAPTER -->|"启动监控"| MONITOR
    MONITOR --> M_STDOUT & M_GIT & M_STALL & M_PROGRESS

    style CLILayer fill:#2e1a3e,stroke:#8855cc
```

### 8.3 CLI 选择与执行时序

```mermaid
sequenceDiagram
    participant DISP as Dispatcher
    participant SEL as CLI Selector
    participant ADAPT as CLI Adapter
    participant MON as Monitor
    participant PROC as subprocess
    participant GIT as Git

    DISP->>SEL: select(spec, available_clis)

    SEL->>SEL: check_available("codex")
    Note right of SEL: which codex → found ✅
    SEL->>SEL: check_available("claude")
    Note right of SEL: which claude → found ✅
    SEL->>SEL: check_available("gemini")
    Note right of SEL: which gemini → not found ❌

    SEL->>SEL: 选择策略:<br/>1. 用户首选: codex<br/>2. 任务匹配: 大规模重构→codex<br/>3. 可用: [codex, claude]<br/>结果: codex
    SEL-->>DISP: selected="codex"

    DISP->>ADAPT: execute(spec, cli="codex")
    ADAPT->>PROC: Popen(["codex", "--full-auto", "-q", instruction])
    ADAPT->>MON: startMonitoring(proc, interval=10s)

    loop 每 10 秒
        MON->>PROC: readline(stdout) 非阻塞
        MON->>GIT: git status --short
        GIT-->>MON: files_touched[]

        MON->>MON: 计算:<br/>· elapsed: 45s<br/>· last_output: 3s ago<br/>· files_touched: 2<br/>· is_stalled: false<br/>· progress: 0.4

        MON->>DISP: on_status(CliExecutionStatus)
    end

    alt 检测到停滞 (5min 无输出)
        MON->>GIT: git status --short
        alt 有新文件变更
            MON->>MON: extend_patience(+5min)
            Note right of MON: "慢但在工作"
        else 无任何变更
            MON->>PROC: terminate()
            MON->>DISP: stall_killed
        end
    end

    PROC-->>ADAPT: exit_code=0, stdout
    ADAPT-->>DISP: CliTaskResult{success, snapshots[]}
```

---

## 9. snapshot_manager 快照管理器

### 9.1 模块职责

在每次重大修改前强制创建系统/文件快照，支持一键回滚。

### 9.2 快照操作时序

```mermaid
sequenceDiagram
    participant SEC as Security Kernel
    participant SNAP as Snapshot Manager
    participant FS as File System / ZFS
    participant GIT as Git

    SEC->>SNAP: createSnapshot("pre-nginx-config-change")

    par 并行快照
        SNAP->>FS: zfs snapshot pool/data@pre-nginx-config-change
        Note right of FS: ZFS 原子快照 (毫秒级)
    and
        SNAP->>GIT: git stash + git tag snapshot/pre-nginx
    end

    FS-->>SNAP: snapshot_id="pool/data@pre-nginx-config-change"
    GIT-->>SNAP: git_tag="snapshot/pre-nginx"

    SNAP-->>SEC: {snapshot_id, git_tag, timestamp}

    Note over SEC,GIT: ... Agent 执行操作 ...

    alt 需要回滚
        SEC->>SNAP: rollback(snapshot_id)
        SNAP->>FS: zfs rollback pool/data@pre-nginx-config-change
        SNAP->>GIT: git checkout snapshot/pre-nginx
        SNAP-->>SEC: ✅ 已回滚到修改前状态
    end
```

---

## 10. 手脚层模块交互全景

```mermaid
flowchart TB
    subgraph Limbs["手脚层模块协作全景"]
        subgraph MCP_Core["MCP 核心"]
            HOST["📡 MCP Host"]
            REG["🗂️ Tool Registry"]
        end

        subgraph SysMCP["系统工具"]
            BASH["⌨️ os_bash"]
            AST_["🔧 file_ast"]
            SYS["📦 systemd_mgr"]
            GIT_["🔀 git_operator"]
            SNAP_["📸 snapshot_mgr"]
        end

        subgraph WebMCP["网络工具"]
            SEARCH_["🔍 search_engine"]
            BROWSER_["🌐 headless_browser"]
        end

        subgraph TimeMCP["时空工具"]
            SLEEP_["💤 sleep_until"]
            CRON_["⏰ schedule_cron"]
        end

        subgraph EvoMCP["进化工具"]
            READ_P_["📖 read_prompt"]
            UPDATE_P_["✏️ update_prompt"]
            REG_TOOL_["🔌 register_tool"]
        end

        subgraph CLI_MCP["CLI 工具"]
            ADAPTER_["🔗 CLI Adapter"]
            CODEX_["Codex"]
            CLAUDE_["Claude"]
            GEMINI_["Gemini"]
        end
    end

    LLM["🤖 LLM Client"] -->|"tool_use"| HOST
    HOST --> REG
    REG --> BASH & AST_ & SYS & GIT_ & SNAP_
    REG --> SEARCH_ & BROWSER_
    REG --> SLEEP_ & CRON_
    REG --> READ_P_ & UPDATE_P_ & REG_TOOL_
    REG --> ADAPTER_
    ADAPTER_ --> CODEX_ & CLAUDE_ & GEMINI_

    %% 安全连线
    BASH & AST_ & SYS -->|"执行前"| SEC["🛡️ Security Kernel"]
    SNAP_ -->|"快照"| SEC

    style Limbs fill:#0a2e1a,stroke:#44ff88,color:#ccffee
```
