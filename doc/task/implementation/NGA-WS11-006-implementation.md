# NGA-WS11-006 Implementation Notes

## Task Info
- Task ID: `NGA-WS11-006`
- Title: Artifact 证据链可观测性（指标与审计）
- Scope: `system/artifact_store.py`, `tests/test_artifact_store_policy.py`
- Status transition: `in_progress -> review`

## What Was Implemented

### 1) Added lightweight ArtifactStore metrics snapshot API
- File: `system/artifact_store.py`
- Added in-memory counters:
  - `store_attempt`
  - `store_success`
  - `quota_reject`
  - `cleanup_deleted`
  - `retrieve_hit`
  - `retrieve_miss`
- Added helper:
  - `_inc_metric(key, delta=1)` for counter increments.
- Added query API:
  - `get_metrics_snapshot()` returns:
    - `artifact_count`
    - `total_size_mb`
    - all counters above.

Notes:
- Metrics are runtime-only and reset on process restart.
- Existing metadata persistence (`artifacts_metadata.json`) remains unchanged.

### 2) Wired metric updates into store/retrieve/cleanup paths
- File: `system/artifact_store.py`

`store(...)`:
- Increment `store_attempt` at method entry.
- Increment `quota_reject` when final quota decision rejects write.
- Increment `store_success` after file+metadata are successfully persisted.

`retrieve(...)`:
- Increment `retrieve_hit` on successful fetch.
- Increment `retrieve_miss` on failure paths:
  - metadata not found
  - artifact expired
  - file missing
  - read exception

`cleanup_expired()` and `cleanup_to_watermark()`:
- Increment `cleanup_deleted` by number of deleted artifacts in each cleanup pass.

### 3) Added regression tests for metric counter changes
- File: `tests/test_artifact_store_policy.py`
- Extended existing WS11-004 tests with metrics assertions:
  - `test_priority_normalization_and_ttl_selection`
  - `test_low_priority_write_rejected_at_high_watermark`
  - `test_store_cleans_expired_before_rejecting_by_total_size`
- Added new test:
  - `test_metrics_snapshot_tracks_retrieve_hit_miss_and_cleanup`

Coverage highlights:
- Snapshot initial values.
- Store attempt/success increments.
- Quota reject increments on low-priority high-watermark rejection.
- Retrieve hit/miss split.
- Cleanup deleted count increments.
- Gauge fields (`artifact_count`, `total_size_mb`) reflect runtime state.

## Compatibility / Non-goals
- No changes to `apiserver/native_tools.py` or `tool_contract.py`.
- WS11-004 behavior (priority normalization, TTL, high-watermark policy, cleanup-before-reject) preserved.

## Verification Command
- `python -m pytest -q tests/test_artifact_store_policy.py`

## Date
2026-02-24
