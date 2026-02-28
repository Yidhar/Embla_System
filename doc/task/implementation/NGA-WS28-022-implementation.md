> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS28-022 实施记录（Immutable DNA 运行时注入）

最后更新：2026-02-27  
任务状态：`done`  
优先级：`P0`  
类型：`hardening`

## 1. 目标

将 Immutable DNA 从“发布前 gate”扩展为“每次 LLM 调用前运行时强校验”，确保 prompt 篡改无法绕过在线调用链。

## 2. 代码改动

1. `apiserver/llm_service.py`
- 新增运行时注入常量与环境开关：
  - `NAGA_IMMUTABLE_DNA_RUNTIME_INJECTION`
  - `NAGA_IMMUTABLE_DNA_PROMPTS_ROOT`
  - `NAGA_IMMUTABLE_DNA_MANIFEST_PATH`
  - `NAGA_IMMUTABLE_DNA_AUDIT_PATH`
- 在非流式与流式调用前统一执行 `ImmutableDNALoader.inject()`。
- 注入失败时 fail-closed：
  - 非流式返回 `Chat call blocked: ...`
  - 流式返回 SSE `error` chunk 并结束。

## 3. 测试改动

1. `tests/test_llm_service_immutable_dna_runtime_injection.py`
- 覆盖“注入成功”路径：断言首条 system message 为 DNA 注入块。
- 覆盖“manifest 篡改”路径：断言调用被阻断且不会触发 `acompletion()`。

## 4. 回归命令

```bash
.venv/bin/ruff check \
  apiserver/llm_service.py \
  tests/test_llm_service_immutable_dna_runtime_injection.py

.venv/bin/pytest -q tests/test_llm_service_immutable_dna_runtime_injection.py
```

结果：通过。
