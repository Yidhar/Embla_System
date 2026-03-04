> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS24-001 实施记录（插件隔离 worker + IPC 协议）

## 1. 背景

当前 `mcp_registry` 对 manifest 的加载路径为宿主进程内 `importlib.import_module`。
这在不受信插件场景下存在宿主劫持风险，和目标态“插件必须走隔离 worker”不一致。

## 2. 实施内容

1. 新增隔离 worker 运行时
   - 新增 `mcpserver/plugin_worker_runtime.py`：
     - 子进程入口，按 `module/class` 动态加载插件并执行 `handle_handoff`。
     - 通过标准输入接收 JSON payload，输出 JSON/字符串结果。

2. 新增宿主侧 worker 代理
   - 新增 `mcpserver/plugin_worker.py`：
     - `PluginWorkerProxy`：宿主侧异步代理，内部通过子进程 IPC 调用插件。
     - `PluginWorkerSpec`：声明模块、类名、超时、解释器与 `PYTHONPATH` 注入。
     - 失败/超时返回结构化错误，避免宿主崩溃。

3. mcp_registry 接入运行模式判定
   - `mcpserver/mcp_registry.py` 新增：
     - `ISOLATED_WORKER_REGISTRY`；
     - `agentType` 与 `isolation.mode` 判定（`inprocess` / `isolated_worker`）；
     - 插件目录扫描（`NAGA_PLUGIN_MANIFEST_DIRS`，默认 `workspace/tools/plugins`）；
     - manifest 记录写入 `_runtime_mode/_manifest_path` 元数据。

4. mcp_manager 暴露隔离来源标记
   - `mcpserver/mcp_manager.py`：
     - `get_available_services_filtered()` 新增 `runtime_mode` 字段；
     - 隔离服务 `source=plugin_worker`，内置服务保持 `source=builtin`；
     - prompt 格式化时显示 `isolated_worker` 运行模式。

## 3. 变更文件

- `mcpserver/plugin_worker_runtime.py`
- `mcpserver/plugin_worker.py`
- `mcpserver/mcp_registry.py`
- `mcpserver/mcp_manager.py`
- `tests/test_mcp_plugin_isolation_ws24_001.py`
- `doc/task/23-phase3-full-target-task-list.md`
- `doc/00-omni-operator-architecture.md`

## 4. 验证记录

```bash
.\.venv\Scripts\python.exe -m pytest -q tests/test_mcp_plugin_isolation_ws24_001.py tests/test_mcp_status_snapshot.py tests/test_embla_core_release_compat_gate.py -p no:tmpdir
```

## 5. 结果

- 插件服务已具备“宿主不直接加载代码”的隔离执行路径。
- 内置 MCP 服务路径保持兼容，MCP 状态快照与前端 BFF 相关回归通过。
- 后续增强已完成并拆分记录：
  - `doc/task/implementation/NGA-WS24-002-implementation.md`
  - `doc/task/implementation/NGA-WS24-003-implementation.md`
  - `doc/task/implementation/NGA-WS24-004-implementation.md`
  - `doc/task/implementation/NGA-WS24-005-implementation.md`
  - `doc/task/implementation/NGA-WS24-006-implementation.md`
