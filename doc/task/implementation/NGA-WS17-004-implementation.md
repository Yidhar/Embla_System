# NGA-WS17-004 实施记录

## 任务信息
- 任务ID: NGA-WS17-004
- 标题: 混沌演练：锁泄漏与切主
- 状态: ✅ 已完成（最小可交付）

## 约束遵循
- 未修改 `system/global_mutex.py`
- 未修改 `system/process_lineage.py`

## 交付物

### 1) 可重复混沌测试
- 文件: `tests/test_chaos_lock_failover.py`
- 新增测试:
  1. `test_chaos_lock_failover_kill9_semantics_ttl_reclaim_and_takeover`
  2. `test_chaos_lock_failover_repeatable_multi_round_takeover`
- 覆盖点:
  - `kill -9` 语义等价（owner 无 release/renew，直接“消失”）
  - TTL 到期后新 owner 接管
  - fencing epoch 单调递增
  - fencing 切换触发 lineage 清理（mock `reap_by_fencing_epoch` 调用校验）
  - 旧 owner 续租失败（`TimeoutError`），避免旧执行链路继续存活

### 2) 最小演练入口
- 文件: `scripts/chaos_lock_failover.py`
- 用法:
  - `.venv\Scripts\python.exe scripts/chaos_lock_failover.py`
  - 可选参数:
    - `--ttl-seconds`
    - `--advance-seconds`
    - `--scratch-dir`
- 行为:
  - 以可控时钟模拟 owner 崩溃后的时间推进（不真实 kill 进程，语义等价）
  - 输出 JSON 报告（epoch 切换、lineage 清理调用、旧 owner 续租错误）

## 验证结果

### 新增测试执行
- 命令:
  - `.venv\Scripts\python.exe -m pytest -q tests/test_chaos_lock_failover.py`
- 结果:
  - `2 passed`
  - 附带 1 条 `PytestCacheWarning`（`.pytest_cache` 写入权限），不影响用例通过

### 演练脚本执行
- 命令:
  - `.venv\Scripts\python.exe scripts/chaos_lock_failover.py`
- 输出摘要:
  - `passed: true`
  - `first_epoch: 1`
  - `second_epoch: 2`
  - `lineage_reap_by_fencing_epoch_calls: [1]`
  - `stale_owner_renew_error: TimeoutError`

## 说明
- 本次交付聚焦“锁持有者异常退出 -> TTL 回收 -> 切主接管”的最小闭环与可重复演练能力。
- 未触碰核心锁/lineage实现文件，全部通过新增测试和演练脚本完成验证。
