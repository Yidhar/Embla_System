"""Global mutex lease tests (WS14-003)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import core.security.lease_fencing as global_mutex_module
from core.security import GlobalMutexManager


def test_global_mutex_reclaim_after_expire():
    base = Path("scratch/test_global_mutex")
    base.mkdir(parents=True, exist_ok=True)
    manager = GlobalMutexManager(state_file=base / "lease_reclaim.json")

    first = asyncio.run(
        manager.acquire(
            owner_id="owner-a",
            job_id="job-a",
            ttl_seconds=0.3,
            wait_timeout_seconds=1.0,
        )
    )
    asyncio.run(asyncio.sleep(0.4))
    second = asyncio.run(
        manager.acquire(
            owner_id="owner-b",
            job_id="job-b",
            ttl_seconds=1.0,
            wait_timeout_seconds=1.0,
        )
    )

    assert second.fencing_epoch > first.fencing_epoch
    assert second.owner_id == "owner-b"


def test_global_mutex_renew_and_release():
    base = Path("scratch/test_global_mutex")
    base.mkdir(parents=True, exist_ok=True)
    manager = GlobalMutexManager(state_file=base / "lease_renew.json")
    lease = asyncio.run(
        manager.acquire(
            owner_id="owner-a",
            job_id="job-a",
            ttl_seconds=1.0,
            wait_timeout_seconds=1.0,
        )
    )
    renewed = asyncio.run(manager.renew(lease))
    assert renewed.lease_id == lease.lease_id
    assert renewed.expires_at > lease.expires_at

    released = asyncio.run(manager.release(renewed))
    assert released is True
    assert asyncio.run(manager.inspect()) is None


def test_global_mutex_scavenger_reaps_expired_lease_and_cleans_lineage(monkeypatch):
    base = Path("scratch/test_global_mutex")
    base.mkdir(parents=True, exist_ok=True)
    state_file = base / "lease_scavenge_expired.json"
    audit_file = base / "lease_scavenge_expired.audit.jsonl"
    if state_file.exists():
        state_file.unlink()
    if audit_file.exists():
        audit_file.unlink()
    manager = GlobalMutexManager(state_file=state_file, audit_file=audit_file)

    class DummyRegistry:
        def __init__(self) -> None:
            self.calls = []

        def reap_for_lock_scavenge(self, *, fencing_epoch, reason):
            self.calls.append({"fencing_epoch": fencing_epoch, "reason": reason})
            return {
                "cleanup_mode": "fencing_epoch",
                "fencing_epoch": fencing_epoch,
                "reaped_count": 2,
                "reason": reason,
            }

    registry = DummyRegistry()
    monkeypatch.setattr(global_mutex_module, "get_process_lineage_registry", lambda: registry)

    lease = asyncio.run(
        manager.acquire(
            owner_id="owner-expired",
            job_id="job-expired",
            ttl_seconds=0.2,
            wait_timeout_seconds=1.0,
        )
    )
    asyncio.run(asyncio.sleep(0.25))

    first = asyncio.run(manager.scan_and_reap_expired(reason="unit_test_expired"))
    second = asyncio.run(manager.scan_and_reap_expired(reason="unit_test_expired_repeat"))

    assert first["reclaimed_count"] == 1
    assert first["cleanup_mode"] == "fencing_epoch"
    assert first["lineage_reaped_count"] == 2
    assert first["fencing_epoch"] == lease.fencing_epoch
    assert second["reclaimed_count"] == 0
    assert second["skip_reason"] == "no_lease"
    assert len(registry.calls) == 1
    assert registry.calls[0]["fencing_epoch"] == lease.fencing_epoch
    assert asyncio.run(manager.inspect()) is None

    rows = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(r.get("reason") == "unit_test_expired" and int(r.get("reclaimed_count") or 0) == 1 for r in rows)


def test_global_mutex_scavenger_keeps_active_lease(monkeypatch):
    base = Path("scratch/test_global_mutex")
    base.mkdir(parents=True, exist_ok=True)
    state_file = base / "lease_scavenge_active.json"
    audit_file = base / "lease_scavenge_active.audit.jsonl"
    if state_file.exists():
        state_file.unlink()
    if audit_file.exists():
        audit_file.unlink()
    manager = GlobalMutexManager(state_file=state_file, audit_file=audit_file)

    class DummyRegistry:
        def __init__(self) -> None:
            self.calls = 0

        def reap_for_lock_scavenge(self, *, fencing_epoch, reason):
            self.calls += 1
            return {"cleanup_mode": "fencing_epoch", "fencing_epoch": fencing_epoch, "reaped_count": 1, "reason": reason}

    registry = DummyRegistry()
    monkeypatch.setattr(global_mutex_module, "get_process_lineage_registry", lambda: registry)

    lease = asyncio.run(
        manager.acquire(
            owner_id="owner-active",
            job_id="job-active",
            ttl_seconds=2.0,
            wait_timeout_seconds=1.0,
        )
    )

    report = asyncio.run(manager.scan_and_reap_expired(reason="unit_test_active"))
    current = asyncio.run(manager.inspect())

    assert report["reclaimed_count"] == 0
    assert report["skip_reason"] == "lease_active"
    assert registry.calls == 0
    assert current is not None
    assert current.lease_id == lease.lease_id


def test_global_mutex_bootstrap_idle_state_persists_and_stays_claimable():
    base = Path("scratch/test_global_mutex")
    base.mkdir(parents=True, exist_ok=True)
    state_file = base / "lease_bootstrap_idle.json"
    if state_file.exists():
        state_file.unlink()

    manager = GlobalMutexManager(state_file=state_file)
    initialized = manager.ensure_initialized(ttl_seconds=12.0)

    assert initialized["lease_state"] == "idle"
    assert state_file.exists()
    assert asyncio.run(manager.inspect()) is None

    lease = asyncio.run(
        manager.acquire(
            owner_id="owner-bootstrap",
            job_id="job-bootstrap",
            ttl_seconds=1.0,
            wait_timeout_seconds=1.0,
        )
    )
    released = asyncio.run(manager.release(lease))
    assert released is True
    assert asyncio.run(manager.inspect()) is None

    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert payload["lease_state"] == "idle"
    assert int(payload["fencing_epoch"]) >= int(lease.fencing_epoch)

    report = asyncio.run(manager.scan_and_reap_expired(reason="unit_test_idle_state"))
    assert report["reclaimed_count"] == 0
    assert report["skip_reason"] == "no_lease"
