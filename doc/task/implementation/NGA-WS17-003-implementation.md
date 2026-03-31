> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS17-003 实施记录（Clean Checkout 双轨验证）

## 任务信息
- Task ID: `NGA-WS17-003`
- Title: Clean Checkout dual-track validation
- 范围: workspace run + clean checkout run 一致性门禁
- 约束: 不使用破坏性 git 操作

## What Was Implemented

### 1) Dual-track validator script
- File: `scripts/clean_checkout_dual_track.py`
- Key behavior:
  1. Runs one command in workspace checkout and a clean `git worktree` checkout.
  2. Computes normalized output digest (SHA-256) for each run.
  3. Compares `(exit_code, normalized_output_digest)` across both tracks.
  4. Emits structured JSON report including command, exit codes, digest, and reason.
  5. Supports `--dry-run` and `--cleanup/--no-cleanup`.

### 2) Safe git operation boundary
- Uses:
  - `git rev-parse --show-toplevel`
  - `git rev-parse --verify HEAD`
  - `git worktree add --detach <path> <ref>`
  - `git worktree remove <path>`
- Does not use reset/checkout/rebase/force-remove style destructive commands.

### 3) Focused unit tests
- File: `tests/test_clean_checkout_dual_track.py`
- Coverage:
  1. Output normalization helper.
  2. Digest helper determinism and sensitivity.
  3. Comparison decision reasons (match/mismatch branches).
  4. Worktree add/remove command builders.
  5. Worktree creation wiring verified via mocked git runner.

## JSON Report Fields (Core)
- `command`
- `workspace.exit_code`
- `clean_checkout.exit_code`
- `workspace.normalized_output_digest`
- `clean_checkout.normalized_output_digest`
- `comparison.match`
- `comparison.reason`
- `dry_run`
- `cleanup.*`

## Suggested Execution-Board Evidence String
- `evidence_link`:
  - `scripts/clean_checkout_dual_track.py; tests/test_clean_checkout_dual_track.py; doc/task/implementation/NGA-WS17-003-implementation.md`
- `notes`:
  - `dual-track workspace vs clean-worktree validator shipped with normalized-output digest comparison, dry-run/safe-cleanup controls, and mocked worktree command unit coverage`

## Verification Commands
- `uv --cache-dir .uv_cache run python -m pytest -q tests/test_clean_checkout_dual_track.py`
  - Result: `10 passed`
  - Warning: `PytestCacheWarning` for `.pytest_cache` write permission (`WinError 5`), non-blocking.
- `uv --cache-dir .uv_cache run python -m ruff check scripts/clean_checkout_dual_track.py tests/test_clean_checkout_dual_track.py`
  - Result: `All checks passed!`

## Date
2026-02-24
