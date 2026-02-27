# 任务状态维护协议（M0-M12）

文档状态：执行协议  
最后更新：2026-02-27

## 1. 目标

解决以下长期维护问题：

1. `09/99` 与 WS 任务文档状态漂移。
2. 历史 `done` 缺少可追溯复验日期，导致“是否真的完成”争议。
3. 新机器/新环境迁移后，无法快速识别需要重验的任务。

## 2. 单一状态源约定

1. 运行态状态源：`doc/task/09-execution-board.csv`。
2. 导入态镜像：`doc/task/99-task-backlog.csv`（由脚本从 `09` 同步）。
3. WS 文档（`10~20-ws-*.md`）默认按“设计与任务拆解说明”使用，不作为实时状态源。
4. `doc/task/23-phase3-full-execution-board.csv` 保留为 Phase3 快照视图；实时状态以 `09/99` 为准。

## 3. `done` 最低证据标准

1. `status=done` 的任务在 `09` 中必须具备：
- 可访问的 `evidence_link`。
- `notes` 内至少一个 `YYYY-MM-DD` 复验日期。
2. 若缺少日期证据，状态回调为 `review`，待复验后再恢复 `done`。

## 4. 维护流程（建议每次里程碑/机器迁移后执行）

1. 先同步 WS10-WS20 文档状态（消除 `- status:` 漂移；该步骤仅覆盖 `10~20-ws-*.md`）：

```bash
.venv/bin/python scripts/sync_ws_doc_status_from_board.py --apply
```

2. 生成审计报告：

```bash
.venv/bin/python scripts/audit_task_status_drift.py
```

3. 回调弱证据 `done`：

```bash
.venv/bin/python scripts/audit_task_status_drift.py --apply-demote-undated-done --apply
```

4. 保证 `99` 与 `09` 同步：

```bash
.venv/bin/python scripts/sync_task_backlog_status.py --apply
```

5. 运行文档一致性门禁：

```bash
.venv/bin/python scripts/validate_m12_doc_consistency_ws27_005.py --strict
```

## 5. 报告产物

1. 审计报告：`scratch/reports/task_status_audit_ws10_ws20.json`
2. 文档一致性报告：`scratch/reports/ws27_m12_doc_consistency_ws27_005.json`
3. WS 文档状态同步报告：`scratch/reports/ws_doc_status_sync_ws10_ws20.json`

## 6. 注意事项

1. 不直接手改 `99-task-backlog.csv` 状态；先改 `09`，再同步。
2. 不把 WS 文档里的 `- status:` 当作唯一状态真值。
3. 回调为 `review` 后，补充复验证据和日期，再回 `done`。
