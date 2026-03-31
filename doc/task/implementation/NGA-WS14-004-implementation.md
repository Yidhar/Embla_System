> `DOC_LAYER: L3_ARCHIVE_IMPLEMENTATION`  
> `作用：历史实施证据归档（Implementation Record）`  
> `约束：不作为当前主链设计、接口契约或运行基线`  
> `当前口径：doc/01-module-overview.md + doc/05-dev-startup-and-index.md + doc/task/25-subagent-development-fabric-status-matrix.md`

# NGA-WS14-004 Implementation Notes

## Task Info
- Task ID: `NGA-WS14-004`
- Title: Global mutex orphan-lock scavenger
- Status transition: `todo -> review`
- Risk linkage: `R3` (orphaned lock + fencing cleanup)

## What was implemented

### 1) Expired lease scan-and-reap entry
- File: `system/global_mutex.py`
- Added `scan_and_reap_expired(reason="periodic_scan") -> Dict[str, Any]`.
- Behavior:
  - no lease: skip with `skip_reason=no_lease`
  - active lease: skip with `skip_reason=lease_active`
  - expired lease: delete lease and report `reclaimed_count=1`
- `reap_expired()` now delegates to the new entry for backward compatibility.

### 2) Fencing/orphan cleanup linkage
- Files:
  - `system/global_mutex.py`
  - `system/process_lineage.py`
- Added `ProcessLineageRegistry.reap_for_lock_scavenge(...)`:
  - with `fencing_epoch`: cleanup by epoch (includes orphan scan)
  - without `fencing_epoch`: orphan-running-job cleanup only
- `scan_and_reap_expired` calls this linkage after successful reclaim.

### 3) Audit events and periodic wrapper
- Files:
  - `system/global_mutex.py`
  - `system/lock_scavenger.py` (new)
- Added JSONL audit append for scavenger events.
- Added `LockScavenger` wrapper:
  - `run_once()` for one-shot cleanup
  - `run_forever()` for periodic cleanup loop

## Tests
- Updated/added:
  - `tests/test_global_mutex.py::test_global_mutex_scavenger_reaps_expired_lease_and_cleans_lineage`
  - `tests/test_global_mutex.py::test_global_mutex_scavenger_keeps_active_lease`
  - `tests/test_process_lineage.py::test_reap_for_lock_scavenge_without_epoch`

## Verification
- `uv --cache-dir .uv_cache run python -m pytest -q tests/test_global_mutex.py tests/test_process_lineage.py`
  - Result: pass

## Date
2026-02-24
