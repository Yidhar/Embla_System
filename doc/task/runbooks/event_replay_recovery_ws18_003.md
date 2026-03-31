# WS18-003 Runbook: Event Replay 与恢复路径

## 1. 目标
- 在故障恢复场景下，按 `trace_id/workflow_id` 重放事件链路。
- 保证重放操作默认只读（drill 模式），并生成审计记录。

## 2. 工具入口
- CLI 脚本：`scripts/event_replay_ws18_003.py`
- 核心模块：`core/event_bus/replay_tool.py`

## 3. 快速使用
1. 按 trace 重放
```bash
python scripts/event_replay_ws18_003.py \
  --trace-id trace_abc123 \
  --operator oncall-ai \
  --reason "incident replay drill"
```

2. 按 workflow + 时间窗口重放并导出结果
```bash
python scripts/event_replay_ws18_003.py \
  --workflow-id wf-20260224-01 \
  --start-time 2026-02-24T00:00:00+00:00 \
  --end-time 2026-02-24T01:00:00+00:00 \
  --output scratch/replay_result.json
```

3. 指定日志路径
```bash
python scripts/event_replay_ws18_003.py \
  --event-log logs/autonomous/events.jsonl \
  --audit-log logs/autonomous/replay_audit.jsonl \
  --trace-id trace_abc123
```

## 4. 输出与审计
- 标准输出：JSON（匹配事件、恢复步骤、审计摘要）
- 审计日志：`logs/autonomous/replay_audit.jsonl`
  - 请求参数（operator/reason/filter/window）
  - 命中事件 ID/类型/trace/workflow
  - 命中数量

## 5. 恢复执行建议
1. 先只读重放确认链路完整性。
2. 校验 `recovery_plan.steps` 顺序是否符合预期。
3. 如需人工恢复，按 steps 顺序执行并记录偏差。
4. 完成后回填工单与 replay 审计记录编号。

## 6. 回退策略
- 本工具默认 `read_only=true`，不直接改写业务状态。
- 恢复动作由人工或上层编排器执行，保持可逆和可审计。

## 7. 排障
1. 错误：`ReplayRequest requires at least one filter`
- 必须提供 `trace_id/workflow_id/event_type` 至少一项。

2. 命中为空
- 检查时间窗口是否过窄。
- 检查 `trace_id/workflow_id` 是否与事件字段一致（优先看 envelope 中 `trace_id/workflow_id`）。

3. 审计未写入
- 检查 `--audit-log` 目录写权限。

## 8. 最后更新
- 2026-02-24
