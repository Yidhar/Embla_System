> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS13 / WS14 P0 波次实施记录

## 任务覆盖
- WS13:
  - `NGA-WS13-002` 并行契约门禁（review）
  - `NGA-WS13-003` contract-aware scaffold 指纹（review）
  - `NGA-WS13-004` Workspace Transaction 管理器（review）
- WS14:
  - `NGA-WS14-001` Policy Firewall（done）
  - `NGA-WS14-002` 解释器入口硬门禁（done）
  - `NGA-WS14-003` Global Mutex TTL + Heartbeat + Fencing（review）
  - `NGA-WS14-005` Process Lineage 绑定与回收（review）
  - `NGA-WS14-006` Double-Fork 幽灵进程清理（in_progress）
  - `NGA-WS14-007` Sleep Watch ReDoS + rotate-safe（review）
  - `NGA-WS14-009` KillSwitch OOB 策略（review）

## 主要代码改动

### 1) WS14-001 Policy Firewall
- 新增: `system/policy_firewall.py`
  - capability allowlist
  - 关键工具 argv schema 校验（`run_cmd/write_file/workspace_txn_apply/sleep_and_watch/killswitch_plan`）
  - 命令混淆模式拦截（变量拼接/base64 pipe）
  - 拒绝审计日志（`logs/security/policy_firewall_audit.jsonl`）
- 接入: `apiserver/native_tools.py::NativeToolExecutor.execute`

### 2) WS14-002 解释器硬门禁
- 增强: `system/native_executor.py`
  - shell-string 维持硬门禁
  - 新增 argv 级门禁，防止 `run([...])` 绕过：
    - `python -c` / `bash -c` / `sh -c` / `node -e`
    - `powershell -EncodedCommand`
  - KillSwitch 命令校验接入（OOB marker）

### 3) WS14-003 全局锁
- 新增: `system/global_mutex.py`
  - lease acquire / renew / release
  - TTL 过期回收
  - fencing epoch 单调递增
  - takeover 时触发旧 epoch lineage 回收钩子
- 接入: `apiserver/agentic_tool_loop.py::_execute_tool_call_with_retry`
  - 对 `requires_global_mutex` 调用自动加锁
  - 执行中 heartbeat 续租
  - 透传 `_fencing_epoch` 到 native call

### 4) WS14-005/006 进程血缘
- 新增: `system/process_lineage.py`
  - `job_root_id + fencing_epoch` 绑定
  - 运行态/结束态审计
  - epoch 维度回收接口
- 接入: `system/native_executor.py`
  - `execute_shell/run` 执行生命周期注册
  - timeout/error/ok 结算写回
- 现状:
  - detached 进程默认阻断策略已生效（`nohup/setsid/docker run -d/start /b`）
  - 外部 runtime 深层双派生回收仍需继续完善（故 `NGA-WS14-006` 保持 `in_progress`）

### 5) WS14-007 Sleep Watch
- 新增: `system/sleep_watch.py`
  - regex 安全门禁（阻断潜在灾难性回溯模式）
  - 匹配超时预算（`asyncio.wait_for`）
  - rotate/truncate 容错重开（tail -F 语义）
- 接入工具: `apiserver/native_tools.py::sleep_and_watch`

### 6) WS14-009 KillSwitch OOB
- 新增: `system/killswitch_guard.py`
  - `validate_freeze_command`：阻断无 OOB 标记的 `OUTPUT DROP`
  - `build_oob_killswitch_plan`：生成 OOB allowlist 优先的冻结计划
- 接入:
  - `system/native_executor.py` 命令校验
  - `apiserver/native_tools.py::killswitch_plan` 工具

### 7) WS13-002/003/004 契约与事务
- 新增: `system/subagent_contract.py`
  - contract checksum / scaffold fingerprint
  - 并行变更契约校验
- 新增: `system/workspace_transaction.py`
  - `begin/apply_all/verify/rollback` 事务管理器
- 接入: `apiserver/native_tools.py::workspace_txn_apply`
  - 多文件变更强制契约门禁
  - 任一步骤失败全量回滚并返回 recovery_ticket
- 接入: `apiserver/agentic_tool_loop.py`
  - 并行 mutating call 契约不一致时自动降级串行（guardrail 事件）

## 验证

### 语法检查
- 命令:
  - `uv --cache-dir .uv_cache run python -m py_compile system/policy_firewall.py system/process_lineage.py system/global_mutex.py system/workspace_transaction.py system/subagent_contract.py system/sleep_watch.py system/killswitch_guard.py system/native_executor.py system/tool_contract.py apiserver/native_tools.py apiserver/agentic_tool_loop.py tests/test_native_executor_guards.py tests/test_policy_firewall.py tests/test_global_mutex.py tests/test_process_lineage.py tests/test_native_tools_runtime_hardening.py tests/test_agentic_loop_contract_and_mutex.py`
- 结果: ✅ 通过

### 定向回归（无 tmpdir 插件）
- 命令:
  - `uv --cache-dir .uv_cache run python -m pytest -q tests/test_native_executor_guards.py tests/test_policy_firewall.py tests/test_global_mutex.py tests/test_process_lineage.py tests/test_native_tools_runtime_hardening.py tests/test_agentic_loop_contract_and_mutex.py -p no:tmpdir`
  - `uv --cache-dir .uv_cache run python -m pytest -q tests/test_tool_contract.py::TestToolCallEnvelope tests/test_tool_contract.py::TestToolResultEnvelope tests/test_tool_contract.py::TestFieldConsistency tests/test_tool_contract.py::TestBuildToolResultWithArtifact::test_small_text_no_artifact tests/test_tool_contract.py::TestBuildToolResultWithArtifact::test_large_text_truncated tests/test_native_tools_artifact_and_guard.py::test_write_file_blocks_test_poisoning tests/test_native_tools_artifact_and_guard.py::test_file_ast_skeleton_and_chunk_read -p no:tmpdir`
- 结果: ✅ 通过

## 环境限制说明
- 该环境下 `pytest` 的 `tmpdir` 相关清理会触发权限异常（`WinError 5`），因此本轮采用 `-p no:tmpdir` 跑定向用例，并保留语法编译校验。

## 时间
2026-02-23
