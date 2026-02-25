# M12 一页式执行清单（WS27-006：Phase3 Full 放行签署）

适用任务：`NGA-WS27-006`  
默认分支：`modifier/naga`

## 1. 目标

- 汇总 `WS27-004/005` 与 `WS27-001/002/003` 的执行证据，生成：
  - 可审计 JSON 放行报告
  - 可直接签署 Markdown 模板

## 2. 关键脚本

- 主脚本：`scripts/generate_phase3_full_release_report_ws27_006.py`
- 默认 JSON 输出：`scratch/reports/phase3_full_release_report_ws27_006.json`
- 默认签署模板：`scratch/reports/phase3_full_release_signoff_ws27_006.md`

## 3. 推荐执行顺序

1. 先确保前置报告已生成

- `scratch/reports/release_closure_chain_full_m0_m12_result.json`
- `scratch/reports/ws27_m12_doc_consistency_ws27_005.json`
- `scratch/reports/ws27_72h_endurance_ws27_001.json`
- `scratch/reports/ws27_subagent_cutover_status_ws27_002.json`
- `scratch/reports/ws27_oob_repair_drill_ws27_003.json`

2. 生成放行报告与签署模板（严格模式）

```powershell
.\.venv\Scripts\python.exe scripts/generate_phase3_full_release_report_ws27_006.py `
  --strict `
  --release-candidate phase3-full-m12 `
  --output-json scratch/reports/phase3_full_release_report_ws27_006.json `
  --output-markdown scratch/reports/phase3_full_release_signoff_ws27_006.md
```

## 4. 预期产物

1. `scratch/reports/phase3_full_release_report_ws27_006.json`
2. `scratch/reports/phase3_full_release_signoff_ws27_006.md`

## 5. 判定标准

- JSON 报告 `passed=true`
- `checks` 全部为 `true`
- `missing_required_reports=[]`
- 签署模板中“放行结论”显示 `PASS`

## 6. 风险与说明

- 若 `WS27-001` 仍是 quick-mode 等效结果，最终签署前需补真实 72h 墙钟验收证据。
- 该步骤只负责证据聚合与模板生成，不自动执行回滚或修复动作。
