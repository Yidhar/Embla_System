> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS23-003 实施记录（M8：Immutable DNA 发布门禁）

## 任务信息
- 任务ID: `NGA-WS23-003`
- 标题: Immutable DNA 校验接入发布门禁链
- 状态: 已完成（含运维效率补充）

## 基线能力（已落地）

1. DNA 门禁脚本
- 文件: `scripts/validate_immutable_dna_gate_ws23_003.py`
- 能力:
  - 校验 `system/prompts` 下 4 个核心 prompt 与 manifest 哈希一致性
  - 输出标准报告：`scratch/reports/immutable_dna_gate_ws23_003_result.json`
  - 失败时返回 `dna_hash_mismatch` / `manifest_missing` 等可审计原因

2. 发布链接入
- 文件: `scripts/release_closure_chain_m0_m5.py`
- 能力:
  - 在收口链 `T0A` 阶段执行 DNA gate，确保发布前 prompt DNA 一致

3. 回归
- 文件:
  - `tests/test_ws23_003_immutable_dna_gate.py`
  - `tests/test_release_closure_chain_m0_m5.py`

## 补充更新（2026-02-26）

为解决“手动改 prompt 后经常忘记同步 manifest”问题，新增一键同步工具：

1. 新增脚本
- 文件: `scripts/update_immutable_dna_manifest_ws23_003.py`
- 能力:
  - 基于审批票据重算 `system/prompts/immutable_dna_manifest.spec`
  - 默认串行执行 DNA gate 复验（可 `--skip-verify`）
  - 输出更新报告：`scratch/reports/immutable_dna_manifest_update_ws23_003.json`
  - `--strict` 下失败返回非零，便于接入 CI/发布链

2. 新增回归
- 文件: `tests/test_update_immutable_dna_manifest_ws23_003.py`
- 覆盖:
  - 票据有效时更新成功并 gate 通过
  - 票据缺失时失败并拒绝更新
  - `--skip-verify` 分支行为

3. 推荐命令
```bash
.venv/bin/python scripts/update_immutable_dna_manifest_ws23_003.py \
  --approval-ticket CHG-2026-XXXX \
  --strict
```

## 结果摘要

- `NGA-WS23-003` 现已覆盖“门禁校验 + manifest 更新 + 更新后复验”的闭环。
- prompt 改动后可通过单命令完成 DNA 同步，降低人工遗漏与发布阻断风险。
