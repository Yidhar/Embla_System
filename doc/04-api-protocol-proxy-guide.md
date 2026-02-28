# 04 模型协议与代理指南（Embla_system 对齐版）

文档状态：开发预备（As-Is + Target-Aligned）
最后更新：2026-02-22

## 1. 目标

统一说明当前代码中的 LLM 路由、跨厂商接入方式与代理行为，避免继续使用旧的“Google 原生 generateContent 双栈”认知。

适用模块：

- `apiserver/llm_service.py`
- `system/background_analyzer.py`
- `main.py`（代理环境处理）
- `frontend/src/views/ModelView.vue`

## 2. 当前真实协议（As-Is）

当前后端在运行时统一走 `openai_chat_completions` 路径：

- `LLMService.PROTOCOL_OPENAI_CHAT = openai_chat_completions`
- `protocol=google/gemini/google_generate_content` 会被归一到 OpenAI 兼容路径
- Google base URL 会被规范化到 `.../v1beta/openai`

结论：

- 当前项目是“单协议内核 + 多 provider 适配”。
- 旧文档中的 `generateContent/streamGenerateContent/BidiGenerateContent` 主链描述已不适用于当前代码。

## 3. 多模型路由策略（OpenAI / Google / Anthropic）

### 3.1 OpenAI（稳定）

推荐配置：

```json
{
  "api": {
    "provider": "openai_compatible",
    "protocol": "auto",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4.1",
    "api_key": "<YOUR_KEY>"
  }
}
```

### 3.2 Google Gemini（稳定，OpenAI 兼容接入）

推荐配置：

```json
{
  "api": {
    "provider": "google",
    "protocol": "auto",
    "base_url": "https://generativelanguage.googleapis.com/v1beta",
    "model": "gemini-2.5-flash",
    "api_key": "<YOUR_KEY>"
  }
}
```

后端会自动规范化到：`https://generativelanguage.googleapis.com/v1beta/openai`。

### 3.3 Anthropic（开发预备说明）

当前代码没有独立 Anthropic 协议分支；建议优先采用 OpenAI 兼容网关方式接入 Anthropic 模型（例如通过 OpenRouter 或企业网关）。

推荐实践：

- 使用 OpenAI 兼容网关：`provider=openai_compatible`。
- 模型写成网关支持的 Anthropic 路由名（例如 `openrouter/...claude...`）。

说明：

- `llm_service.py` 当前显式的 `custom_llm_provider` 推断包含 `openai/openrouter/deepseek/google`。
- 直接 `anthropic/...` 前缀在本项目中属于“可尝试但需自测”路径，不作为默认稳定路径。

## 4. 关键配置项（`config.json -> api`）

- `api_key`：模型密钥。
- `base_url`：OpenAI 兼容基地址。
- `model`：模型名或 provider 前缀模型名。
- `provider`：`auto` / `openai_compatible` / `google`（UI 当前提供这三项）。
- `protocol`：建议 `auto`（当前最终仍归一到 `openai_chat_completions`）。
- `applied_proxy`：是否启用系统代理。
- `request_timeout`：请求超时秒数。
- `extra_headers` / `extra_body`：扩展参数（会过滤遗留 Google-only 字段）。

## 5. 代理行为（Windows 与跨链路一致性）

代理初始化在 `main.py` 完成，核心机制：

1. 读取 `config.api.applied_proxy` 与 `NAGA_USE_SYSTEM_PROXY`。
2. Windows 下可从注册表读取系统代理并同步为进程环境变量。
3. 强制维护 `NO_PROXY`（至少包含 `localhost/127.0.0.1/0.0.0.0`）。
4. 当代理关闭时，清理 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY` 相关变量。

效果：

- 主聊天链路与后台分析链路可共享同一代理语义。
- 降低“配置看似正确但请求不可达”的排障成本。

## 6. 排障流程（推荐）

1. 检查 `config.json`：`base_url/model/api_key/protocol/provider/applied_proxy`。
2. 启动后确认日志中的代理来源与生效值。
3. 观察 LLM 请求日志是否已落到预期 OpenAI 兼容地址。
4. 区分错误类型：
   - 4xx/5xx：多为鉴权或参数问题。
   - connect timeout / connection attempts failed：多为网络或代理连通问题。

## 7. 与 Embla_system 对齐说明

当前状态：

- 已实现统一 LLM Client 接口（Brain 层统一入口）。
- 已实现 provider 级适配和请求规范化。

待补齐：

- Tool Contract 级别的 provider 能力声明（例如工具调用支持矩阵）尚未与 LLM 路由配置联动。

## 8. Token 经济学与成本控制（目标态细化）

本节定义“防 Token 破产”架构，目标是将长程运行成本降低 90% 以上。  
状态标记：以下为 `目标态规范`，当前代码仅部分具备。

### 8.1 四重拦截机制（必须并存）

1. 网关层拦截：请求进入前做上下文分层、缓存标记、预算校验。
2. 大模型调度层拦截：按任务类型分流主模型/次模型/本地模型。
3. 工具层拦截：I/O 截断、只读骨架优先、禁止大文件直读。
4. 事件层拦截：空闲期释放会话，转为事件驱动唤醒。

### 8.2 Prompt Caching 分层规范

Block 1（静态头部）：

- 内容：系统角色、全局规范（如 `CLAUDE.md`）、MCP Tools JSON Schema。
- 标记：`cache_control: {"type":"ephemeral"}`。
- 体量基线：约 `10,000` tokens。
- 目标：命中率 `>=90%`。

Block 2（长期记忆层）：

- 内容：过去 24 小时摘要记忆。
- 标记：紧跟 Block 1，使用第二个 `ephemeral`。

Block 3（动态滑动窗口）：

- 内容：最近 3~5 轮真实交互。
- 标记：禁止缓存标记。
- 软阈值：超过 `10,000` tokens 强制触发 GC（证据保真归档 + 摘要索引 + 历史裁剪）。

### 8.3 异构模型分流（LLM Gateway）

系统必须封装统一 `LLM_Gateway` 执行分流：

| 任务类型 | 绑定模型 | 成本评级 | 场景 |
|---|---|---|---|
| 主控路由/代码生成 | `{用户设置主要模型}` | 极高 | Router 拆解、核心代码修改 |
| 后台清理/记忆压缩 | `{次要模型}` | 低 | 历史对话压缩、乱码清洗 |
| 重度日志解析 | 本地开源模型（Qwen/Llama） | 零 | 超长日志关键栈提取 |

## 9. 事件驱动休眠机制（目标态细化）

目标：消除轮询型 Token 空转。

规范：

1. 禁止“每分钟询问一次”轮询监控。
2. 提供 `sleep_and_watch(log_file, regex)` 工具。
3. 工具执行后由宿主进程接管日志监听（`tail -F` 语义：inode 变更重开）与 regex 触发。
4. 未触发前销毁当前大模型会话内存（Token 消耗归零）；触发后再重组 Prompt 唤醒模型。

## 10. 交叉引用

- 总览：`./01-module-overview.md`
- 开发启动：`./05-dev-startup-and-index.md`
- 工具调用：`./06-structured-tool-calls-and-local-first-native.md`
- 前后端边界：`./08-frontend-backend-separation-plan.md`
