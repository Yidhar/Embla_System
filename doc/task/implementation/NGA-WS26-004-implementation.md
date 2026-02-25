# NGA-WS26-004 实施记录（锁泄漏清道夫与 fencing 联动）

## 任务信息
- 任务ID: `NGA-WS26-004`
- 标题: 锁泄漏清道夫与 fencing 联动
- 状态: 已完成

## 变更范围

1. 全局锁调用链接入“预清道夫扫描”
- 文件: `apiserver/agentic_tool_loop.py`
- 变更:
  - 在 `_execute_tool_call_with_retry()` 的全局互斥分支中，`acquire()` 前新增:
    - `scan_and_reap_expired(reason=tool_call_pre_acquire:...)`
  - 清道夫结果写入调用上下文:
    - `call["_mutex_scavenge_report"]`
    - `result["mutex_scavenge_report"]`
  - 当扫描本身报错时，采用非阻断策略:
    - 继续执行 `acquire()`
    - 回执中写入 `cleanup_mode=scan_error` + `scan_error=<ExceptionType>`

2. 心跳异常场景的补偿扫描
- 文件: `apiserver/agentic_tool_loop.py`
- 变更:
  - 当 lease heartbeat 失败时，错误结果中附加一次补偿扫描:
    - `scan_and_reap_expired(reason=tool_call_heartbeat_failure:...)`
  - 使“锁泄漏 -> 心跳异常 -> 清道夫尝试回收”形成闭环审计链。

3. 回归测试
- 文件: `tests/test_agentic_loop_contract_and_mutex.py`
- 新增:
  - `test_global_mutex_pre_acquire_scavenger_runs_and_attaches_report`
    - 验证预扫描执行、fencing 透传、结果携带清道夫报告。
  - `test_global_mutex_pre_acquire_scavenger_scan_error_is_non_blocking`
    - 验证扫描异常不阻塞主执行路径，且回执中包含扫描错误诊断。
- 关联验证:
  - `tests/test_global_mutex.py`
  - `tests/test_chaos_lock_failover.py`

## 验证命令

1. 互斥链路与清道夫回归
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_agentic_loop_contract_and_mutex.py tests/test_global_mutex.py tests/test_chaos_lock_failover.py`

2. 静态检查
- `.\.venv\Scripts\python.exe -m ruff check apiserver/agentic_tool_loop.py tests/test_agentic_loop_contract_and_mutex.py`

## 结果摘要

- 全局锁调用链现已具备“调用前自动清道夫扫描 + fencing 回执可见 + 扫描异常不阻断”的稳态能力。
- 结合既有 `GlobalMutexManager.scan_and_reap_expired()` 的 epoch 清理能力，`orphan lock` 可自动回收且具备无误杀基线回归覆盖。
