# WS19-007 Runbook: Daily Checkpoint 日结归档

## 1. 目标
- 每 24 小时生成一次可审计的运行总结与次日恢复卡片。
- 汇总最近窗口的 session/tool/artifact 关键信息，支持次日快速恢复。

## 2. 入口
- 引擎模块：`autonomous/daily_checkpoint.py`
- 执行脚本：`scripts/daily_checkpoint_ws19_007.py`

## 3. 标准执行命令
```bash
python scripts/daily_checkpoint_ws19_007.py \
  --archive logs/episodic_memory/episodic_archive.jsonl \
  --output logs/autonomous/daily_checkpoint/latest_checkpoint.json \
  --audit logs/autonomous/daily_checkpoint/daily_checkpoint_audit.jsonl \
  --window-hours 24 \
  --top-items 5 \
  --summary-lines 6
```

## 4. 输出文件
1. `latest_checkpoint.json`
   - `top_sessions`
   - `top_source_tools`
   - `key_artifacts`
   - `day_summary`
   - `recovery_card`
2. `daily_checkpoint_audit.jsonl`
   - 每次生成事件落盘（时间、窗口内记录数、输出路径）

## 5. 值班核验
1. `total_records_in_window` 非负，且随业务波动合理。
2. `recovery_card.next_actions` 有效，不为空时可直接用于次日启动。
3. 审计日志新增 `daily_checkpoint_generated` 记录。

## 6. 失败处理
1. archive 缺失：
   - 允许输出空报告，不中断流程。
2. 解析异常：
   - 跳过坏行并继续生成（避免全量失败）。
3. 输出目录无权限：
   - 切换到可写路径并保留错误记录。

## 7. 回滚策略
1. 若自动日结异常，回退到手工脚本执行。
2. 以 `daily_checkpoint_audit.jsonl` 为审计基线补录人工执行记录。
3. 不阻断主业务链路，日结恢复后再回填缺口。

## 8. 最后更新
- 2026-02-24
