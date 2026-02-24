# 06 结构化工具调用与本地优先执行（Omni-Operator 对齐版）

文档状态：开发预备（As-Is + Target-Aligned）
最后更新：2026-02-22

## 1. 核心原则

当前工具执行链只接受结构化函数调用，不再接受 legacy 文本协议。

允许的调用类型：

- `native_call`
- `mcp_call`
- `live2d_action`

不允许：

- Markdown fenced `tool` 代码块
- 文本内自由格式 `agentType` JSON

## 2. 当前执行管线（As-Is）

1. `apiserver/llm_service.py` 输出结构化工具调用数据。
2. `apiserver/agentic_tool_loop.py` 聚合并校验 `tool_calls`。
3. 按调用类型分发：
   - Native：`apiserver/native_tools.py`
   - MCP：`mcpserver/mcp_manager.py`
   - Live2D：UI action 通知
4. 将结果通过 SSE 事件回推到前端。

SSE 关键事件：

- `tool_calls`
- `tool_results`
- `tool_stage`
- `round_start`
- `round_end`

## 3. MCP Host + Tool Registry 映射

与 Omni-Operator 对齐关系：

- MCP Host：`mcpserver/mcp_server.py`（`/schedule`、`/call`、`/services`、`/status`）
- Tool Registry：`mcpserver/mcp_registry.py`（manifest 扫描、实例化注册）
- Tool Router：`mcpserver/mcp_manager.py`（本地优先 + mcporter 外部兜底）

执行策略：

1. 先查本地已注册 MCP 服务。
2. 本地失败后可按策略回退到 mcporter 外部服务。
3. 针对 codex 服务有专门规范化与降级逻辑。

## 4. Omni-Operator 安全层管线（当前落地）

### 4.1 调用前校验

`agentic_tool_loop` 当前已实现：

- 工具名必填校验
- 参数类型校验
- legacy 协议违规检测
- coding intent 的 codex-first 约束

### 4.2 Native 执行边界

`system/native_executor.py` 当前已实现：

- 项目根目录约束（禁止越界）
- 高风险 token 拦截（如 `del/rm/rmdir/format/diskpart/remove-item`）
- 路径穿越与 UNC 路径拦截
- 超时与输出边界控制

补充说明（安全边界）：

- token/正则拦截只是一层“快速止血”，不能单独作为最终安全边界。
- 对混淆命令（变量拼接、编码后执行、解释器二次执行）需通过“能力白名单 + 参数 schema + 风险门禁”补齐。

### 4.3 执行后反馈

- 工具执行状态统一写回 `tool_results` 事件。
- 阶段状态写回 `tool_stage`，可用于前端可视化与审计。

## 5. 与 Tool Contract 的关系

目标态（见 `00-omni-operator-architecture.md`）要求 Tool Contract 包含：

- `tool_name`
- `input_schema_version`
- `validated_args`
- `risk_level`
- `timeout_ms`
- `idempotency_key`
- `caller_role`
- `trace_id`

当前状态：

- 已具备结构化调用与参数校验基础。
- 仍需把上述字段提升为“统一强制契约”，并在 native/mcp 两条链路中一致执行。

## 6. I/O 截断与防爆工具链（目标态细化）

状态标记：`目标态规范`，当前实现部分具备（超时与路径边界），以下规则需继续补齐。

### 6.1 读取策略

1. 禁止全局大文件直读（禁止用 `cat` 直接读取大型文件）。
2. 强制优先使用结构化读取工具（`grep/awk/file_ast_skeleton`）。
3. `file_ast_skeleton` 仅返回代码骨架、函数签名与关键结构，不返回完整正文。

### 6.2 修改策略

1. 强制 diff/patch 路径提交修改。
2. 禁止“整文件重写输出”作为默认修改方式。
3. 写入前必须经过 Tool Contract 校验与风险门禁。

### 6.3 输出熔断器规范

强制规则：

1. 结构化输出（JSON/XML/CSV）禁止做字符级“头尾截断”。
2. 大响应应落盘为 artifact，并返回 `raw_result_ref + display_preview + truncated + total_chars/lines`。
3. 纯文本日志可截断预览，但必须显式携带截断元数据，避免模型误判为执行失败。
4. 返回 `raw_result_ref` 时必须可通过 `artifact_reader` 二次读取（`jsonpath/line_range/grep`）。
5. Artifact Store 必须具备 `TTL + quota + high-watermark` 防爆策略。

参考伪代码：

```ts
type ToolResultEnvelope = {
  display_preview: string;
  raw_result_ref?: string;
  fetch_hints?: string[];
  truncated: boolean;
  total_chars: number;
  content_type: "text/plain" | "application/json" | "text/csv" | "application/xml";
};

function buildToolResult(raw: string, contentType: string): ToolResultEnvelope {
  const total = raw.length;
  const isStructured = ["application/json", "text/csv", "application/xml"].includes(contentType);

  if (isStructured && total > 8000) {
    ensureArtifactQuota(); // 高水位/配额检查
    const ref = persistArtifact(raw); // 写入对象存储/临时文件并返回引用
    return {
      display_preview: summarizeStructured(raw), // schema/keys/sample rows
      raw_result_ref: ref,
      fetch_hints: ["jsonpath:$..error_code", "jsonpath:$..trace_id"],
      truncated: true,
      total_chars: total,
      content_type: contentType as ToolResultEnvelope["content_type"],
    };
  }

  const preview = total > 8000 ? raw.slice(0, 8000) + "\n...[TRUNCATED]..." : raw;
  return {
    display_preview: preview,
    truncated: total > 8000,
    total_chars: total,
    content_type: "text/plain",
  };
}
```

## 7. 开发预备建议

1. 在 `agentic_tool_loop` 增加统一 Tool Contract 组装层。
2. 将风险等级（`read_only/write_repo/deploy/secrets`）纳入调用前门禁。
3. 在 `native_tools` 路径补齐“读取策略 + 修改策略 + 输出熔断器”三项硬约束。
4. 为关键工具调用补齐 `trace_id` 与审计落盘。

## 8. 交叉引用

- 总览：`./01-module-overview.md`
- 启动与调试：`./05-dev-startup-and-index.md`
- 自治 SDLC：`./07-autonomous-agent-sdlc-architecture.md`
- 工具治理规范：`./09-tool-execution-specification.md`
- 安全盲区与加固基线：`./13-security-blindspots-and-hardening.md`
