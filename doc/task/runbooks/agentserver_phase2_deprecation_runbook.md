# WS16-002 Runbook: AgentServer Phase-2 弃用路径

## 1. 目标与边界
- 目标：在不破坏现网可用性的前提下，完成 `agentserver/` 的 Phase-2 弃用设计，明确删除顺序、替代链路与回退策略。
- 边界：本任务不直接删除 `agentserver/` 代码；先固化执行方案与门禁，避免“边迁移边扩散”。

## 2. 当前耦合基线（2026-02-24）
1. 启动耦合（仍保留）
- `main.py:550` `_start_agent_server` 仍存在动态导入：
  - `from agentserver.agent_server import app`
- 当前默认策略：不自动启动（仅兼容保留）。

2. 配置耦合（仍保留）
- `config.json.example:37` 仍有 `agentserver` 配置段。
- `system/config.py:71` 仍支持 `agentserver/agent_server/server_ports` 的兼容端口映射。

3. 文案与兼容说明耦合
- `apiserver/api_server.py:189` 保留 `_call_agentserver` 辅助函数（当前无核心链路依赖）。

## 3. 替代链路（目标态）
1. 工具执行链路
- 旧链路：`agentserver -> openclaw -> tool execution`
- 新链路：`apiserver/agentic_tool_loop.py -> native_tools.py / mcpserver/mcp_manager.py`

2. 自治执行链路
- 旧链路：`agentserver` 内调度逻辑
- 新链路：`agents/pipeline.py` + `core/security/lease_fencing.py` + `agents/runtime/workflow_store.py`（global mutex + outbox/inbox）

## 4. Phase-2 分阶段执行顺序
1. D0 冻结新增依赖（当前轮落地）
- 新增自动化守门测试：禁止新增 `from/import agentserver`（除历史 allowlist）。
- 目的：先阻断“新债务”。

2. D1 软切流量（兼容保留）
- 默认禁用 `agentserver` 自动启动，保持显式开关可回切。
- 前端/接口层将用户入口导向 `apiserver` 新链路，避免新增调用面。

3. D2 裁剪冗余接口
- 移除 `apiserver` 中未被调用的 agentserver 代理 helper。
- 移除 UI/BFF 里仅用于 AgentServer 的兼容轮询分支（若仍存在）。

4. D3 配置收口
- 从 `config.json.example` 下线 `agentserver` 字段，保留迁移脚本做旧配置投影/回退。
- `system/config.py` 保留一版兼容读取，下一版删掉兼容 alias。

5. D4 物理删除
- 删除 `agentserver/` 目录与 `main.py` 中 `_start_agent_server`。
- 更新 `doc/*` 与 runbook，宣告弃用完成。

## 5. 门禁与回退策略
1. 出场门禁（每阶段）
- 功能门禁：核心链路回归通过（工具调用、MCP 状态、自治调度）。
- 兼容门禁：旧配置可迁移、可回切（至少一个版本周期）。
- 依赖门禁：无新增 `agentserver` 直接导入。

2. 回退策略
- 回退触发：新链路故障影响主流程，或回归门禁不达标。
- 回退动作：
  - 恢复兼容开关（重新启用 agentserver 启动）
  - 回切配置备份（由迁移脚本 restore）
  - 保留旧端口映射一版周期

## 6. 验证清单
1. 依赖扩散守门
- `python -m pytest -q tests/test_agentserver_deprecation_guard_ws16_002.py`

2. 核心链路冒烟
- `python -m pytest -q tests/test_embla_core_release_compat_gate.py tests/test_mcp_status_snapshot.py`

3. 迁移脚本/配置兼容
- `python -m pytest -q tests/test_config_migration_ws16_004.py tests/test_contract_rollout_ws16_005.py`

## 7. 风险说明
1. 已知风险
- 历史代码与文档仍有 `AgentServer` 文案/兼容字段，属于计划内技术债。

2. 控制策略
- 先“冻结新增”，再“分阶段摘除”，避免一次性大删导致联动回归。

## 8. 任务归档
- 对应任务：`NGA-WS16-002`
- 关联任务：`NGA-WS16-003`、`NGA-WS16-004`、`NGA-WS16-005`
- 最后更新：2026-02-24
