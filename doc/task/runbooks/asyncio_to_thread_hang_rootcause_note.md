# asyncio.to_thread 挂起根因说明（本机环境）

最后更新：2026-02-25  
适用范围：`当前 Embla 开发分支`（本机开发环境）

## 1. 问题现象

- `await asyncio.to_thread(...)` 能返回结果。
- 但 `asyncio.run(main())` 在 `main` 结束后不退出，进程持续挂起。
- `loop.run_in_executor(None, ...)` 也会出现同类挂起。

## 2. 复现环境与版本

- `.venv/bin/python --version` -> `Python 3.11.14`
- `python3 --version` -> `Python 3.13.7`
- `uv --version` -> `uv 0.10.6`

两套 Python 都可复现，说明不是单一解释器版本问题。

## 3. 最小复现（可直接执行）

```bash
timeout 8s .venv/bin/python - <<'PY'
import asyncio

async def main():
    value = await asyncio.to_thread(lambda: "ok")
    print("val", value, flush=True)

asyncio.run(main())
print("done", flush=True)
PY
```

预期异常现象：只打印 `val ok`，不会打印 `done`，最终被 `timeout` 杀掉。

## 4. 根因证据

1. 栈定位  
- 主线程卡在 `asyncio/runners.py -> Runner.close()`  
- 具体阻塞点是 `loop.run_until_complete(loop.shutdown_default_executor())`

2. 关键底层证据  
- 在当前环境直接执行 `socket.socketpair()` 后 `send()` 会返回 `PermissionError(1, 'Operation not permitted')`。  
- `asyncio` 的 `call_soon_threadsafe()` 依赖 `_write_to_self()`（向 self-pipe 写入 1 字节）唤醒 selector。  
- `_write_to_self()` 内部会吞掉 `OSError`，因此出现“回调已入队但 loop 没被唤醒”，形成无限等待。

3. 结论  
- 挂起不是业务代码逻辑死循环。  
- 根因是当前环境（已知包含代理/运行策略限制）导致 asyncio 线程唤醒通道不可用，从而影响默认线程池关闭与跨线程回调投递。

## 5. 工程化对策（已落地）

1. 新增统一适配层  
- 文件：`system/asyncio_offload.py`
- 策略：
  - 优先 `asyncio.to_thread`（环境可用时）
  - 检测到 wakeup 不可用时，切换到“线程池 + 事件循环轮询”回退路径（不依赖 `call_soon_threadsafe`）

2. 已切换调用点  
- `guide_engine/query_router.py`
- `apiserver/api_server.py`
- `summer_memory/memory_manager.py`
- `system/background_analyzer.py`
- `mcpserver/plugin_worker.py`
- `mcpserver/agent_open_launcher/comprehensive_app_scanner.py`

3. 补充单测  
- `tests/test_asyncio_offload.py`

## 6. 回归建议

```bash
.venv/bin/python -m ruff check \
  system/asyncio_offload.py \
  guide_engine/query_router.py \
  apiserver/api_server.py \
  summer_memory/memory_manager.py \
  system/background_analyzer.py \
  mcpserver/plugin_worker.py \
  mcpserver/agent_open_launcher/comprehensive_app_scanner.py \
  tests/test_asyncio_offload.py

.venv/bin/python -m pytest -q \
  tests/test_asyncio_offload.py \
  tests/test_native_tools_runtime_hardening.py \
  tests/test_native_tools_artifact_and_guard.py \
  tests/test_native_executor_guards.py -p no:tmpdir
```

