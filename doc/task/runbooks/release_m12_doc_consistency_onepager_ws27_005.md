# M12 一页式执行清单（WS27-005：文档一致性收口）

适用任务：`NGA-WS27-005`  
默认分支：`modifier/naga`

## 1. 目标

- 在本机完成 `M12` 文档一致性终检，覆盖：
  - 执行看板 evidence 一致性
  - 核心架构文档存在性（`00/10/11/12/13` + `task`）
  - `WS27-001~004` 实施记录/runbook 完整性
  - `23-phase3` 任务快照落地标记完整性

## 2. 关键脚本

- 主脚本：`scripts/validate_m12_doc_consistency_ws27_005.py`
- 默认输出：`scratch/reports/ws27_m12_doc_consistency_ws27_005.json`

## 3. 推荐执行顺序

1. 执行严格校验

```powershell
.\.venv\Scripts\python.exe scripts/validate_m12_doc_consistency_ws27_005.py `
  --strict `
  --output scratch/reports/ws27_m12_doc_consistency_ws27_005.json
```

2. 失败时先看报告中的两个区域

- `checks`：定位失败检查项
- `missing_items`：定位缺失文件或缺失标记

## 4. 预期产物

1. `scratch/reports/ws27_m12_doc_consistency_ws27_005.json`

## 5. 判定标准

- 报告 `passed=true`
- `checks` 全部为 `true`
- `board_consistency_summary.error_count=0`

## 6. 风险与说明

- 该步骤校验“文档与证据一致性”，不替代 `WS27-004` 运行时门禁链结果。
- 放行签署前需与 `WS27-006` 生成的最终放行报告合并判定。
