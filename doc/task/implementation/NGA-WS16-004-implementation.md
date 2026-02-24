# NGA-WS16-004 实施记录（配置迁移脚本与版本化）

## 任务信息
- 任务ID: `NGA-WS16-004`
- 标题: 配置迁移脚本与版本化
- 状态: 已完成（进入 review）

## 本次范围（仅 WS16-004）
- 新增 `scripts/config_migration_ws16_004.py`：
  - 旧配置 payload 迁移（保留未知键）
  - `system.config_schema_version` 版本标记注入
  - `handoff.max_loop_stream/non_stream` 到 `agentic_loop.max_rounds_*` 缺失映射
  - 可选 `server_ports` 投影（`--project-server-ports`）
  - 迁移写入前自动备份
  - `--restore` / `--restore-latest` 回滚恢复
- 运行时模型默认值补齐：`system/config.py` 增加 `SystemConfig.config_schema_version=1`
- 配置样例更新：`config.json.example` 增加 `system.config_schema_version`
- 新增 focused tests：`tests/test_config_migration_ws16_004.py`

## 实施要点
1. 迁移逻辑为“非破坏式补齐”
- 使用深拷贝迁移 payload，仅补齐缺失字段，不删除未知字段，不重写无关结构。

2. 版本标记策略
- 迁移阶段确保 `system.config_schema_version >= 1`。
- 运行时默认 `SystemConfig.config_schema_version=1`，保证历史配置缺失字段时可向后兼容加载。

3. handoff 到 agentic_loop 映射
- 仅当 `agentic_loop.max_rounds_stream/non_stream` 缺失时，分别从
  `handoff.max_loop_stream/non_stream` 投影。

4. backup/restore
- `upgrade_config_file()` 在写回前自动 `create_backup()`。
- `restore_config_file()` 支持显式备份路径或按规则恢复最新备份。

## 验证（见本次执行输出）
- `pytest`：`tests/test_config_migration_ws16_004.py`
- `ruff check`：变更的 Python 文件

## 建议 execution-board 证据字符串（evidence_link + notes）
- `evidence_link` 建议值:
  - `scripts/config_migration_ws16_004.py; system/config.py; config.json.example; tests/test_config_migration_ws16_004.py; doc/task/implementation/NGA-WS16-004-implementation.md`
- `notes` 建议值:
  - `config migration cli landed with schema marker system.config_schema_version, non-destructive handoff->agentic_loop mapping, optional server_ports projection, and backup/restore rollback coverage via focused tests`
