> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS28-019 实施记录（脑干守护进程真实存活探测与自愈重启）

最后更新：2026-02-27  
任务状态：`done`  
优先级：`P0`  
类型：`hardening`

## 1. 背景问题

在既有实现中，`BrainstemSupervisor` 的运行判定主要依赖内存/状态文件中的 `running + pid`，未对 PID 做 OS 级存活探测。  
这会产生“假存活”窗口：

1. 子进程异常退出但状态仍显示 `running`。
2. `ensure_running()` 返回 `noop`，无法触发自愈重启。
3. 心跳/姿态层可能误报健康。

## 2. 目标

1. 在不破坏现有接口的前提下，引入 PID 存活探测。
2. 对 dead PID 自动触发重启（遵循既有 restart policy）。
3. 让健康快照能识别“pid 不存活”并输出明确 reason。

## 3. 代码改动

1. `system/brainstem_supervisor.py`
- 新增 `pid_alive` 注入点（默认使用 OS 探测）。
- `ensure_running()` 新增 dead PID 分支：
  - 若策略允许并有预算，返回 `restarted(reason=stale_pid_auto_restart)`。
  - 若预算耗尽且配置了 fallback，返回 `fallback`。
  - 其余场景继续执行显式启动，避免卡死在 stale state。
- `build_health_snapshot()` 新增 `service_pid_not_alive` 识别。

2. `scripts/run_brainstem_supervisor_ws23_001.py`
- `dry_run=True` 时注入 `pid_alive=lambda _: True`，避免测试环境 fake pid 被误判为 dead。

## 4. 测试与验证

新增/更新测试：

1. `tests/test_brainstem_supervisor_ws18_008.py`
- 覆盖 dead PID 自动重启。
- 覆盖健康快照 dead PID 判定。
- 既有 fake launcher 场景统一注入 `pid_alive`，保持语义稳定。

2. `tests/test_brainstem_supervisor_entry_ws23_001.py`
- 兼容 `pid_alive` 注入后的入口构造。

回归命令（本次执行）：

```bash
.venv/bin/ruff check \
  system/brainstem_supervisor.py \
  scripts/run_brainstem_supervisor_ws23_001.py \
  tests/test_brainstem_supervisor_ws18_008.py \
  tests/test_brainstem_supervisor_entry_ws23_001.py

.venv/bin/pytest -q \
  tests/test_brainstem_supervisor_ws18_008.py \
  tests/test_brainstem_supervisor_entry_ws23_001.py \
  tests/test_manage_brainstem_control_plane_ws28_017.py \
  tests/test_api_server_brainstem_bootstrap_ws28_018.py
```

结果：通过。

## 5. 影响范围

1. 改动仅影响 brainstem supervisor 托管链路，不改变外部 API 契约。
2. 对生产行为是正向收敛：减少“假存活”与自愈失效风险。
3. 与现有 WS28-017/018 启动托管链路兼容。
