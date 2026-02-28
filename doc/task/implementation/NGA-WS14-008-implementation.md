> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS14-008 实施说明（logrotate 容错）

## 变更范围
- `system/sleep_watch.py`
- `tests/test_sleep_watch_rotation.py`

## 实施内容
1. 强化 `wait_for_log_pattern` 的 `tail -F` 容错语义：
   - `inode` 变化时触发重开（`inode_changed`）。
   - 文件被截断时触发重开（`truncated`）。
   - 文件短暂缺失后再创建时触发重开（`recreated`）。
2. 增加最小可观测信息（返回结构）：
   - `reopen_count`：重开次数累计。
   - `reopen_reason`：最后一次重开原因。
3. 新增独立测试文件覆盖三个场景：
   - log rotate 后可继续匹配；
   - truncate 后可继续匹配；
   - 文件短暂缺失后再创建可恢复并匹配。

## 设计说明
- 保持原有对外行为不变（`watch_id`/`matched`/`reason`/`matched_line`/`elapsed_seconds` 仍然保留）。
- 新字段以向后兼容方式追加在 `SleepWatchResult`，不会影响现有调用方读取旧字段。
- 对“缺失后重建”的检测使用显式状态位 `missing_since_initialized`，避免依赖平台特定 inode 行为。

## 验证
- 目标测试：`tests/test_sleep_watch_rotation.py`
- 命令：`pytest -q tests/test_sleep_watch_rotation.py`
