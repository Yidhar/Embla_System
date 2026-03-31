"""Chaos drill tests for lock leak + failover (NGA-WS17-004)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import core.security.lease_fencing as global_mutex_module
from core.security import GlobalMutexManager


class ManualClock:
    def __init__(self, start: float = 1000.0) -> None:
        self._now = float(start)

    def time(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += max(0.0, float(seconds))


class DummyLineageRegistry:
    def __init__(self) -> None:
        self.reap_by_fencing_epoch_calls = []
        self.reap_for_lock_scavenge_calls = []

    def reap_by_fencing_epoch(self, max_epoch: int) -> int:
        self.reap_by_fencing_epoch_calls.append(int(max_epoch))
        return 1

    def reap_for_lock_scavenge(self, *, fencing_epoch, reason):
        self.reap_for_lock_scavenge_calls.append({"fencing_epoch": fencing_epoch, "reason": reason})
        return {"cleanup_mode": "fencing_epoch", "fencing_epoch": fencing_epoch, "reaped_count": 1, "reason": reason}


def _fresh_manager(state_name: str, audit_name: str) -> GlobalMutexManager:
    base = Path("scratch/test_chaos_lock_failover")
    base.mkdir(parents=True, exist_ok=True)
    state_file = base / state_name
    audit_file = base / audit_name
    if state_file.exists():
        state_file.unlink()
    if audit_file.exists():
        audit_file.unlink()
    return GlobalMutexManager(state_file=state_file, audit_file=audit_file)


def test_chaos_lock_failover_kill9_semantics_ttl_reclaim_and_takeover(monkeypatch):
    manager = _fresh_manager("lease_chaos_1.json", "lease_chaos_1.audit.jsonl")
    registry = DummyLineageRegistry()
    clock = ManualClock(start=2000.0)

    monkeypatch.setattr(global_mutex_module, "get_process_lineage_registry", lambda: registry)
    monkeypatch.setattr(global_mutex_module.time, "time", clock.time)

    first = asyncio.run(
        manager.acquire(
            owner_id="owner-a",
            job_id="job-a",
            ttl_seconds=3.0,
            wait_timeout_seconds=0.5,
        )
    )
    # kill -9 semantics: owner process disappears abruptly, so no release/renew happens.
    clock.advance(3.2)
    second = asyncio.run(
        manager.acquire(
            owner_id="owner-b",
            job_id="job-b",
            ttl_seconds=3.0,
            wait_timeout_seconds=0.5,
        )
    )

    assert second.owner_id == "owner-b"
    assert second.fencing_epoch == first.fencing_epoch + 1
    assert registry.reap_by_fencing_epoch_calls == [first.fencing_epoch]

    with pytest.raises(TimeoutError, match="lease lost"):
        asyncio.run(manager.renew(first))

    current = asyncio.run(manager.inspect())
    assert current is not None
    assert current.lease_id == second.lease_id


def test_chaos_lock_failover_repeatable_multi_round_takeover(monkeypatch):
    manager = _fresh_manager("lease_chaos_2.json", "lease_chaos_2.audit.jsonl")
    registry = DummyLineageRegistry()
    clock = ManualClock(start=3000.0)

    monkeypatch.setattr(global_mutex_module, "get_process_lineage_registry", lambda: registry)
    monkeypatch.setattr(global_mutex_module.time, "time", clock.time)

    ttl_seconds = 2.0
    handles = []
    for idx, owner in enumerate(("owner-a", "owner-b", "owner-c", "owner-d"), start=1):
        handle = asyncio.run(
            manager.acquire(
                owner_id=owner,
                job_id=f"job-{idx}",
                ttl_seconds=ttl_seconds,
                wait_timeout_seconds=0.5,
            )
        )
        handles.append(handle)
        clock.advance(ttl_seconds + 0.05)

    epochs = [h.fencing_epoch for h in handles]
    assert epochs == [1, 2, 3, 4]
    assert registry.reap_by_fencing_epoch_calls == [1, 2, 3]
