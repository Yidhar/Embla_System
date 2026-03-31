> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS11-005 Implementation Notes

## Task Info
- Task ID: `NGA-WS11-005`
- Title: 高水位背压与关键路径保护
- Scope: `system/artifact_store.py`, `tests/test_artifact_store_policy.py`
- Depends on: `NGA-WS11-004`
- Acceptance focus: 高水位/临界区下为 EventBus/SQLite 预留空间，且支持回退到只告警模式
- Date: `2026-02-24`

## What Was Implemented

### 1) Critical-path reserve protection for EventBus/SQLite
- File: `system/artifact_store.py`
- Added `ArtifactStoreConfig.critical_reserve_ratio` (default `0.05`).
- Added reserve check in `check_quota(...)`:
  - Compute projected usage ratio.
  - For `low|normal` priority writes, if projected usage reaches critical threshold
    (`1.0 - critical_reserve_ratio`), trigger backpressure decision.
- This creates explicit headroom for non-artifact critical paths (EventBus/SQLite).

### 2) Rollback switch (enforce vs warn-only)
- File: `system/artifact_store.py`
- Added `ArtifactStoreConfig.backpressure_mode` (default `enforce`).
- Supported modes:
  - `enforce` (default): keep rejection behavior.
  - `warn_only` plus aliases `warn|alert|loose|relaxed`: allow write but keep warning semantics.
- Backpressure resolution is centralized through `_resolve_backpressure(...)`.
- Hard limits remain hard-fail regardless of mode:
  - single artifact size limit
  - total size limit
  - artifact count limit

### 3) Warning observability for degraded mode
- File: `system/artifact_store.py`
- Added metric counter: `backpressure_warn`.
- `store(...)` now preserves warning reason on successful warn-only bypass and returns:
  - `Artifact stored with warning: ...`
- Metrics snapshot now includes `backpressure_warn`.

### 4) Regression tests for WS11-005
- File: `tests/test_artifact_store_policy.py`
- Added/updated coverage:
  - `test_critical_reserve_backpressures_low_and_normal`
    - verifies critical reserve backpressure rejects `low` and `normal`.
  - `test_warn_only_mode_allows_write_and_keeps_warning_semantics`
    - verifies rollback switch allows write and keeps warning semantics/messages.
  - `test_priority_normalization_and_ttl_selection`
    - now also asserts `backpressure_warn` initial value.

## Verification
- Command:
  - `uv --cache-dir .uv_cache run python -m pytest -q tests/test_artifact_store_policy.py`
- Result:
  - `6 passed`
  - Environment warning remains: `PytestCacheWarning` for `.pytest_cache` ACL (non-blocking).

## Non-goals / Compatibility
- No changes to:
  - `apiserver/native_tools.py`
  - `tool_contract.py`
- Existing WS11-004 cleanup-before-reject and TTL normalization behavior remains intact.
