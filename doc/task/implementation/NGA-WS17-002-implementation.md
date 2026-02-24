# NGA-WS17-002 实施记录

## 任务信息
- 任务ID: NGA-WS17-002
- 标题: Anti-Test-Poisoning 检查器
- 优先级: P0
- 阶段: M1
- 状态: ✅ 已完成

## 代码改动

### 1) 写入前硬门禁接入
- 文件: `apiserver/native_tools.py`
- 变更:
  1. `write_file` 在写入前调用 `TestBaselineGuard.check_modification_allowed()`。
  2. 对测试文件内容执行毒化扫描:
     - `assert True` / `assert 1 == 1`
     - `@pytest.mark.skip` / `@unittest.skip`
     - `except: pass` / `except Exception: pass`
  3. 检测命中直接抛 `NativeSecurityError`，阻断写入。

### 2) 覆盖范围
- 普通非测试文件不受影响。
- 测试文件 append/overwrite 两种模式均执行检查。

## 验证
- 新增测试:
  - `tests/test_native_tools_artifact_and_guard.py::test_write_file_blocks_test_poisoning`
- 定向测试命令:
  - `uv run python -m pytest -q tests/test_tool_contract.py tests/test_native_tools_artifact_and_guard.py`
- 结果: ✅ 17 passed

## 回滚策略
- 若误报过高，可先将该规则降级为告警（当前实现为硬阻断）。

## 完成时间
2026-02-24
