# 04 模型协议与代理排障指南

## 1. 目标

本文档用于统一说明以下内容：

- 模型 API 协议路由策略（OpenAI 兼容 / Google 原生）
- Google 原生接口调用格式（`generateContent` / `streamGenerateContent` / `BidiGenerateContent`）
- 系统代理开关行为（含 Windows 系统代理）
- 日志字段含义与排障顺序

适用模块：

- `apiserver/llm_service.py`
- `system/background_analyzer.py`
- `agentserver/task_scheduler.py`
- `main.py`
- `frontend/src/views/ModelView.vue`

---

## 2. 关键配置项

配置路径：`config.json -> api`

- `base_url`
  - API 基地址。Google 推荐填写：`https://generativelanguage.googleapis.com/v1beta`
- `model`
  - 模型名。推荐填写：`gemini-2.5-flash`（无需 `models/` 前缀）
- `provider`
  - 提供商提示（`openai_compatible` / `google` / `auto`）
- `protocol`
  - 协议开关（`auto` / `openai_chat_completions` / `google_generate_content`）
- `google_live_api`
  - Google 流式模式开关。`false` 走 `streamGenerateContent`，`true` 走 `BidiGenerateContent`
- `applied_proxy`
  - 是否启用系统代理（HTTP 客户端 `trust_env=True`）
- `request_timeout`
  - 请求超时（秒）
- `extra_headers` / `extra_body`
  - 附加头与请求体扩展

---

## 3. 协议路由规则

### 3.1 自动路由（`protocol=auto`）

优先级：

1. `base_url` 命中 `generativelanguage.googleapis.com` -> 路由到 Google 原生协议
2. 否则按 `provider` 判断（`google/gemini` -> Google 原生；`openai/openai_compatible` -> OpenAI 兼容）
3. 无法判断时默认 OpenAI 兼容

### 3.2 强制路由

- `protocol=openai_chat_completions`：固定走 OpenAI 兼容
- `protocol=google_generate_content`：固定走 Google 原生

---

## 4. Google URL 规范化规则

后端会对输入进行“容错规范化”，最终统一成：

`{base}/models/{model}:{method}`

其中：

- `base` 默认为 `https://generativelanguage.googleapis.com/v1beta`
- `method` 取值：
  - `generateContent`
  - `streamGenerateContent`

### 4.1 可容错输入示例

以下都可被规范化为正确 Google URL：

- `base_url=https://generativelanguage.googleapis.com/v1beta/chat/completions`
- `base_url=https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent`
- `model=models/gemini-2.5-flash`
- `model=openai/gemini-2.5-flash`
- `model=gemini-2.5-flash:generateContent`

---

## 5. 请求模式映射

### 5.1 非流式

- 接口：`generateContent`
- URL：`https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`

### 5.2 流式（SSE）

- 接口：`streamGenerateContent`
- URL：`https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent`
- 查询参数：`alt=sse`

### 5.3 Live API（WebSocket）

- 接口：`BidiGenerateContent`
- URL：`wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent`
- 开关：`google_live_api=true`

---

## 6. 日志字段说明

### 6.1 主聊天链路（`apiserver/llm_service.py`）

会输出类似日志：

- `[LLM] Google request mode=streamGenerateContent ... url=... proxy=True`
- `[LLM] Google request mode=BidiGenerateContent ... url=... proxy=True`

说明：

- `mode`：实际调用方法
- `url`：脱敏后的完整请求地址（`key` 会被隐藏）
- `proxy`：当前请求是否启用系统代理

### 6.2 任务/分析链路

- `[TaskScheduler] Google request ...`
- `[ConversationAnalyzer] Google request ...`

这两条用于验证“后台压缩/分析”是否与主链路一致。

---

## 7. 系统代理行为（重点）

### 7.1 开关语义

- `applied_proxy=true`：允许使用系统代理（`trust_env=True`）
- `applied_proxy=false`：清理进程内 `HTTP(S)_PROXY/ALL_PROXY`，禁用代理

### 7.2 Windows 特殊处理

Windows 的“设置 -> 网络和 Internet -> 代理服务器”不一定在环境变量中。

为避免 `NO_PROXY` 干扰系统代理探测，启动时会：

1. 读取注册表代理（`ProxyServer` / `ProxyOverride`）
2. 若启用代理且进程内无 `HTTP(S)_PROXY`，把注册表代理同步到当前进程环境变量
3. 再设置 `NO_PROXY`（并合并系统 bypass 列表）

这保证 `httpx` 与 `websockets` 在进程内都能稳定读取到代理配置。

### 7.3 临时强制覆盖（仅当前进程）

- `NAGA_USE_SYSTEM_PROXY=1`：强制启用
- `NAGA_USE_SYSTEM_PROXY=0`：强制禁用

---

## 8. 推荐排障顺序

1. 检查配置
   - `protocol=auto`
   - `base_url=https://generativelanguage.googleapis.com/v1beta`
   - `model=gemini-2.5-flash`
   - `applied_proxy=true`（如需代理）
2. 看启动日志中的代理来源与生效配置
3. 看 `[LLM] Google request ... url=...` 是否符合预期
4. 若仍失败，区分是：
   - URL/鉴权问题（HTTP 4xx/5xx）
   - 连接问题（`All connection attempts failed`，通常是网络/代理连通性）

