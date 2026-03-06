> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS20-001 实施记录（API 契约冻结与版本策略）

## 任务信息
- Task ID: `NGA-WS20-001`
- Title: API 契约冻结与版本策略
- 状态: 已完成（进入 review）

## 本次范围（仅 WS20-001）
1. API 契约快照与弃用策略
- `apiserver/api_server.py`
  - 新增契约常量：
    - `API_DEFAULT_VERSION = v1`
    - `API_CONTRACT_VERSION = 2026-02-24`
    - `API_COMPATIBILITY_WINDOW_DAYS = 180`
  - 新增 `_build_api_contract_snapshot`：统一输出版本、兼容窗口、弃用路由策略
  - 新增 `_resolve_api_deprecation_policy`：按路由返回弃用元信息

2. 响应头级版本与弃用信号
- `apiserver/api_server.py`
  - 新增 `inject_api_contract_headers` 中间件：
    - 注入 `X-Embla-System-Api-Version`
    - 注入 `X-Embla-System-Contract-Version`
    - 对未版本化且标记弃用的路由注入：
      - `Deprecation: true`
      - `Sunset`
      - `Link: <successor-version>`

3. v1 路由别名与契约查询端点
- `apiserver/api_server.py`
  - 新增：
    - `GET /system/api-contract`
    - `GET /v1/system/api-contract`
    - `GET /v1/health`
    - `GET /v1/system/info`
    - `POST /v1/chat`
    - `POST /v1/chat/stream`
  - `GET /` 和 `GET /system/info` 的版本号改为读取配置版本（不再硬编码）

4. 回归测试
- 新增 `tests/test_embla_core_release_compat_gate.py`
  - 契约快照字段检查
  - 弃用策略映射检查
  - v1 路由注册检查
  - 响应头注入检查（版本头 + 弃用头）

## 验证命令
- `.\.venv\Scripts\python.exe -m ruff check tests/test_embla_core_release_compat_gate.py`
  - 结果: `All checks passed`
- `powershell -ExecutionPolicy Bypass -File scripts/run_tests_safe.ps1 tests/test_embla_core_release_compat_gate.py tests/test_mcp_status_snapshot.py`
  - 结果: `6 passed`
- `powershell -ExecutionPolicy Bypass -File scripts/run_tests_safe.ps1 tests/test_embla_core_release_compat_gate.py tests/test_risk_gate_ws10_005.py tests/test_tool_receipt_ws10_004.py tests/test_policy_firewall.py tests/test_agentic_loop_contract_and_mutex.py tests/test_global_mutex.py tests/test_native_executor_guards.py tests/test_process_lineage.py tests/test_native_tools_runtime_hardening.py tests/test_gc_memory_card_injection.py tests/test_mcp_status_snapshot.py`
  - 结果: `75 passed`

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `apiserver/api_server.py; tests/test_embla_core_release_compat_gate.py; doc/task/implementation/NGA-WS20-001-implementation.md`
- `notes`:
  - `api contract freeze now exposes v1 strategy and compatibility window, adds versioned aliases for key routes, and injects deprecation/sunset/successor headers for unversioned legacy endpoints`

## Date
2026-02-24
