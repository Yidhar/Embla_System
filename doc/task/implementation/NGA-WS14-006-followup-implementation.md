> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS14-006 Follow-up 实施记录

## 任务信息
- 任务ID: `NGA-WS14-006`
- 标题: Double-Fork 幽灵进程清理
- 波次: W5
- 本次状态推进: `in_progress -> review`

## 本次新增能力

### 1) Orphaned Running Job 扫尾
- 文件: `system/process_lineage.py`
- 新增:
  - `reap_orphaned_running_jobs(...)`
  - `_is_pid_alive(...)`
  - `_list_process_rows(...)`
  - `_extract_signature_tokens(...)`
  - `_kill_by_signature(...)`
- 行为:
  - 当记录仍是 `running` 但 `root_pid` 已失效时，触发 orphan 扫描
  - 对 detached 启动特征命令（`nohup/setsid/docker run -d/start /b`）提取保守 signature
  - 进行 signature 匹配补偿回收，完成后写回 `register_end`

### 2) Fencing takeover 联动 orphan scan
- 文件: `system/process_lineage.py`
- 变更:
  - `reap_by_fencing_epoch(...)` 在常规 kill 之后，追加 orphan 扫描

### 3) kill_job fallback 清理
- 文件: `system/process_lineage.py`
- 变更:
  - `kill_job(...)` 在 `taskkill/killpg` 失败时，自动尝试 signature fallback
  - 审计 reason 增加 `signature_killed` 计数

## 回归验证
- 新增测试:
  - `tests/test_process_lineage.py::test_process_lineage_kill_job_fallback_signature`
  - `tests/test_process_lineage.py::test_reap_orphaned_running_jobs`
- 全链路回归命令:
  - `uv --cache-dir .uv_cache run python -m pytest -q tests/test_native_executor_guards.py tests/test_policy_firewall.py tests/test_global_mutex.py tests/test_process_lineage.py tests/test_native_tools_runtime_hardening.py tests/test_agentic_loop_contract_and_mutex.py`
- 结果: ✅ 通过（45 passed）

## 风险与边界
- 当前实现是保守 signature 匹配，降低误杀优先，仍不替代 runtime 原生 API（如容器平台级 cleanup）。
- 对外部 runtime 的深层资源回收（端口/volume 级）仍建议后续补充平台适配器，但不阻塞当前 W5 止血链路验收。

## 时间
2026-02-24
