---
**文档类型**：🎯 目标态架构设计（Target Architecture - Phase 3）
**实施状态**：Phase 3 目标态对齐中（当前为 Phase 0 + 增量桥接混合态）
**最后更新**：2026-02-27
**当前替代方案**：MCP Manager (mcpserver/) + Native Executor (system/) + SubAgent Runtime + NativeExecutionBridge
**实施路径**：Phase 0 (基础 MCP) → Phase 1-2 (增强) → Phase 3 (本文档)
---

# 12 - 手脚层模块详细架构 (Limbs Layer Modules)


> Migration Note (archived/legacy)
> 文中 `autonomous/*` 路径属于历史实现标识；当前实现请优先使用 `agents/*`、`core/*` 与 `config/autonomous_runtime.yaml`。

> **定位**：手脚层是 Embla System 的执行末端，所有能力以 MCP (Model Context Protocol) 形式挂载，支持热插拔和动态注册。
>
> **实施状态**：
> - 🟢 **Phase 0 已实现**：MCP Manager、Native Executor、基础工具集
> - 🟡 **Phase 1-2 规划**：工具热加载、健康检查、降级标记
> - 🔴 **Phase 3 目标态**：完整 MCP Host、动态插件、Sub-Agent Runtime（本文档）
>
> **当前实现映射**：
> - MCP Host → MCP Manager (mcpserver/mcp_manager.py)
> - Tool Registry → MCP Registry (mcpserver/mcp_registry.py)
> - os_bash → Native Executor (system/native_executor.py)
> - file_ast → 无（目标态）
> - Sub-Agent Runtime → `agents/runtime/mini_loop.py`（Phase 3 增量 v1：依赖调度 + 契约协商前置 + 事件锚点）
> - Scaffold Engine → `autonomous/scaffold_engine.py`（archived/legacy）（契约门禁 + 可插拔 verify pipeline + 事务回滚）
> - Execution Bridge → `agents/tool_loop.py`（内生可审计执行桥已落地；语义级能力持续补齐）
> - CLI Adapter → 历史兼容入口（非默认主路径）
>
> **一致性口径（2026-02-27）**：
> - 阶段边界与目标态判定以 `doc/00-omni-operator-architecture.md` 为主。
> - 子代理执行面状态分层以 `doc/task/25-subagent-development-fabric-status-matrix.md` 为主。

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
        LOADER["📦 Isolated Loader<br/>签名校验 + worker import()<br/>TypeScript 模块加载"]
        HEALTH["❤️ Health Monitor<br/>工具健康检查<br/>降级标记"]
        DISPATCHER["🔀 Call Dispatcher<br/>调用分发 · 超时控制<br/>结果封装"]
        SCHEMA_GEN["📋 Schema Generator<br/>从工具代码提取 JSON Schema<br/>供 LLM tools 参数"]
    end

    subgraph BuiltIn["内置工具 (built_in/)"]
        T_BASH["os_bash"]
        T_ART["artifact_reader"]
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
    DISPATCHER -->|"路由执行"| T_BASH & T_ART & T_AST & T_WEB & P1

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
    participant LOAD as Isolated Loader
    participant SCHEMA as Schema Generator
    participant REG as Tool Registry
    participant HEALTH as Health Monitor

    Note over FS,HEALTH: === 启动时批量注册 ===

    SCAN->>FS: readdir("workspace/tools/built_in/")
    FS-->>SCAN: [os_bash.ts, file_ast.ts, web_scraper.ts, ...]

    loop 每个工具文件
        SCAN->>LOAD: spawn worker + import("./os_bash.ts")
        LOAD-->>SCAN: tool_contract {name, schema, invoke_endpoint, health_endpoint}
        SCAN->>SCHEMA: extractSchema(tool_contract)
        SCHEMA-->>SCAN: JSONSchema {name, params, returns}
        SCAN->>REG: register({<br/>  name: "os_bash",<br/>  schema: jsonSchema,<br/>  invoke_endpoint: "worker://tool/os_bash/invoke",<br/>  health_endpoint: "worker://tool/os_bash/health",<br/>  version: "1.0.0",<br/>  risk_level: "write_repo"<br/>})
    end

    Note over FS,HEALTH: === 运行时热加载 ===

    FS->>WATCH: Agent 写入新文件 plugins/log_parser.ts
    WATCH->>WATCH: debounce(1000ms)
    WATCH->>LOAD: verify signature + load in isolated worker
    LOAD-->>SCHEMA: tool_contract
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
  execution_scope: "local" | "global";
  requires_global_mutex?: boolean;
  queue_ticket?: string;
  global_lock_id?: string;
}

interface ToolResult {
  success: boolean;
  output?: string;
  display_preview?: string;
  raw_result_ref?: string;
  exit_code?: number;
  files_changed?: string[];
  duration_ms: number;
  truncated: boolean;
  raw_length?: number;
  total_chars?: number;
  total_lines?: number;
  content_type?: "text/plain" | "application/json" | "text/csv" | "application/xml";
  file_hash?: string;         // 读取类工具返回文件指纹
}
```

并发写保护扩展契约：

```typescript
interface EditFileArgs {
  path: string;
  patch: string;
  original_file_hash: string; // 必填：乐观锁校验
}

interface ReadFileResult extends ToolResult {
  file_hash: string; // MD5 或 Last-Modified 指纹
}

interface ReadArtifactArgs {
  raw_result_ref: string;
  mode: "head_tail" | "jsonpath" | "line_range" | "grep";
  query?: string;            // jsonpath/grep pattern
  start_line?: number;
  end_line?: number;
}

interface ReadArtifactResult extends ToolResult {
  raw_result_ref: string;
  chunk_ref?: string;        // 二次切片引用
}
```

---

## 2. os_bash 系统命令执行器

### 2.1 模块职责

带超时、结构化结果封装、安全校验的 Bash/Shell 命令执行器。Agent 所有系统操作的基础能力。

### 2.2 执行流程架构

```mermaid
flowchart TB
    subgraph OsBash["⌨️ os_bash 工具"]
        direction TB
        VALIDATE["参数校验<br/>命令非空 · 合法字符"]
        SECURITY["安全预检<br/>调用 Policy Firewall"]
        SPAWN["进程管理<br/>child_process.spawn<br/>设定 timeout / cwd / env"]
        STREAM["输出采集<br/>stdout + stderr 实时读取<br/>内存上限 10MB"]
        TRUNCATE["输出封装层<br/>structured-safe preview<br/>artifact ref + metadata"]
        ART_GC["Artifact 生命周期管理<br/>TTL + Quota + LRU + 压缩"]
        FORMAT["结果封装<br/>exit_code + packaged_result"]
    end

    ART_READ["artifact_reader<br/>按 ref 分块读取/检索"]

    LLM["LLM tool_use"] -->|"cmd, timeout, cwd"| VALIDATE
    VALIDATE --> SECURITY
    SECURITY -->|"放行"| SPAWN
    SECURITY -->|"拦截"| ERROR["❌ Security Denied"]
    SPAWN --> STREAM
    STREAM --> TRUNCATE
    TRUNCATE --> ART_GC
    TRUNCATE --> FORMAT
    FORMAT -->|"tool_result"| LLM
    LLM -->|"raw_result_ref"| ART_READ
    ART_READ -->|"chunk/filtered result"| LLM

    style OsBash fill:#1a2a1a,stroke:#44aa44
```

### 2.3 执行与结果封装时序

```mermaid
sequenceDiagram
    participant LLM as LLM Client
    participant BASH as os_bash
    participant SEC as Security Kernel
    participant PROC as child_process
    participant PACK as Result Packager
    participant ART as Artifact Store
    participant AR as artifact_reader

    LLM->>BASH: tool_use("os_bash", {<br/>  cmd: "grep -R \"ERROR\" /var/log/nginx --line-number",<br/>  timeout: 30000,<br/>  cwd: "/var/log"<br/>})

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

    BASH->>PACK: classifyAndPackage(stdout, stderr)
    alt 结构化输出且超阈值 (JSON/XML/CSV)
        PACK->>ART: persist(raw_output, metadata)
        ART-->>PACK: raw_result_ref
        PACK-->>BASH: {raw_result_ref, display_preview, fetch_hints, truncated: false, structured: true}
    else 纯文本超阈值
        PACK-->>BASH: {display_preview, truncated: true, total_chars, total_lines}
    else 输出在阈值内
        PACK-->>BASH: {output, truncated: false}
    end

    BASH-->>LLM: tool_result({<br/>  success: true,<br/>  ...packaged_result,<br/>  exit_code: 0,<br/>  duration_ms: 8500<br/>})

    opt 预览不足以定位根因
        LLM->>AR: tool_use("artifact_reader", {<br/>  raw_result_ref,<br/>  mode: "jsonpath",<br/>  query: "$..error_code"<br/>})
        AR->>ART: fetchChunk(raw_result_ref, query)
        ART-->>AR: matched_chunk
        AR-->>LLM: tool_result({<br/>  chunk_preview,<br/>  chunk_ref,<br/>  matched_count<br/>})
    end
```

标准结果封装实现规范：

```typescript
interface OsBashResult {
  success: boolean;
  output?: string;
  display_preview?: string;
  raw_result_ref?: string;
  fetch_hints?: string[];
  structured: boolean;
  truncated: boolean;
  total_chars: number;
}

function executeWithResultPackaging(cmd: string): OsBashResult {
  const raw = execSync(cmd, { timeout: 30000 }).toString();
  const structured = looksLikeJson(raw) || looksLikeXml(raw) || looksLikeCsv(raw);

  if (structured && raw.length > 8000) {
    const rawResultRef = persistArtifact(raw, { content_type: detectContentType(raw) });
    return {
      success: true,
      raw_result_ref: rawResultRef,
      display_preview: buildStructuredPreview(raw),
      fetch_hints: ["jsonpath:$..error_code", "jsonpath:$..trace_id", "line_range:1200-1350"],
      structured: true,
      truncated: false,
      total_chars: raw.length
    };
  }

  if (!structured && raw.length > 8000) {
    return {
      success: true,
      display_preview: buildTextPreview(raw, 8000),
      structured: false,
      truncated: true,
      total_chars: raw.length
    };
  }

  return { success: true, output: raw, structured, truncated: false, total_chars: raw.length };
}
```

### 2.4 Artifact Store 生命周期与防爆配额

硬约束：

1. 所有 `raw_result_ref` 必须可被 `artifact_reader` 工具按 `jsonpath/line_range/grep` 方式读取。
2. Artifact Store 必须启用 `global_quota + tenant_quota + session_quota` 三层配额。
3. 默认保留策略：TTL 过期自动清理 + LRU 回收，禁止无限增长。
4. 当磁盘使用率超过高水位（例如 85%）时，系统必须进入降级模式：拒绝新大对象写入并告警。
5. 清理过程必须避开关键系统文件（EventBus/SQLite），并记录审计日志。

参考接口：

```typescript
interface ArtifactStorePolicy {
  global_quota_mb: number;
  session_quota_mb: number;
  ttl_hours: number;
  high_watermark_pct: number;
  low_watermark_pct: number;
}

interface ArtifactReader {
  readByRef(args: ReadArtifactArgs): Promise<ReadArtifactResult>;
}
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
        INDEX["分层读取器<br/>skeleton/index/chunk<br/>避免 30k 行全量加载"]
        PARSE["AST 解析器<br/>TypeScript: ts-morph<br/>Python: ast / LibCST<br/>Markdown: mdast"]
        LOCATE["定位器<br/>按函数名 · 类名 · 行号<br/>精确定位修改目标"]
        HASHCHK["乐观锁校验<br/>对比 original_file_hash"]
        REBASE["冲突重基器<br/>语义区域重算 + 最小差异合并"]
        BACKOFF["退避协调器<br/>指数退避 + 抖动 + 最大重试窗口"]
        PATCH["补丁引擎<br/>AST 级别精确替换<br/>保持格式化"]
        VALIDATE["变更校验<br/>语法检查 · 类型检查<br/>diff 生成"]
        WRITE["原子写入<br/>tmp写入 → rename<br/>防止部分写入"]
    end

    LLM["LLM tool_use"] -->|"file, target, patch"| INDEX
    INDEX --> PARSE
    PARSE --> LOCATE
    LOCATE --> HASHCHK
    HASHCHK -->|"✅ hash一致"| PATCH
    HASHCHK -->|"❌ hash冲突"| REBASE
    REBASE -->|"可自动重基"| PATCH
    REBASE -->|"冲突过深"| BACKOFF
    BACKOFF -->|"达到重试上限"| ERROR["返回并发冲突错误 + 协调建议"]
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
    participant SKEL as file_ast_skeleton
    participant PARSER as AST Parser
    participant COORD as Concurrency Coordinator
    participant FS as File System

    LLM->>AST: tool_use("file_ast", {<br/>  path: "src/server.ts",<br/>  target: {type: "function", name: "handleRequest"},<br/>  patch: "function handleRequest(req) {\n  // 新实现\n}",<br/>  original_file_hash: "md5:9f0ab..."<br/>})

    AST->>SKEL: read_skeleton("src/server.ts", {<br/>  mode: "index",<br/>  include: ["imports", "symbols", "function_ranges"]<br/>})
    SKEL-->>AST: code_index + symbol_table + hotspots

    AST->>AST: 计算 current_file_hash
    AST->>AST: 对比 current_file_hash vs original_file_hash
    alt hash 不一致
        AST->>COORD: trySemanticRebase(path, target_range, patch)
        alt 可自动重基
            COORD-->>AST: rebased_patch + refreshed_hash
            AST->>FS: readChunkByRange("src/server.ts", target_range ± context)
            FS-->>AST: focused_source
        else 冲突过深
            COORD-->>AST: conflict_ticket + backoff_ms
            AST-->>LLM: tool_result({<br/>  success: false,<br/>  error: "Hash conflict (deep). Retry with conflict_ticket.",<br/>  conflict_ticket,<br/>  backoff_ms<br/>})
        end
    else hash 一致
    AST->>FS: readChunkByRange("src/server.ts", target_range ± context)
    FS-->>AST: focused_source
    AST->>PARSER: parse(focused_source, "typescript")
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
    end
```

### 3.4 巨型单体文件与并发冲突治理（新增）

硬约束：

1. 对超大文件（例如 > 5,000 行）默认走 `file_ast_skeleton` 分层读取，禁止直接全量正文回读。
2. `file_ast` 必须支持按符号/行段定向读取（`readChunkByRange`），只拉取目标区域与最小上下文。
3. hash 冲突时禁止无脑“全量重读重试”，必须先走 `trySemanticRebase` 快速路径。
4. 冲突重试必须带指数退避与冲突票据（`conflict_ticket`），防止并发活锁风暴。
5. 超过重试窗口后升级到 Router 协调或人工仲裁，而不是持续消耗预算重试。

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

## 6. sleep_and_watch / sleep_until / schedule_cron 时空控制工具

### 6.1 模块职责

让 Agent 能够挂起自身等待特定条件或时间，以及设定定期巡检任务。这是长程自主运行与零 Token 空转的关键能力。

硬约束：

1. 严禁轮询式监控（如每分钟唤醒一次询问状态）。
2. 监控类场景优先使用 `sleep_and_watch(log_file, regex)`。
3. 休眠期间由宿主接管日志监听与事件监听，模型会话内存释放。
4. 日志监听必须具备轮转容错（`tail -F` 语义：inode 变更后自动重开）。
5. 监听 regex 必须通过复杂度校验并设置匹配超时，禁止灾难性回溯模式拖垮宿主。

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
            S_WATCH["日志监听条件<br/>sleep_and_watch('/var/log/nginx/error.log', 'upstream timed out')"]
        end

        subgraph Cron["schedule_cron"]
            C_PATROL["巡检任务<br/>'0 */6 * * *' 每6h"]
            C_BACKUP["备份任务<br/>'0 3 * * *' 每天3点"]
            C_HEALTH["健康检查<br/>'*/5 * * * *' 每5min"]
        end

        WATCHER["条件监控器<br/>EventBus 订阅 + log tail 监听"]
    end

    S_EVENT -->|"订阅"| EB["Event Bus"]
    S_METRIC -->|"订阅"| WD["Watchdog Metrics Stream"]
    S_WATCH -->|"tail -F + safe-regex + timeout + rotate-safe reopen"| LOGD["Log Watch Daemon"]
    WATCHER -->|"条件满足"| WAKE["唤醒 Agent"]
    C_PATROL & C_BACKUP & C_HEALTH -->|"定时触发"| EB

    style Chronos fill:#1a1a2e,stroke:#6666ff
```

### 6.3 条件休眠时序

```mermaid
sequenceDiagram
    participant LLM as LLM Client
    participant SLEEP as sleep_and_watch
    participant EB as Event Bus
    participant LOG_MON as Log Watch Daemon
    participant META as Meta-Agent

    LLM->>SLEEP: tool_use("sleep_and_watch", {<br/>  log_file: "/var/log/nginx/error.log",<br/>  regex: "upstream timed out",<br/>  timeout: "24h",<br/>  on_wake: "诊断 nginx 错误"<br/>})

    SLEEP->>LOG_MON: start rotate-safe log watch (tail -F semantics)
    SLEEP->>SLEEP: 挂起 Agent 会话并释放上下文<br/>🔇 零 Token 消耗

    Note over SLEEP,META: Agent 完全休眠中...<br/>可能持续数小时<br/>Event Bus 持续监控

    LOG_MON->>EB: publish("wake.log_match", {<br/>  message: "upstream timed out",<br/>  file: "/var/log/nginx/error.log"<br/>})

    EB->>SLEEP: 条件匹配! 触发唤醒

    SLEEP->>META: wake_up({<br/>  trigger: "nginx upstream timed out",<br/>  slept_duration: "4h 23min",<br/>  original_instruction: "诊断 nginx 错误"<br/>})

    META->>META: 恢复认知上下文<br/>执行指定任务
```

---

## 7. Self-Evolution 自我进化工具集

### 7.1 模块职责

允许 Agent 读取/修改子 Agent 的提示词，以及自己编写新工具并注册。

安全补充：

1. `register_new_tool` 的不受信代码不得在宿主主进程内直接加载执行。
2. 动态工具注册必须走“隔离执行 + 签名校验 + 能力白名单”三层门禁。

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

    REG->>LOADER: register isolated plugin worker (no in-process untrusted import)
    LOADER->>REGISTRY: register(new_tool_module)
    REGISTRY->>REGISTRY: 更新 LLM tools 列表

    REG-->>AGENT: tool_result({<br/>  success: true,<br/>  tool_name: "log_pattern_analyzer",<br/>  message: "工具已注册，可在后续对话中使用"<br/>})

    Note over AGENT: Agent 现在多了一个新能力!
```

---

## 8. Sub-Agent Runtime 与 Scaffold Engine

### 8.1 模块职责

在当前设计中，开发任务执行由“子代理 + 脚手架”双组件完成：

1. `Sub-Agent Runtime`：并发调度 Frontend/Backend/Ops 子代理，汇聚结果。
2. `Scaffold Engine`：根据任务规格生成补丁骨架（路由、中间件、页面、测试模板）。
3. `Execution Bridge`：将子代理输出转换为 `file_ast/os_bash/git_operator` 可执行动作。
4. `Contract Gate`：并行分析前先冻结前后端接口契约，避免盲写错配。
5. `Workspace Transaction`：多文件补丁必须以事务方式提交，失败自动回滚，避免半写损坏态。

### 8.2 运行时架构

```mermaid
flowchart TB
    subgraph SARuntime["🤝 Sub-Agent Runtime"]
        direction TB
        PLANNER["Task Planner<br/>任务切片·依赖图"]
        CONTRACT_GATE["Contract Gate<br/>API契约协商·checksum冻结"]
        SPAWNER["Agent Spawner<br/>Frontend / Backend / Ops"]
        MERGER["Result Merger<br/>冲突检测·统一补丁"]
        MONITOR["Execution Monitor<br/>进度跟踪·停滞告警"]
    end

    subgraph Scaffold["🏗️ Scaffold Engine"]
        TEMPLATES["Template Registry<br/>RBAC / API / UI / Test"]
        GENERATOR["Scaffold Generator<br/>生成补丁骨架"]
        PATCH_BUILDER["Patch Builder<br/>最小差异补丁"]
    end

    DISPATCHER["Dispatcher"] -->|"任务规格"| PLANNER
    PLANNER --> CONTRACT_GATE
    CONTRACT_GATE --> SPAWNER
    SPAWNER -->|"子任务结果"| MERGER
    MERGER -->|"结构化变更意图"| GENERATOR
    GENERATOR --> PATCH_BUILDER
    PATCH_BUILDER -->|"patch plan"| TXN["Workspace Transaction"]
    TXN --> EXEC_BRIDGE["Execution Bridge"]
    EXEC_BRIDGE -->|"调用"| FILE_AST["file_ast"] & BASH["os_bash"] & GIT_OP["git_operator"]
    MONITOR --> MERGER

    style SARuntime fill:#2e1a3e,stroke:#8855cc
    style Scaffold fill:#1e2a3e,stroke:#5577cc
```

### 8.3 子代理协作与脚手架执行时序

```mermaid
sequenceDiagram
    participant DISP as Dispatcher
    participant RUNTIME as Sub-Agent Runtime
    participant CONTRACT as Contract Gate
    participant FE as Frontend Agent
    participant BE as Backend Agent
    participant OPS as Ops Agent
    participant SCF as Scaffold Engine
    participant TXN as Workspace Transaction
    participant EXEC as Execution Bridge
    participant TOOLS as file_ast/os_bash/git_operator

    DISP->>RUNTIME: dispatch(spec)
    RUNTIME->>RUNTIME: 拆分任务 + 依赖排序

    RUNTIME->>CONTRACT: propose_contract(spec)
    CONTRACT->>FE: freeze_api_contract(checksum, schema)
    CONTRACT->>BE: freeze_api_contract(checksum, schema)
    alt 契约未达成一致
        CONTRACT-->>RUNTIME: contract_mismatch (fail-fast)
        RUNTIME-->>DISP: blocked_until_contract_resolved
    else 契约一致
        CONTRACT-->>RUNTIME: contract_id + checksum
    end

    par 并行子代理分析
        RUNTIME->>FE: analyze(frontend_scope, contract_id)
        FE-->>RUNTIME: ui_patch_intent
    and
        RUNTIME->>BE: analyze(backend_scope, contract_id)
        BE-->>RUNTIME: api_patch_intent
    and
        RUNTIME->>OPS: analyze(runtime_scope)
        OPS-->>RUNTIME: verify_plan
    end

    RUNTIME->>SCF: build_scaffold(intents, contract_id)
    SCF->>SCF: 选择模板 + 生成补丁骨架
    SCF-->>RUNTIME: patch_blueprint

    RUNTIME->>TXN: begin_workspace_txn(patch_blueprint)
    TXN->>EXEC: compile_action_plan(patch_blueprint)
    EXEC->>TOOLS: apply patch set (ordered)
    alt 任一文件写入/验证失败
        TOOLS-->>EXEC: failure(file_n)
        EXEC-->>TXN: abort
        TXN->>TXN: rollback_all_files()
        TXN-->>RUNTIME: failed_rolled_back (clean_state)
    else 全部成功
        TOOLS-->>EXEC: tool_results
        EXEC-->>TXN: commit_ready
        TXN->>TXN: commit_all_files()
        TXN-->>RUNTIME: committed_results
    end
    RUNTIME-->>DISP: final_task_result
```

### 8.4 并行协作硬门禁（新增）

1. FE/BE 子代理并行分析前必须先达成 `contract_id + checksum`，未达成时禁止进入 scaffold。
2. `Scaffold Engine` 生成的多文件补丁必须在同一事务内提交，禁止半成功半失败落盘。
3. 任一文件冲突或策略拦截时，必须执行自动回滚并返回 `clean_state=true`。
4. 回滚后重试必须基于新的 `contract_id`，禁止沿用旧契约继续盲修。

---

## 9. snapshot_manager 快照管理器

### 9.1 模块职责

在每次重大修改前强制创建恢复点，支持一键回滚。快照能力不能绑定单一文件系统，必须按后端能力自适配并显式记录降级原因。

### 9.2 快照操作时序

```mermaid
sequenceDiagram
    participant SEC as Security Kernel
    participant SNAP as Snapshot Manager
    participant DET as Backend Detector
    participant FS as Snapshot Backend
    participant ART as Artifact Snapshot
    participant GIT as Git

    SEC->>SNAP: createSnapshot("pre-nginx-config-change")
    SNAP->>DET: detectSnapshotBackend()
    DET-->>SNAP: [zfs|btrfs|lvm|volume|artifact]

    par 文件系统/卷级快照
        alt 后端支持 ZFS/Btrfs/LVM/云盘快照
            SNAP->>FS: create_fs_snapshot("pre-nginx-config-change")
            FS-->>SNAP: snapshot_id="fs:pre-nginx-config-change"
        else 仅支持应用层归档
            SNAP->>ART: create_artifact_snapshot(workspace + config + metadata)
            ART-->>SNAP: snapshot_id="artifact:pre-nginx-config-change"
            SNAP->>SEC: raise_risk_level("degraded_snapshot_backend")
        end
    and Git 恢复点
        SNAP->>GIT: git stash + git tag snapshot/pre-nginx
    end

    GIT-->>SNAP: git_tag="snapshot/pre-nginx"

    SNAP-->>SEC: {snapshot_id, snapshot_backend, git_tag, timestamp, degrade_reason?}

    Note over SEC,GIT: ... Agent 执行操作 ...

    alt 需要回滚
        SEC->>SNAP: rollback(snapshot_id)
        alt fs/volume 快照
            SNAP->>FS: rollback_fs_snapshot(snapshot_id)
        else artifact 快照
            SNAP->>ART: restore_artifact(snapshot_id)
        end
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
            ART_R["🧾 artifact_reader"]
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
            SLEEP_["💤 sleep_and_watch / sleep_until"]
            CRON_["⏰ schedule_cron"]
        end

        subgraph EvoMCP["进化工具"]
            READ_P_["📖 read_prompt"]
            UPDATE_P_["✏️ update_prompt"]
            REG_TOOL_["🔌 register_tool"]
        end

        subgraph SubAgentFabric["子代理与脚手架"]
            SA_RUNTIME_["🤝 sub_agent_runtime"]
            SCAFFOLD_["🏗️ scaffold_engine"]
            EXEC_BRIDGE_["🔧 execution_bridge"]
        end
    end

    LLM["🤖 LLM Client"] -->|"tool_use"| HOST
    HOST --> REG
    REG --> BASH & ART_R & AST_ & SYS & GIT_ & SNAP_
    REG --> SEARCH_ & BROWSER_
    REG --> SLEEP_ & CRON_
    REG --> READ_P_ & UPDATE_P_ & REG_TOOL_
    REG --> SA_RUNTIME_ & SCAFFOLD_
    SA_RUNTIME_ --> EXEC_BRIDGE_
    EXEC_BRIDGE_ --> AST_ & BASH & GIT_

    %% 安全连线
    BASH & AST_ & SYS -->|"执行前"| SEC["🛡️ Security Kernel"]
    SNAP_ -->|"快照"| SEC

    style Limbs fill:#0a2e1a,stroke:#44ff88,color:#ccffee
```

---

## 11. 手脚层硬约束摘要（新增）

1. 读取类工具必须返回文件指纹（`file_hash`）。
2. 写入类工具必须携带 `original_file_hash`，冲突时硬错误返回。
3. 全局环境动作必须标记 `execution_scope="global"` 并申请全局互斥锁。
4. 结构化输出（JSON/XML/CSV）禁止字符级头尾截断，必须返回 `raw_result_ref + display_preview`。
5. 监控类任务必须优先 `sleep_and_watch`，禁止轮询空转消耗。
6. `register_new_tool` 只能注册到隔离 worker，宿主进程禁止直接加载不受信插件代码。
7. 自我进化相关验证必须防 Test Poisoning，裁判测试基线不可被被测任务直接改写。
8. `sleep_and_watch` 的 regex 必须具备复杂度门禁与匹配超时，禁止 ReDoS 风险模式。
9. `snapshot_manager` 必须支持多后端降级链路，且降级快照必须上抬风险等级并记录审计。
10. `raw_result_ref` 必须可被 `artifact_reader` 二次读取，禁止“只给引用不给读取路径”。
11. `file_ast` 面对巨型文件必须先走 `file_ast_skeleton` 分层读取，禁止默认全量正文加载。
12. hash 冲突必须先尝试语义重基并带退避，禁止无脑全量重读重试导致活锁。
13. FE/BE 子代理并行前必须通过 `Contract Gate` 冻结接口契约。
14. Scaffold 多文件落盘必须事务化（begin/commit/rollback），失败后保持 `clean_state=true`。
15. Artifact Store 必须启用 TTL+配额+高水位熔断，防止磁盘 DoS。

补充参考：`./13-security-blindspots-and-hardening.md`
