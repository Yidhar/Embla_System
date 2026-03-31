> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS24-005 实施记录（插件隔离混沌演练集）

## 1. 背景

`WS24-002/003/004` 已完成能力落地，但发布前仍需要“攻防样例 -> 自动验证 -> 报告落盘”的演练闭环。
本任务目标是把关键攻击面转化为可回归的混沌测试集。

## 2. 实施内容

1. 新增混沌演练脚本
   - `scripts/run_plugin_isolation_chaos_suite_ws24_005.py`
   - 输出统一报告：`task_id/scenario/passed/failed_cases/case_results/audit`

2. 演练覆盖样例
   - `unsigned manifest`：无签名插件注册失败
   - `forbidden scope`：超权限 scope 注册失败
   - `payload budget`：超大输入被预算拒绝
   - `timeout + circuit-open`：长耗时插件触发超时并进入熔断

3. 审计证据
   - 注册拒绝证据来自 `REJECTED_PLUGIN_MANIFESTS`
   - 运行时拦截证据来自 worker 返回结果与 runtime metrics

## 3. 变更文件

- `scripts/run_plugin_isolation_chaos_suite_ws24_005.py`
- `tests/test_run_plugin_isolation_chaos_suite_ws24_005.py`

## 4. 验证记录

```bash
.\.venv\Scripts\python.exe -m pytest -q tests/test_run_plugin_isolation_chaos_suite_ws24_005.py
```

## 5. 结果

- 插件宿主劫持关键样例已形成可执行混沌演练集。
- 每轮演练可产出可审计报告，作为 M9 发布门禁输入。
