# NGA-WS18-006 实施记录（Immutable DNA 注入与校验）

## 任务信息
- Task ID: `NGA-WS18-006`
- Title: Immutable DNA 注入与校验
- 状态: 已完成（进入 review）

## 本次范围（仅 WS18-006）
1. Immutable DNA 核心模块
- 新增 `system/immutable_dna.py`
  - DNA 清单模型：`DNAManifest`
  - 校验结果模型：`DNAVerificationResult`
  - 加载器：`ImmutableDNALoader`
    - `bootstrap_manifest()`：生成并封存 hash 清单
    - `verify()`：按清单校验文件 hash 一致性
    - `inject()`：校验通过后按固定顺序注入 DNA 文本
    - `approved_update_manifest(approval_ticket=...)`：需要审批票据才允许更新清单
  - 审计落盘：`immutable_dna_audit.jsonl`

2. 固定注入顺序
- 默认顺序固定为：
  1. `conversation_style_prompt.txt`
  2. `conversation_analyzer_prompt.txt`
  3. `tool_dispatch_prompt.txt`
  4. `agentic_tool_prompt.txt`
- 支持自定义顺序（显式配置），并在 manifest 中固化。

3. 非授权变更拒绝
- 文件内容被篡改后 `verify().ok=False`，`inject()` 抛 `PermissionError`。
- 审计事件记录：
  - `dna_verify_failed`
  - `dna_manifest_update_rejected`

4. 测试覆盖
- 新增 `tests/test_immutable_dna_ws18_006.py`
  - bootstrap + verify + inject 正常链路
  - 篡改后拒绝注入
  - 清单更新需审批票据
  - 自定义注入顺序生效

## 验证命令
- `python -m ruff check system/immutable_dna.py tests/test_immutable_dna_ws18_006.py`
  - 结果: `All checks passed`
- `python -m pytest -q tests/test_immutable_dna_ws18_006.py tests/test_loop_cost_guard_ws18_005.py tests/test_watchdog_daemon_ws18_004.py`
  - 结果: `passed`

## 交付结果与验收对应
- 交付“DNA hash 校验、注入顺序固定化”：已实现并单测覆盖。
- 验收“非授权变更被拒绝并审计”：篡改用例触发拒绝与审计事件。
- 回退策略“回退到最后已签名版本”：通过 manifest 机制可重新加载上次封存版本。

## Suggested Execution-Board Evidence
- `evidence_link`:
  - `system/immutable_dna.py; tests/test_immutable_dna_ws18_006.py; doc/task/implementation/NGA-WS18-006-implementation.md`
- `notes`:
  - `immutable dna loader now seals prompt hashes in manifest, enforces fixed injection order, rejects tampered content, and records approval/audit events for manifest updates`

## Date
2026-02-24
