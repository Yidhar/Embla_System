> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

﻿# NGA-WS11-004 Implementation Notes

## Task Info
- Task ID: `NGA-WS11-004`
- Title: Artifact quota and lifecycle policy
- Wave: `W3`
- Status transition: `in_progress -> review`
- Risk linkage: `R16` (Artifact Store disk DoS)

## What was implemented

### 1) Quota check now supports priority-aware backpressure
- File: `system/artifact_store.py`
- Updated `check_quota(new_size_bytes, *, priority="normal")`.
- Added priority normalization before policy evaluation.
- High-watermark logic changed to selective rejection:
  - Reject low-priority writes when projected usage reaches high watermark.
  - Keep normal/high/critical write path available unless hard quota is exceeded.

### 2) Store path now performs pre-write lifecycle cleanup
- File: `system/artifact_store.py`
- Updated `store(...)` workflow:
  1. Normalize priority.
  2. Run `cleanup_expired()` before quota check.
  3. If usage is already at high watermark, run `cleanup_to_watermark()` first.
  4. Perform quota check with priority.
  5. On quota/high-watermark failure, retry once after watermark cleanup.
- Fixed incomplete variable wiring:
  - `normalized_priority` is now explicitly defined before metadata/TTL usage.

### 3) TTL and metadata priority are deterministic
- File: `system/artifact_store.py`
- TTL decision is now consistently tied to normalized priority.
- Metadata `priority` always stores normalized value (`low|normal|high|critical`).

## Regression tests added
- File: `tests/test_artifact_store_policy.py`
- Added:
  - `test_priority_normalization_and_ttl_selection`
  - `test_low_priority_write_rejected_at_high_watermark`
  - `test_store_cleans_expired_before_rejecting_by_total_size`

## Verification evidence
- `uv --cache-dir .uv_cache run python -m pytest -q tests/test_artifact_store_policy.py`
  - Result: pass (`3 passed`)
- `uv --cache-dir .uv_cache run python -m pytest -q tests/test_native_executor_guards.py tests/test_policy_firewall.py tests/test_global_mutex.py tests/test_process_lineage.py tests/test_native_tools_runtime_hardening.py tests/test_agentic_loop_contract_and_mutex.py`
  - Result: pass (`45 passed`)

## Known environment noise
- `tests/test_tool_contract.py` and `tests/test_native_tools_artifact_and_guard.py` currently hit a host temp-directory ACL issue around `pytest` tmp path creation (`pytest-of-芸` access denied).
- This is environment-level and independent of `artifact_store` logic changes.

## Date
2026-02-24
