# NGA-WS17-005 实施记录（混沌演练：ReDoS 与 logrotate）

## 任务信息
- 任务ID: `NGA-WS17-005`
- 目标: 为 `sleep_watch` 增加 ReDoS/logrotate 混沌测试覆盖，验证不会假死并可持续唤醒。

## 变更范围
- `tests/test_chaos_sleep_watch.py`（新建）
- `system/sleep_watch.py`（未改动）

## 实施内容
1. 新增 ReDoS-like 慢匹配超时返回测试  
   - 用 `monkeypatch` 在测试内注入慢 `regex.search()`，模拟灾难性匹配成本。  
   - 验证 `wait_for_log_pattern` 在总超时窗口内返回 `reason == "timeout"`，避免 watch 假死。

2. 新增多轮 rotate/truncate 唤醒测试  
   - 在同一 watch 会话中依次执行 `rotate -> truncate -> rotate`。  
   - 最终写入目标行后应成功唤醒（`matched is True`），并观测到至少多次 reopen。

3. 新增匹配预算生效测试  
   - 对同一“慢 regex”分别用大预算与小预算运行。  
   - 断言小预算端到端耗时明显短于大预算，证明 `regex_match_timeout_seconds` 可限制单次匹配阻塞扩散。

## 设计取舍
- 仅使用本地文件与 `asyncio` 场景，未依赖任何系统命令或外部服务。
- 为降低平台差异和随机性，ReDoS 成本采用测试内可控注入，而非依赖某个具体正则在不同 Python/CPU 上的自然退化曲线。
- 按任务约束未修改 `system/sleep_watch.py`，通过测试侧覆盖验证现有实现行为。

## 验证
- 执行命令（可用环境）:  
  - `.\.venv\Scripts\python.exe -m pytest -q tests/test_chaos_sleep_watch.py`
- 结果: `3 passed`
- 运行告警: `PytestCacheWarning`（`.pytest_cache` 写权限受限），不影响用例通过。
