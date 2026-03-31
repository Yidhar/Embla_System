"""Minimal chaos drill: lock holder crash semantics -> TTL reclaim -> owner failover."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List

import core.security.lease_fencing as global_mutex_module
from core.security import GlobalMutexManager


class ManualClock:
    def __init__(self, start: float = 1000.0) -> None:
        self._now = float(start)

    def time(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += max(0.0, float(seconds))


class RecordingLineageRegistry:
    def __init__(self) -> None:
        self.reap_by_fencing_epoch_calls: List[int] = []

    def reap_by_fencing_epoch(self, max_epoch: int) -> int:
        self.reap_by_fencing_epoch_calls.append(int(max_epoch))
        return 1

    def reap_for_lock_scavenge(self, *, fencing_epoch, reason):
        return {"cleanup_mode": "fencing_epoch", "fencing_epoch": fencing_epoch, "reaped_count": 1, "reason": reason}


def run_drill(*, ttl_seconds: float, advance_seconds: float, scratch_dir: Path) -> Dict[str, Any]:
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be > 0")
    if advance_seconds <= ttl_seconds:
        raise ValueError("advance_seconds must be greater than ttl_seconds to force expiration")

    scratch_dir.mkdir(parents=True, exist_ok=True)
    state_file = scratch_dir / "chaos_lock_failover_lease.json"
    audit_file = scratch_dir / "chaos_lock_failover.audit.jsonl"
    if state_file.exists():
        state_file.unlink()
    if audit_file.exists():
        audit_file.unlink()

    manager = GlobalMutexManager(state_file=state_file, audit_file=audit_file)
    clock = ManualClock(start=5000.0)
    registry = RecordingLineageRegistry()

    original_time = global_mutex_module.time.time
    original_registry_getter = global_mutex_module.get_process_lineage_registry
    global_mutex_module.time.time = clock.time
    global_mutex_module.get_process_lineage_registry = lambda: registry
    try:
        first = asyncio.run(
            manager.acquire(
                owner_id="owner-chaos-a",
                job_id="job-chaos-a",
                ttl_seconds=ttl_seconds,
                wait_timeout_seconds=0.5,
            )
        )
        # kill -9 semantics equivalent: crashed owner stops heartbeat without release.
        clock.advance(advance_seconds)
        second = asyncio.run(
            manager.acquire(
                owner_id="owner-chaos-b",
                job_id="job-chaos-b",
                ttl_seconds=ttl_seconds,
                wait_timeout_seconds=0.5,
            )
        )

        stale_renew_error = ""
        try:
            asyncio.run(manager.renew(first))
        except Exception as exc:  # pragma: no cover - runtime drill safety net
            stale_renew_error = type(exc).__name__

        passed = (
            second.fencing_epoch == first.fencing_epoch + 1
            and registry.reap_by_fencing_epoch_calls == [first.fencing_epoch]
            and stale_renew_error == "TimeoutError"
        )
        return {
            "passed": passed,
            "scenario": "kill9_semantic_ttl_failover",
            "ttl_seconds": ttl_seconds,
            "advance_seconds": advance_seconds,
            "first_owner": first.owner_id,
            "first_epoch": first.fencing_epoch,
            "second_owner": second.owner_id,
            "second_epoch": second.fencing_epoch,
            "lineage_reap_by_fencing_epoch_calls": registry.reap_by_fencing_epoch_calls,
            "stale_owner_renew_error": stale_renew_error,
        }
    finally:
        global_mutex_module.time.time = original_time
        global_mutex_module.get_process_lineage_registry = original_registry_getter


def main() -> int:
    parser = argparse.ArgumentParser(description="Run NGA-WS17-004 lock failover chaos drill")
    parser.add_argument("--ttl-seconds", type=float, default=2.0)
    parser.add_argument("--advance-seconds", type=float, default=2.2)
    parser.add_argument("--scratch-dir", type=Path, default=Path("scratch/test_chaos_lock_failover"))
    args = parser.parse_args()

    report = run_drill(
        ttl_seconds=float(args.ttl_seconds),
        advance_seconds=float(args.advance_seconds),
        scratch_dir=args.scratch_dir,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
