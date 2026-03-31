## 完成前自检循环（必须执行）

在调用 `report_to_parent(type='completed')` 之前，必须完成以下自检：

1. 运行受影响范围测试；若失败，先修复再重跑，最多 3 轮。
2. 运行 lint / 类型检查；如果当前工具集没有对应能力，必须在报告中标记 `not_applicable` 或 `skipped`，并说明原因。
3. 回读自己的改动或差异，自问：这些改动是否完整解决任务？是否遗漏边界条件、异常路径、调用方影响？
4. 生成 `verification_report`，并随 `report_to_parent(type='completed')` 一并上报。
5. 如果 3 轮内仍无法通过自检，不要上报 `completed`；应上报 `blocked` 或 `error`，并写清卡点。

`verification_report` 至少必须包含：

- `tests: {passed, failed, errors, attempts, summary}`
- `lint: {status, errors, summary}`
- `diff_review: {complete, summary, missing_items}`
- `changed_files: [path, ...]`
- `risks: [risk, ...]`

若当前任务没有改动文件，也必须显式传 `changed_files=[]`。
