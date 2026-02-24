# NGA-WS13-001 实施记录（Contract Gate 契约模型）

## 任务信息
- 任务ID: `NGA-WS13-001`
- 标题: 设计 Contract Gate 契约模型
- 状态: 已完成（进入 review）

## 变更范围
- `system/subagent_contract.py`
- `tests/test_subagent_contract.py`（新增）
- 复核联动: `tests/test_workspace_txn_e2e_regression.py`

## 契约模型设计
1. 契约标识
- `contract_id`: 并行修改同一工作流的共享标识。

2. 契约校验
- `contract_checksum`: 基于 `contract_id + schema` 的稳定哈希。
- `build_contract_checksum()` 使用 `json.dumps(sort_keys=True)`，确保字典键顺序变化不影响摘要。

3. 脚手架指纹
- `build_scaffold_fingerprint(contract_id, paths)`：对路径做去重、排序、分隔符归一化后生成指纹。
- 用于跨文件补丁绑定契约上下文，避免“并行盲写”。

4. 并行门禁验证
- `validate_parallel_contract(...)` 规则：
  - 并行修改（`changed_paths > 1`）必须提供非空 `contract_id`。
  - 若提供 `contract_checksum` 且与期望值不一致，立即 fail-fast。
  - 校验通过返回 `normalized_contract_id / expected_checksum / scaffold_fingerprint`。

## 验证结果
1. 新增单测覆盖（`tests/test_subagent_contract.py`）
- checksum 对 schema 键顺序稳定。
- scaffold fingerprint 对路径分隔符与重复项稳定。
- 并行多路径缺失 contract_id 会拒绝。
- checksum 错配会拒绝并返回期望值。
- checksum 匹配时返回可用 fingerprint。

2. 联动回归
- `tests/test_workspace_txn_e2e_regression.py`
- `tests/test_agentic_loop_contract_and_mutex.py`

## 验收结论
- `contract_id + checksum + schema` 协议已具备可执行实现。
- 契约错配 fail-fast 行为已可测试验证。
- 为后续 `WS13-002/WS13-003` 并行协商与脚手架绑定提供稳定基础。

