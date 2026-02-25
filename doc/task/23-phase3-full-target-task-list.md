# 23 M7 之后到 Omni 全目标态（Phase3 Full）任务清单

## 1. 目标与边界

- 目标: 在 `M7` 已完成（WS21/WS22）的基础上，继续推进到 `doc/00-omni-operator-architecture.md` 的全目标态。
- 范围: 脑干层独立化、插件隔离宿主、Event Bus 全量化、全链路观测与 72h 长稳验收。
- 非目标: 不回退已上线的 `M0-M8` 收口链路，不做一次性大爆炸替换。

## 2. 当前基线（2026-02-24）

- `M0-M5`: 已收口，`doc/task/09-execution-board.csv` 为 `76/76 done`。
- `M6-M7`: 已收口，`WS21 (6/6)` + `WS22 (4/4)` 完成。
- 当前阶段: `Phase3 Full` 增量落地启动（新增里程碑定义为 `M8-M12`）。

## 3. 里程碑与门禁（M8-M12）

| 里程碑 | 目标 | 出场条件（Exit Criteria） |
|---|---|---|
| `M8` 脑干控制面独立化 | Watchdog/DNA/KillSwitch 从“模块能力”升级为“独立可托管控制面” | 独立守护链路可启动、可恢复、可审计；发布门禁接入 DNA/KillSwitch 规则 |
| `M9` 插件隔离宿主 | `register_new_tool` 从宿主同进程执行迁移到隔离 worker | 不受信插件无法访问宿主写路径；劫持/逃逸演练通过 |
| `M10` Event Bus 全量化 | 事件总线从轻量日志演进为 Topic + Replay + Cron/Alert | 事件可订阅、可重放、可追责；幂等保障可验证 |
| `M11` 运行时稳态化 | 调度、租约、并发、回滚、观测形成统一闭环 | 关键混沌场景通过并具备 SLO 仪表盘 |
| `M12` Phase3 Full 验收 | 72h 长稳 + 发布收口 + 文档一致性完成 | 全门禁链通过，Phase3 Full 放行报告可审计 |

## 4. Lane 划分（全 AI Agent 并行）

| Lane | 责任域 | 典型产物 |
|---|---|---|
| `Lane-BS` | Brainstem 控制面（Watchdog/DNA/KillSwitch） | 守护进程、策略门禁、恢复脚本 |
| `Lane-PLG` | 插件隔离与工具宿主 | Plugin worker、IPC 协议、签名校验 |
| `Lane-EVT` | Event Bus/Replay/Cron-Alert | 事件总线、回放工具、幂等机制 |
| `Lane-RT` | Runtime/Scaffold 写路径收敛 | 原子提交流水线、冲突退避策略 |
| `Lane-OBS` | 观测、SLO、混沌验证 | 仪表盘、压力脚本、演练报告 |
| `Lane-REL` | 发布收口与文档一致性 | 门禁脚本链、Runbook、实现记录 |

## 5. 任务拆解（可直接派发）

| task_id | 里程碑 | lane | 优先级 | 依赖 | 交付物 | 验收标准 |
|---|---|---|---|---|---|---|
| `NGA-WS23-001` | M8 | Lane-BS | P0 | - | Brainstem Supervisor 独立启动入口与健康探针 | 守护进程异常后可自动恢复，恢复事件可审计 |
| `NGA-WS23-002` | M8 | Lane-BS | P0 | NGA-WS23-001 | Watchdog 动作桥接到 SystemAgent 调度拒绝链 | 超阈值动作能阻断任务并记录原因 |
| `NGA-WS23-003` | M8 | Lane-BS | P0 | - | Immutable DNA 校验接入发布门禁链 | 缺审批票据时发布门禁必拒绝 |
| `NGA-WS23-004` | M8 | Lane-BS | P0 | - | KillSwitch OOB 通道模板 + 回收脚本 | 冻结策略不导致云主机失联，且可带外恢复 |
| `NGA-WS23-005` | M8 | Lane-EVT | P1 | NGA-WS23-001 | Workflow outbox 到 Brainstem 事件桥接适配器 | 关键事件不丢失且可回放 |
| `NGA-WS23-006` | M8 | Lane-REL | P1 | NGA-WS23-002;NGA-WS23-003;NGA-WS23-004;NGA-WS23-005 | M8 门禁脚本 + Runbook | M8 回归脚本一次通过并产出报告 |
| `NGA-WS24-001` | M9 | Lane-PLG | P0 | NGA-WS23-006 | 插件隔离 worker（独立进程） + IPC 协议 | 插件代码无法直接调用宿主危险能力 |
| `NGA-WS24-002` | M9 | Lane-PLG | P0 | NGA-WS24-001 | `register_new_tool` 签名/清单/schema 校验 | 非签名或超权限插件注册失败 |
| `NGA-WS24-003` | M9 | Lane-PLG | P0 | NGA-WS24-001 | 插件资源限制（CPU/MEM/时限）与超时熔断 | 恶意插件不会拖垮宿主 |
| `NGA-WS24-004` | M9 | Lane-BS | P1 | NGA-WS24-001 | Plugin worker 生命周期与僵尸回收 | worker 崩溃后可回收且不留幽灵进程 |
| `NGA-WS24-005` | M9 | Lane-OBS | P1 | NGA-WS24-002;NGA-WS24-003;NGA-WS24-004 | 宿主劫持/逃逸混沌演练集 | 攻击样例均被拦截且有审计日志 |
| `NGA-WS24-006` | M9 | Lane-REL | P1 | NGA-WS24-005 | M9 发布门禁接入（插件隔离） | 发布前必须通过插件安全门禁 |
| `NGA-WS25-001` | M10 | Lane-EVT | P0 | NGA-WS24-006 | Topic 化 Event Bus 抽象层（替代纯日志模式） | 事件可按 topic 订阅并持久化 |
| `NGA-WS25-002` | M10 | Lane-EVT | P1 | NGA-WS25-001 | Cron/Alert 事件生产者接入 Event Bus | 定时与告警事件可进入统一总线 |
| `NGA-WS25-003` | M10 | Lane-EVT | P0 | NGA-WS25-001 | Replay 幂等锚点与去重策略强化 | 重放不会导致重复副作用 |
| `NGA-WS25-004` | M10 | Lane-RT | P1 | NGA-WS25-001 | 关键证据字段保真策略（TraceID/ErrorCode/路径） | GC 后硬字段召回率达标 |
| `NGA-WS25-005` | M10 | Lane-OBS | P1 | NGA-WS25-003;NGA-WS25-004 | Event/GC 质量评测基线脚本 | 回放与证据链指标稳定可回归 |
| `NGA-WS25-006` | M10 | Lane-REL | P1 | NGA-WS25-002;NGA-WS25-005 | M10 综合门禁脚本链 | M10 脚本链通过且报告完整 |
| `NGA-WS26-001` | M11 | Lane-RT | P0 | NGA-WS25-006 | SystemAgent 写路径强制收敛到 Scaffold/Txn | 禁止绕过原子提交的默认路径 |
| `NGA-WS26-002` | M11 | Lane-OBS | P0 | NGA-WS25-006 | rollout/fail-open/lease 统一指标与导出 | 可看见灰度命中率与失败预算 |
| `NGA-WS26-003` | M11 | Lane-BS | P0 | NGA-WS26-002 | fail-open 预算超限自动降级策略 | 超阈值自动切回 legacy 并告警 |
| `NGA-WS26-004` | M11 | Lane-BS | P1 | NGA-WS26-001 | 锁泄漏清道夫与 fencing 联动 | orphan 锁可自动回收且无误杀 |
| `NGA-WS26-005` | M11 | Lane-BS | P1 | NGA-WS24-004;NGA-WS26-004 | double-fork/脱离进程树回收链 | 幽灵进程可识别并回收 |
| `NGA-WS26-006` | M11 | Lane-REL | P1 | NGA-WS26-003;NGA-WS26-004;NGA-WS26-005 | M11 混沌门禁（锁泄漏/logrotate/double-fork） | 三类场景回归稳定通过 |
| `NGA-WS27-001` | M12 | Lane-OBS | P0 | NGA-WS26-006 | 72h 长稳耐久脚本与磁盘配额压测 | 无 ENOSPC/无未捕获异常/无事件丢失 |
| `NGA-WS27-002` | M12 | Lane-REL | P0 | NGA-WS26-006 | Legacy -> SubAgent Full cutover 方案与回滚窗 | 可灰度放量并可一键回退 |
| `NGA-WS27-003` | M12 | Lane-REL | P1 | NGA-WS27-002 | OOB 抢修 Runbook + 演练记录 | 云主机场景下可恢复可验证 |
| `NGA-WS27-004` | M12 | Lane-REL | P0 | NGA-WS27-001;NGA-WS27-002;NGA-WS27-003 | `release_closure_chain_full_m0_m12.py` | M0-M12 统一收口脚本一键执行成功 |
| `NGA-WS27-005` | M12 | Lane-REL | P1 | NGA-WS27-004 | 文档一致性收口（00/10/11/12/13 + task） | 文档状态与实现证据一致无冲突 |
| `NGA-WS27-006` | M12 | Lane-REL | P0 | NGA-WS27-005 | Phase3 Full 放行报告与签署模板 | 放行报告可追踪到代码、测试、runbook |

## 6. 可并行任务组（按依赖层）

| 并行组 | 可并行任务 | 前置依赖 |
|---|---|---|
| `G0` | NGA-WS23-001, NGA-WS23-003, NGA-WS23-004 | - |
| `G1` | NGA-WS23-002, NGA-WS23-005 | NGA-WS23-001 |
| `G2` | NGA-WS24-001 | NGA-WS23-006 |
| `G3` | NGA-WS24-002, NGA-WS24-003, NGA-WS24-004 | NGA-WS24-001 |
| `G4` | NGA-WS25-001 | NGA-WS24-006 |
| `G5` | NGA-WS25-002, NGA-WS25-003, NGA-WS25-004 | NGA-WS25-001 |
| `G6` | NGA-WS26-001, NGA-WS26-002 | NGA-WS25-006 |
| `G7` | NGA-WS26-003, NGA-WS26-004, NGA-WS26-005 | NGA-WS26-001;NGA-WS26-002 |
| `G8` | NGA-WS27-001, NGA-WS27-002 | NGA-WS26-006 |
| `G9` | NGA-WS27-003, NGA-WS27-004, NGA-WS27-005, NGA-WS27-006 | NGA-WS27-001;NGA-WS27-002 |

## 7. 执行建议（全 AI 团队）

- 按 `G0 -> G9` 顺序推进；同组任务按 lane 并行派发。
- 每个 `P0` 任务必须绑定至少 1 个自动化验证任务与 1 份 Runbook 更新。
- 每个里程碑结束时，先跑门禁脚本，再更新 `doc/00-omni-operator-architecture.md` 的证据矩阵与状态字段。

## 8. 本轮推进快照（2026-02-25）

- `NGA-WS23-001` 已落地第一版：
  - 新增独立入口：`scripts/run_brainstem_supervisor_ws23_001.py`
  - 新增默认服务规范：`system/brainstem_services.spec`
  - 新增健康探针快照：`system/brainstem_supervisor.py::build_health_snapshot`
  - 回归：`tests/test_brainstem_supervisor_entry_ws23_001.py`、`tests/test_brainstem_supervisor_ws18_008.py`
- `NGA-WS23-002` 已落地调度阻断桥接：
  - `SystemAgent` 新增 `watchdog` 配置块与调度前门禁判定
  - 当 `WatchdogDaemon` 返回 `pause_dispatch_and_escalate/throttle_new_workloads` 时，进入 `ReleaseGateRejected(gate=watchdog)` + `TaskRejected` 链路
  - 回归：`autonomous/tests/test_system_agent_watchdog_gate_ws23_002.py`、`autonomous/tests/test_system_agent_config.py`
- `NGA-WS23-003` 已接入发布预检：
  - 新增 DNA 门禁脚本：`scripts/validate_immutable_dna_gate_ws23_003.py`
  - 接入收口链：`scripts/release_closure_chain_m0_m5.py` (`T0A`)
  - 回归：`tests/test_ws23_003_immutable_dna_gate.py`、`tests/test_release_closure_chain_m0_m5.py`
- `NGA-WS23-004` 已落地可执行导出链路：
  - 新增 OOB 预案导出脚本：`scripts/export_killswitch_oob_bundle_ws23_004.py`
  - 产物包含 freeze plan + health probe plan + 双重校验结果
  - 回归：`tests/test_export_killswitch_oob_bundle_ws23_004.py`、`tests/test_native_executor_guards.py`
- `NGA-WS23-005` 已落地 outbox->Brainstem 事件桥接：
  - 新增桥接适配器：`system/brainstem_event_bridge.py`
  - `SystemAgent` outbox 分发链路接入 `BrainstemEventBridged` 事件发射（分发前桥接，保留 envelope 元数据）
  - 新增 smoke 与回归：`scripts/run_outbox_brainstem_bridge_smoke_ws23_005.py`、`autonomous/tests/test_system_agent_outbox_bridge_ws23_005.py`、`tests/test_brainstem_event_bridge_ws23_005.py`
- `NGA-WS23-006` 已落地 M8 门禁与收口链：
  - 新增 M8 门禁评估器与入口：`autonomous/ws23_release_gate.py`、`scripts/validate_m8_closure_gate_ws23_006.py`
  - 新增 M8 收口链：`scripts/release_closure_chain_m8_ws23_006.py`
  - M8 已接入全量发布链：`scripts/release_closure_chain_full_m0_m7.py`（新增 `m8` group）
  - 新增 runbook：`doc/task/runbooks/release_m8_phase3_closure_onepager_ws23_006.md`
  - 回归：`autonomous/tests/test_ws23_release_gate.py`、`tests/test_release_closure_chain_m8_ws23_006.py`、`tests/test_release_closure_chain_full_m0_m7.py`
- `NGA-WS24-001` 已落地第一版隔离 worker + IPC：
  - 新增隔离 worker 代理与子进程运行时：`mcpserver/plugin_worker.py`、`mcpserver/plugin_worker_runtime.py`
  - `mcp_registry` 新增运行模式判定（`inprocess` / `isolated_worker`）与隔离服务注册池
  - `mcp_manager` 服务视图新增 `runtime_mode` 与 `plugin_worker` 来源标记
  - 回归：`tests/test_mcp_plugin_isolation_ws24_001.py`
- `NGA-WS24-002` 已落地签名/清单/schema 校验：
  - 新增插件清单治理模块：`mcpserver/plugin_manifest_policy.py`
  - 隔离插件注册新增三层强校验：schema 白名单、`policy.scopes` allowlist、`signature(hmac-sha256)` 校验
  - 非签名、非 allowlist、超权限 scope 的插件在注册期硬拒绝，拒绝原因写入 `REJECTED_PLUGIN_MANIFESTS`
  - 回归：`tests/test_mcp_plugin_isolation_ws24_001.py::test_scan_rejects_unsigned_plugin_manifest_ws24_002`、`tests/test_mcp_plugin_isolation_ws24_001.py::test_scan_rejects_scope_not_allowlisted_ws24_002`
- `NGA-WS24-003` 已落地资源限制与超时熔断：
  - `PluginWorkerSpec` 新增 `payload/output` 预算、`timeout`、`cpu/memory` 限额和熔断阈值
  - 运行时新增 payload/output 预算门禁、超时错误分型、失败熔断（circuit open）与运行指标统计
  - `plugin_worker_runtime` 接入 `--max-memory-mb/--cpu-time-seconds`（POSIX best-effort `resource` 限额）
  - 回归：`tests/test_mcp_plugin_isolation_ws24_001.py::test_plugin_worker_timeout_and_circuit_ws24_003`、`tests/test_mcp_plugin_isolation_ws24_001.py::test_plugin_worker_output_budget_rejected_ws24_003`
- `NGA-WS24-004` 已落地生命周期与僵尸回收：
  - 插件调用过程接入 `system.process_lineage`，记录 `register_start/register_end`
  - worker 调用前新增 stale job 扫描回收；超时路径新增 `kill_job + orphan_scan` 闭环
  - 运行时指标增加 `stale_reaped_total`，可用于 M9 门禁观测
  - 回归：`tests/test_mcp_plugin_isolation_ws24_001.py::test_plugin_worker_reaps_stale_jobs_ws24_004`
