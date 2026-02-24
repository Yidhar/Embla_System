# NGA-WS18-003 实施记录（Event Replay 与恢复路径）

## 任务信息
- Task ID: `NGA-WS18-003`
- Title: Event Replay 与恢复路径
- 状态: 已完成（进入 review）

## 本次范围（仅 WS18-003）
1. Replay 工具核心实现
- 新增 `autonomous/event_log/replay_tool.py`
  - `ReplayRequest`：trace/workflow/event_type + 时间窗口 + operator/reason
  - `EventReplayTool.replay(...)`：
    - 按过滤器读取事件链
    - 按时间窗口截取
    - 生成 `recovery_plan`
    - 写入 replay 审计日志（jsonl）
  - 默认读模式：`read_only=true`

2. CLI 入口
- 新增 `scripts/event_replay_ws18_003.py`
  - 支持参数：
    - `--trace-id`
    - `--workflow-id`
    - `--event-type`
    - `--start-time` / `--end-time`
    - `--event-log` / `--audit-log`
    - `--operator` / `--reason`
    - `--output`
  - 输出：匹配事件 + recovery_plan + audit_record（JSON）

3. 运行手册
- 新增 `doc/task/runbooks/event_replay_recovery_ws18_003.md`
  - 使用示例、审计要求、恢复建议、回退与排障。

4. 测试覆盖
- 新增 `autonomous/tests/test_event_replay_tool_ws18_003.py`
  - trace + 时间窗口过滤
  - recovery_plan 生成
  - audit 落盘
  - 无过滤器请求拒绝

## 验证命令
- `python -m ruff check autonomous/event_log/replay_tool.py scripts/event_replay_ws18_003.py autonomous/tests/test_event_replay_tool_ws18_003.py`
  - 结果: `All checks passed`
- `python -m pytest -q autonomous/tests/test_event_replay_tool_ws18_003.py autonomous/tests/test_event_store_ws18_001.py autonomous/tests/test_workflow_store.py autonomous/tests/test_system_agent_release_flow.py`
  - 结果: `passed`

## 交付结果与验收对应
- 指定窗口重放工具：已提供 CLI + 模块化 API。
- 审计记录：每次 replay 自动写入 `replay_audit.jsonl`。
- 可按 trace 复现链路：`trace_id` 过滤 + `recovery_plan.steps` 提供复现顺序。
- 回退策略：默认只读，恢复动作不直接改写线上状态。

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `autonomous/event_log/replay_tool.py; scripts/event_replay_ws18_003.py; autonomous/tests/test_event_replay_tool_ws18_003.py; doc/task/runbooks/event_replay_recovery_ws18_003.md; doc/task/implementation/NGA-WS18-003-implementation.md`
- `notes`:
  - `event replay tooling now supports trace/workflow/window filters with read-only recovery plans and audit jsonl records for every replay request`

## Date
2026-02-24
