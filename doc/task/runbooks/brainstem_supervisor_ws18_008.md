# WS18-008 Runbook: Brainstem 守护进程打包与托管

## 1. 目标
- 将 Brainstem 关键服务以守护进程方式托管。
- 保证异常退出可自动拉起，并将运行状态落盘持久化。
- 当重启预算耗尽时，自动进入轻量回退模式（lightweight）。

## 2. 模块入口
- 监督器核心：`system/brainstem_supervisor.py`
- 模板导出脚本：`scripts/export_brainstem_service_template_ws18_008.py`

## 3. 快速导出部署模板
```bash
python scripts/export_brainstem_service_template_ws18_008.py \
  --service-name naga-brainstem \
  --command python main.py --headless \
  --working-dir E:/Programs/NagaAgent \
  --restart-policy on-failure \
  --max-restarts 5 \
  --restart-backoff 3 \
  --state-file logs/autonomous/brainstem_supervisor_state.json \
  --output-dir scratch/brainstem_templates
```

导出结果：
1. `scratch/brainstem_templates/naga-brainstem.service`（systemd 模板）
2. `scratch/brainstem_templates/naga-brainstem.windows-recovery.json`（Windows 恢复计划）
3. `scratch/brainstem_templates/naga-brainstem.manifest.json`（监督器清单）

## 4. 托管策略
1. `restart_policy=on-failure`：仅异常退出自动拉起。
2. `max_restarts`：超出后不再无限重启，避免重启风暴。
3. `lightweight_fallback_command`：超预算后切换轻量模式兜底。
4. `state_file`：记录 `pid/restart_count/mode/last_exit_code`，支持重启后恢复状态。

## 5. 运行时判断
1. 初次启动：`action=started`
2. 异常退出且预算内：`action=restarted`
3. 异常退出且预算耗尽 + 配置 fallback：`action=fallback`
4. 正常退出或策略禁止重启：`action=stopped`

## 6. 核验项（值班）
1. 状态文件 `logs/autonomous/brainstem_supervisor_state.json` 持续更新。
2. 异常退出后 `restart_count` 递增。
3. 达到重启上限后 `mode=lightweight`。
4. 模板中的 `Restart=`、`RestartSec=` 与预期策略一致。

## 7. 回滚策略（轻量模式）
1. 将服务运行方式切回轻量模式（`--lightweight`）。
2. 关闭/放宽守护策略，避免反复拉起造成资源抖动。
3. 在工单中记录状态快照（exit_code、restart_count、mode）并进入人工处理。

## 8. 最后更新
- 2026-02-24
