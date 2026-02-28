> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS24-002 实施记录（`register_new_tool` 签名/清单/schema 校验）

## 1. 背景

`WS24-001` 仅完成了隔离 worker + IPC 通路，但注册期仍缺少强制信任链。
按 `doc/13-security-blindspots-and-hardening.md` 要求，动态插件必须具备：

1. 清单结构白名单（禁止隐式扩权字段）。
2. `policy.scopes` 显式能力约束（超权限硬拒绝）。
3. allowlist + signature 双重信任校验（非签名/非白名单拒绝）。

## 2. 实施内容

1. 新增插件清单治理模块
   - `mcpserver/plugin_manifest_policy.py`
   - 提供：
     - `validate_plugin_manifest()`：统一校验入口
     - `compute_manifest_signature()`：签名摘要（`hmac-sha256`）
     - allowlist/signing-keys/scope-allowlist 的环境变量解析

2. 隔离插件注册接入强校验
   - `mcpserver/mcp_registry.py`
   - 在 `runtime_mode=isolated_worker` 路径上强制执行清单校验：
     - schema 不匹配 -> 拒绝注册
     - scope 超白名单 -> 拒绝注册
     - signature 无效/缺失 -> 拒绝注册
   - 新增 `REJECTED_PLUGIN_MANIFESTS` 记录拒绝原因，便于审计和观测。

## 3. 变更文件

- `mcpserver/plugin_manifest_policy.py`
- `mcpserver/mcp_registry.py`
- `tests/test_mcp_plugin_isolation_ws24_001.py`
- `doc/task/23-phase3-full-target-task-list.md`
- `doc/00-omni-operator-architecture.md`

## 4. 验证记录

```bash
.\.venv\Scripts\python.exe -m pytest -q tests/test_mcp_plugin_isolation_ws24_001.py
```

关键断言覆盖：
- unsigned plugin 被拒绝；
- forbidden scope 被拒绝；
- signed + allowlisted manifest 才能注册。

## 5. 结果

- `register_new_tool` 的隔离注册路径已具备“签名 + allowlist + schema + scope”四重硬门禁。
- 非签名或超权限插件不再进入可执行态，注册期即失败并落审计原因。
