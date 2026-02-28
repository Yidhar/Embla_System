> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS28-024 实施记录（Brainstem Supervisor 接入 main.py 主启动链）

最后更新：2026-02-27  
任务状态：`done`  
优先级：`P1`  
类型：`refactor`

## 1. 目标

将 Brainstem 控制面托管接入 `main.py` 主启动链，并移除 API lifespan 对该托管流程的重复执行分叉。

## 2. 代码改动

1. `main.py`
- 新增主启动链托管入口：`ServiceManager._bootstrap_brainstem_control_plane_main_startup(...)`。
- 启动流程在 `start_all_servers()` 中先执行 brainstem 托管，再启动 API/MCP/TTS 线程。
- 托管成功后设置 ownership 与去重环境变量：
  - `NAGA_BRAINSTEM_BOOTSTRAP_OWNER=main`
  - `NAGA_BRAINSTEM_AUTOSTART=0`
- 通过上述约定让 API 生命周期不再重复托管 brainstem。

2. `apiserver/api_server.py`
- 新增 ownership 感知：
  - `NAGA_BRAINSTEM_BOOTSTRAP_OWNER`
  - 当 owner 非 `api/apiserver` 时，`_should_bootstrap_brainstem_control_plane()` 返回 skip。
- shutdown 入口同样尊重 ownership，避免 API 在非 owner 模式下 stop 外部托管实例。

## 3. 测试改动

1. `tests/test_api_server_brainstem_bootstrap_ws28_018.py`
- 新增 startup skip 场景：owner=main 时跳过 API bootstrap。
- 新增 shutdown skip 场景：owner=main 时跳过 API stop。

2. `tests/test_main_brainstem_bootstrap_ws28_024.py`
- 新增主启动链托管成功场景：校验 owner/env 设置与 API lifespan 去重开关。
- 新增主启动链托管失败场景：校验不抢占 owner，并保留 API fallback。

## 4. 回归命令

```bash
.venv/bin/ruff check \
  tests/test_api_server_brainstem_bootstrap_ws28_018.py \
  tests/test_main_brainstem_bootstrap_ws28_024.py

.venv/bin/pytest -q \
  tests/test_api_server_brainstem_bootstrap_ws28_018.py \
  tests/test_main_brainstem_bootstrap_ws28_024.py
```

结果：通过。
