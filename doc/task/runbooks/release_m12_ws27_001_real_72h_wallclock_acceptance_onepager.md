# M12 一页式执行清单（WS27-001：真实 72h 墙钟验收）

适用任务：`NGA-WS27-001`  
默认分支：`modifier/naga`

## 1. 目标

- 为 `WS27-001` 补齐“真实 72h 墙钟运行”验收证据。
- 生成独立可审计报告，不与虚拟 72h 等效脚本混淆。

## 2. 关键脚本

- 脚本：`scripts/manage_ws27_72h_wallclock_acceptance_ws27_001.py`
- 状态文件：`scratch/reports/ws27_72h_wallclock_acceptance_ws27_001_state.json`
- 验收报告：`scratch/reports/ws27_72h_wallclock_acceptance_ws27_001.json`

## 3. 推荐执行顺序

1. 启动墙钟验收计时

```bash
.venv/bin/python scripts/manage_ws27_72h_wallclock_acceptance_ws27_001.py \
  --action start \
  --target-hours 72
```

2. 日常巡检（按需）

```bash
.venv/bin/python scripts/manage_ws27_72h_wallclock_acceptance_ws27_001.py \
  --action status
```

3. 满 72h 后收口验收（严格模式）

```bash
.venv/bin/python scripts/manage_ws27_72h_wallclock_acceptance_ws27_001.py \
  --action finish \
  --strict
```

## 4. 判定标准

- 收口报告 `passed=true`。
- `checks.wallclock_target_reached=true`。
- `checks.required_reports_present=true`。

## 5. 风险与说明

- 该流程只补“墙钟验收证据”，不替代 `WS27-004` 全链与 `WS27-006` 放行聚合。
- 若中途中断，可重新 `--action start --force-restart`，但需在签署记录中标注重启原因。
