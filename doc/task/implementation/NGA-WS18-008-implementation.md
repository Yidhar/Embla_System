> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS18-008 实施记录（Brainstem 守护进程打包与托管）

## 任务信息
- Task ID: `NGA-WS18-008`
- Title: Brainstem 守护进程打包与托管
- 状态: 已完成（进入 review）

## 本次范围（仅 WS18-008）
1. 守护进程监督器核心
- 新增 `system/brainstem_supervisor.py`
  - 服务规格：`BrainstemServiceSpec`
  - 运行状态：`BrainstemServiceState`
  - 动作输出：`SupervisorAction`
  - 核心监督器：`BrainstemSupervisor`
    - `register_service(...)`
    - `ensure_running(...)`
    - `mark_exit(...)`（异常退出自动拉起）
    - `get_state(...)`（状态查询）
    - `build_supervisor_manifest(...)`（状态清单）
    - `render_systemd_unit(...)`（systemd 模板）
    - `render_windows_recovery_template(...)`（Windows 恢复模板）

2. 自恢复与回退策略
- 异常退出在重启预算内自动重启（`action=restarted`）。
- 重启预算耗尽后，若配置 fallback，切换轻量模式（`action=fallback`, `mode=lightweight`）。
- 运行状态落盘（`state_file`），重启后可恢复 `restart_count/pid/mode/exit_code`。

3. 打包模板导出脚本
- 新增 `scripts/export_brainstem_service_template_ws18_008.py`
  - 一键导出：
    - `*.service`（systemd）
    - `*.windows-recovery.json`
    - `*.manifest.json`

4. 运维 Runbook
- 新增 `doc/task/runbooks/brainstem_supervisor_ws18_008.md`
  - 模板导出、托管策略、值班核验、回滚到轻量模式流程。

5. 测试覆盖
- 新增 `tests/test_brainstem_supervisor_ws18_008.py`
  - 异常退出自动重启 + 状态持久化
  - 重启预算耗尽后切换轻量模式
  - 部署模板渲染与 manifest 输出

## 验证命令
- `.\.venv\Scripts\python.exe -m ruff check system/brainstem_supervisor.py tests/test_brainstem_supervisor_ws18_008.py scripts/export_brainstem_service_template_ws18_008.py`
  - 结果: `All checks passed!`
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_brainstem_supervisor_ws18_008.py tests/test_watchdog_daemon_ws18_004.py tests/test_immutable_dna_ws18_006.py`
  - 结果: `passed`
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_agentserver_deprecation_guard_ws16_002.py tests/test_native_executor_guards.py tests/test_policy_firewall.py tests/test_global_mutex.py tests/test_process_lineage.py tests/test_native_tools_runtime_hardening.py tests/test_agentic_loop_contract_and_mutex.py tests/test_dna_change_audit_ws18_007.py tests/test_immutable_dna_ws18_006.py tests/test_loop_cost_guard_ws18_005.py tests/test_watchdog_daemon_ws18_004.py tests/test_embla_core_release_compat_gate.py tests/test_embla_core_release_compat_gate.py tests/test_llm_stream_json_protocol_ws28_035.py tests/test_mcp_status_snapshot.py tests/test_router_engine_prompt_profile_ws28_001.py tests/test_core_event_bus_consumers_ws28_029.py tests/test_llm_gateway_prompt_slice_ws28_002.py tests/test_memory_agents.py tests/test_chat_route_quality_guard_ws28_012.py`
  - 结果: `104 passed, 0 failed`

## 交付结果与验收对应
- deliverables“守护进程部署模板与自恢复策略”：已通过监督器模板渲染 + 导出脚本落地。
- acceptance“异常退出可自动拉起并保留状态”：已通过自动重启与状态持久化测试验证。
- rollback“回退现有轻量运行模式”：已通过 fallback 流程与 runbook 固化。

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `system/brainstem_supervisor.py; tests/test_brainstem_supervisor_ws18_008.py; scripts/export_brainstem_service_template_ws18_008.py; doc/task/runbooks/brainstem_supervisor_ws18_008.md; doc/task/implementation/NGA-WS18-008-implementation.md`
- `notes`:
  - `brainstem supervisor now provides persisted service state, abnormal-exit auto restart, restart-budget fallback to lightweight mode, and exportable systemd/windows deployment templates`

## Date
2026-02-24
