# M9 发布收口一页纸（WS24-006）

## 1. 目标

在 M9 阶段把插件隔离安全能力纳入发布门禁，确保：

1. `register_new_tool` 仅允许签名 + allowlist + scope 合规插件注册。
2. 插件执行具备资源预算与熔断保护。
3. 插件 worker 生命周期异常（超时/僵尸）可回收。
4. 攻击样例在混沌演练中被拦截且审计可追溯。

## 2. 预检

```bash
python -m pytest -q tests/test_mcp_plugin_isolation_ws24_001.py tests/test_run_plugin_isolation_chaos_suite_ws24_005.py tests/test_ws24_release_gate.py
```

## 3. 运行 M9 收口链

```bash
python scripts/release_closure_chain_m9_ws24_006.py
```

默认产物：

- `scratch/reports/plugin_isolation_chaos_ws24_005.json`
- `scratch/reports/ws24_m9_closure_gate_result.json`
- `scratch/reports/release_closure_chain_m9_ws24_006_result.json`

## 4. 单独执行门禁

```bash
python scripts/validate_m9_closure_gate_ws24_006.py \
  --plugin-chaos-report scratch/reports/plugin_isolation_chaos_ws24_005.json \
  --output-json scratch/reports/ws24_m9_closure_gate_result.json
```

## 5. 接入全量收口链

```bash
python scripts/release_closure_chain_full_m0_m7.py --skip-m0-m5 --skip-m6-m7 --skip-m8
```

说明：

1. 脚本名保持历史兼容，但当前链路已扩展到 `M0-M9`。
2. 若仅验证 M9，可跳过前序里程碑组（如上命令）。

## 6. 失败排障

1. `ws24_005:*` 失败：检查 `scratch/reports/plugin_isolation_chaos_ws24_005.json` 的 `case_results` 与 `audit`。
2. `doc:*` 失败：补齐 `doc/task/23-phase3-full-target-task-list.md` 的 WS24 快照状态行。
3. `runbook:*` 失败：确认本 runbook 包含 `release_closure_chain_m9_ws24_006.py` 与 `validate_m9_closure_gate_ws24_006.py` 命令示例。
