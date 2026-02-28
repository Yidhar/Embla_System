# NGA-WS28-030 Legacy Shim 最终退役可执行卡

## 目标
将当前过渡期 shim 全量退役，收敛到 `core/*` 主命名空间，消除运行时与测试层对 legacy 兼容层的依赖。

本任务按三步推进：
1. 先替换调用点。
2. 再删除 shim。
3. 最后改测试并补门禁。

## 退役范围（当前 shim）
- `autonomous/event_log/event_schema.py`
- `autonomous/event_log/event_store.py`
- `autonomous/event_log/topic_event_bus.py`
- `system/global_mutex.py`
- `system/policy_firewall.py`
- `system/watchdog_daemon.py`
- `system/brainstem_supervisor.py`

## 当前引用基线（扫描结果）
运行路径/脚本路径仍有 legacy 引用：
- `autonomous/system_agent.py`（`autonomous.event_log`）
- `autonomous/event_log/cron_alert_producer.py`（`autonomous.event_log.event_store`）
- `autonomous/event_log/replay_tool.py`（`autonomous.event_log.event_store`）
- `scripts/event_replay_ws18_003.py`（`autonomous.event_log`）
- `scripts/chaos_lock_failover.py`（`system.global_mutex`）
- `scripts/export_brainstem_service_template_ws18_008.py`（`system.brainstem_supervisor`）

测试路径仍有 legacy 引用：
- `tests/test_global_mutex.py`
- `tests/test_chaos_lock_failover.py`
- `tests/test_policy_firewall.py`
- `tests/test_tool_schema_validation.py`
- `tests/test_watchdog_daemon_ws18_004.py`
- `tests/test_loop_cost_guard_ws18_005.py`
- `tests/test_brainstem_supervisor_ws18_008.py`
- `tests/test_brainstem_supervisor_entry_ws23_001.py`
- `tests/test_agentic_loop_contract_and_mutex.py`
- `tests/test_core_lease_fencing_ws28_029.py`
- `autonomous/tests/test_event_store_ws18_001.py`
- `autonomous/tests/test_topic_event_bus_ws25_001.py`
- `autonomous/tests/test_topic_event_bus_replay_idempotency_ws25_003.py`
- `autonomous/tests/test_cron_alert_producer_ws25_002.py`
- `autonomous/tests/test_event_replay_tool_ws18_003.py`

---

## Step 1: 先替换调用点（不删 shim）

### Card A1: 运行时 EventBus 调用点切换到 core
`优先级: P0`

`代码点`
- `autonomous/system_agent.py`
- `autonomous/event_log/cron_alert_producer.py`
- `autonomous/event_log/replay_tool.py`
- `autonomous/event_log/__init__.py`
- `scripts/event_replay_ws18_003.py`

`实施动作`
- 将 EventStore/EventSchema/TopicBus 的 import 全部改为 `core.event_bus`。
- `autonomous/event_log/__init__.py` 保留对外 API 名称，但改为从 `core.event_bus` re-export。
- 保证 `SystemAgent` 不再经由 `autonomous.event_log.event_store` shim 获取 EventStore。

`测试点`
- event replay、cron producer、system agent 初始化均可正常创建 EventStore。
- 事件写入/回放行为不变（topic replay + idempotency）。

`验收命令`
- `rg -n "from autonomous\\.event_log\\.event_store|from autonomous\\.event_log\\.event_schema" autonomous apiserver scripts --glob '!**/tests/**'`
- `.venv/bin/pytest -q autonomous/tests/test_event_store_ws18_001.py autonomous/tests/test_topic_event_bus_ws25_001.py autonomous/tests/test_topic_event_bus_replay_idempotency_ws25_003.py autonomous/tests/test_event_replay_tool_ws18_003.py`

`完成标准`
- 非测试路径不再直接 import `autonomous.event_log.event_store|event_schema`。
- 相关回归测试全绿。

### Card A2: 安全/监督调用点切换到 core
`优先级: P0`

`代码点`
- `scripts/chaos_lock_failover.py`
- `scripts/export_brainstem_service_template_ws18_008.py`
- 如有新增调用点，一并替换。

`实施动作`
- 将 `system.global_mutex` 切到 `core.security.lease_fencing` 或 `core.security` 导出。
- 将 `system.brainstem_supervisor` 切到 `core.supervisor.brainstem_supervisor`。

`测试点`
- chaos lock failover 场景行为不变。
- brainstem 服务模板导出与 spec 解析不变。

`验收命令`
- `rg -n "from system\\.global_mutex|from system\\.brainstem_supervisor|import system\\.global_mutex|import system\\.brainstem_supervisor" scripts autonomous apiserver system core --glob '!**/tests/**'`
- `.venv/bin/pytest -q tests/test_chaos_lock_failover.py tests/test_brainstem_supervisor_ws18_008.py tests/test_brainstem_supervisor_entry_ws23_001.py`

`完成标准`
- 非测试路径不再依赖 `system.global_mutex|system.brainstem_supervisor`。
- 关键脚本与相关测试通过。

### Card A3: 增加“无 legacy 运行时 import”检查脚本
`优先级: P1`

`代码点`
- 新增 `scripts/check_legacy_shim_imports_ws28_030.py`

`实施动作`
- 脚本扫描 `apiserver/ autonomous/ system/ scripts/ core/`（排除 `tests`）。
- 命中 legacy import 则输出文件+行号并返回非 0。

`测试点`
- 正常路径返回 0。
- 人工注入一个 legacy import 时返回 2 且报出命中点。

`验收命令`
- `.venv/bin/python scripts/check_legacy_shim_imports_ws28_030.py --strict`

`完成标准`
- 可作为后续发布门禁子步骤直接调用。

---

## Step 2: 再删 shim（保持 API 连续性）

### Card B1: 删除 system shim
`优先级: P0`

`代码点`
- 删除：`system/global_mutex.py`
- 删除：`system/policy_firewall.py`
- 删除：`system/watchdog_daemon.py`
- 删除：`system/brainstem_supervisor.py`
- 补齐：`core/security/__init__.py`、`core/supervisor/__init__.py` 导出

`实施动作`
- 删除以上 shim 文件。
- 将所有引用统一到 `core.security` / `core.supervisor`。
- 对需要 monkeypatch 的测试，改为 patch `core.*` 真实模块（不再依赖 shim 暴露的兼容钩子）。

`测试点`
- policy firewall、mutex、watchdog、brainstem supervisor 对应单测全绿。
- 无 `ModuleNotFoundError: system.*` 回归。

`验收命令`
- `rg -n "from system\\.global_mutex|from system\\.policy_firewall|from system\\.watchdog_daemon|from system\\.brainstem_supervisor|import system\\.global_mutex|import system\\.policy_firewall|import system\\.watchdog_daemon|import system\\.brainstem_supervisor" . --glob '!**/__pycache__/**'`
- `.venv/bin/pytest -q tests/test_policy_firewall.py tests/test_global_mutex.py tests/test_watchdog_daemon_ws18_004.py tests/test_brainstem_supervisor_ws18_008.py`

`完成标准`
- 代码库中无任何 `system.*` shim import。
- 对应测试通过。

### Card B2: 删除 autonomous event_log shim
`优先级: P0`

`代码点`
- 删除：`autonomous/event_log/event_schema.py`
- 删除：`autonomous/event_log/event_store.py`
- 删除：`autonomous/event_log/topic_event_bus.py`
- 修改：`autonomous/event_log/__init__.py`

`实施动作`
- 删 3 个 shim 文件。
- `autonomous/event_log/__init__.py` 直接从 `core.event_bus` re-export。
- 若 replay/producer 仍在 `autonomous/event_log`，仅保留业务辅助组件，不保留总线主实现。

`测试点`
- `autonomous.event_log` 对外导入仍可用（向后兼容 API 名称）。
- Topic replay/idempotency 行为保持。

`验收命令`
- `rg -n "autonomous/event_log/(event_schema|event_store|topic_event_bus)\\.py" -S`
- `.venv/bin/pytest -q autonomous/tests/test_event_store_ws18_001.py autonomous/tests/test_topic_event_bus_ws25_001.py autonomous/tests/test_topic_event_bus_replay_idempotency_ws25_003.py autonomous/tests/test_cron_alert_producer_ws25_002.py`

`完成标准`
- shim 文件已删除。
- 外部使用 `autonomous.event_log` 不破坏既有行为。

### Card B3: 将 Step A3 检查脚本接入 release chain
`优先级: P1`

`代码点`
- `scripts/release_closure_chain_full_m0_m12.py`
- `doc/task/runbooks/*` 对应步骤说明

`实施动作`
- 在 M12 治理组中加入 `check_legacy_shim_imports_ws28_030` 子步骤。
- strict 模式下命中即 fail。

`测试点`
- 正常路径全链通过。
- 人工制造一条 legacy import 后全链该组失败并给出定位。

`验收命令`
- `.venv/bin/python scripts/release_closure_chain_full_m0_m12.py --quick-mode --skip-m0-m11`

`完成标准`
- 退役状态进入标准门禁闭环。

---

## Step 3: 最后改测试（去兼容断言）

### Card C1: 测试 import 全迁移到 core
`优先级: P0`

`代码点`
- `tests/test_global_mutex.py`
- `tests/test_chaos_lock_failover.py`
- `tests/test_policy_firewall.py`
- `tests/test_tool_schema_validation.py`
- `tests/test_watchdog_daemon_ws18_004.py`
- `tests/test_loop_cost_guard_ws18_005.py`
- `tests/test_brainstem_supervisor_ws18_008.py`
- `tests/test_brainstem_supervisor_entry_ws23_001.py`
- `tests/test_agentic_loop_contract_and_mutex.py`
- `tests/test_core_lease_fencing_ws28_029.py`
- `autonomous/tests/test_event_store_ws18_001.py`
- `autonomous/tests/test_topic_event_bus_ws25_001.py`
- `autonomous/tests/test_topic_event_bus_replay_idempotency_ws25_003.py`
- `autonomous/tests/test_cron_alert_producer_ws25_002.py`
- `autonomous/tests/test_event_replay_tool_ws18_003.py`

`实施动作`
- 测试导入统一为 `core.event_bus`、`core.security`、`core.supervisor`。
- 删除针对 shim 的 monkeypatch/兼容行为断言，改为验证 core 模块行为。

`测试点`
- 历史基线能力保持（事件、锁、监督、门禁）。
- 新增无 shim 场景不回退。

`验收命令`
- `.venv/bin/pytest -q tests/test_policy_firewall.py tests/test_global_mutex.py tests/test_chaos_lock_failover.py tests/test_watchdog_daemon_ws18_004.py tests/test_brainstem_supervisor_ws18_008.py tests/test_brainstem_supervisor_entry_ws23_001.py tests/test_agentic_loop_contract_and_mutex.py tests/test_core_lease_fencing_ws28_029.py autonomous/tests/test_event_store_ws18_001.py autonomous/tests/test_topic_event_bus_ws25_001.py autonomous/tests/test_topic_event_bus_replay_idempotency_ws25_003.py autonomous/tests/test_cron_alert_producer_ws25_002.py autonomous/tests/test_event_replay_tool_ws18_003.py`

`完成标准`
- 所有核心测试不再引用 legacy shim。

### Card C2: 新增“退役完成”防回归测试
`优先级: P1`

`代码点`
- 新增 `tests/test_no_legacy_shim_imports_ws28_030.py`

`实施动作`
- 以静态扫描方式断言运行路径无 legacy shim import。
- 与 `scripts/check_legacy_shim_imports_ws28_030.py` 规则一致。

`测试点`
- 规则命中覆盖 7 个 shim 命名空间。

`验收命令`
- `.venv/bin/pytest -q tests/test_no_legacy_shim_imports_ws28_030.py`

`完成标准`
- CI 层面可长期阻断 shim 回流。

### Card C3: 全链终验
`优先级: P0`

`实施动作`
- 执行快速链 + 完整链（由人工窗口决定）。

`验收命令`
- 快速链：`.venv/bin/python scripts/release_closure_chain_full_m0_m12.py --quick-mode --skip-m0-m11`
- 全链：`.venv/bin/python scripts/release_closure_chain_full_m0_m12.py`

`完成标准`
- quick/full 两链路通过，且门禁报告不再出现 legacy shim 相关 reason code。

---

## 分片提交建议
1. `refactor(legacy): replace runtime callsites to core namespace`
2. `refactor(legacy): remove shim modules and wire release gate`
3. `test(legacy): migrate tests to core and add no-shim regression guard`

## 风险与回滚
- 风险1：测试 monkeypatch 钩子迁移后行为差异。  
  回滚：先回退 Card B1/B2，仅保留 Step 1 调用点替换。
- 风险2：`autonomous.event_log` 对外 API 变化导致脚本失败。  
  回滚：在 `autonomous/event_log/__init__.py` 暂时保留 re-export 桥接。
- 风险3：release chain 新增 gate 触发历史分支失败。  
  回滚：将 Card B3 的 strict 模式改为 warn-only 一版过渡。

