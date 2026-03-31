> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS26-005 实施记录（double-fork/脱离进程树回收链）

## 任务信息
- 任务ID: `NGA-WS26-005`
- 标题: double-fork/脱离进程树回收链
- 状态: 已完成

## 变更范围

1. 进程回收策略强化
- 文件: `system/process_lineage.py`
- 变更:
  - `kill_job()` 的 detached 清理由“仅 root kill 失败时触发签名扫描”升级为：
    - 对 `nohup/setsid/docker run -d|--detach/start /b/disown/daemonize` 类命令
    - **始终执行**保守签名扫描（排除 root pid）
  - 修复场景:
    - root 进程 kill 成功但 double-fork/脱离进程组子进程仍存活时，仍可被签名链回收。

2. detached 命令识别扩展
- 文件: `system/process_lineage.py`
- 变更:
  - `_extract_signature_tokens()` 扩展 detached marker：
    - `docker run --detach`
    - `disown`
    - `daemonize`
  - 降低对变体命令格式的漏检率。

3. 回归测试
- 文件: `tests/test_process_lineage.py`
- 新增:
  - `test_process_lineage_kill_job_signature_runs_even_when_root_kill_succeeds`
    - 验证 root kill 成功时仍触发 signature cleanup。
  - `test_extract_signature_tokens_supports_docker_detach_variant`
    - 验证 `docker run --detach` 变体可被识别并抽取签名 token。
- 关联验证:
  - `tests/test_chaos_runtime_storage.py`
  - `tests/test_global_mutex.py`
  - `tests/test_agentic_loop_contract_and_mutex.py`
  - `tests/test_chaos_lock_failover.py`

## 验证命令

1. 进程回收与双重派生链路
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_process_lineage.py tests/test_chaos_runtime_storage.py`

2. 锁/fencing 联动链路回归
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_global_mutex.py tests/test_agentic_loop_contract_and_mutex.py tests/test_chaos_lock_failover.py`

3. 静态检查
- `.\.venv\Scripts\python.exe -m ruff check system/process_lineage.py tests/test_process_lineage.py`

## 结果摘要

- double-fork/脱离进程树场景下，回收链不再依赖“root kill 必须失败”这一前置条件。
- 与 WS26-004 清道夫链结合后，`orphan lock -> fencing takeover -> detached ghost cleanup` 的关键链路已可自动回收并具备回归覆盖。
