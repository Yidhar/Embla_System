from __future__ import annotations

import asyncio
from pathlib import Path

from core.security.lease_fencing import LeaseFencingController
from system.global_mutex import GlobalMutexManager


def test_lease_fencing_controller_full_lifecycle(tmp_path: Path) -> None:
    manager = GlobalMutexManager(
        state_file=tmp_path / "global_mutex_lease.json",
        audit_file=tmp_path / "global_mutex_events.jsonl",
    )
    controller = LeaseFencingController(manager=manager)

    init_state = controller.ensure_initialized(ttl_seconds=3.0)
    assert init_state["state_file"].endswith("global_mutex_lease.json")

    acquired = asyncio.run(
        controller.acquire(
            owner_id="tester-owner",
            job_id="job-1",
            ttl_seconds=3.0,
            wait_timeout_seconds=2.0,
        )
    )
    assert acquired.fencing_epoch >= 1
    assert acquired.owner_id == "tester-owner"

    renewed = asyncio.run(controller.renew(acquired))
    assert renewed.lease_id == acquired.lease_id
    assert renewed.expires_at >= acquired.expires_at

    inspected = asyncio.run(controller.inspect())
    assert inspected is not None
    assert inspected.lease_id == acquired.lease_id

    released = asyncio.run(controller.release(renewed))
    assert released is True

    inspected_after_release = asyncio.run(controller.inspect())
    assert inspected_after_release is None

    scan_report = asyncio.run(controller.scan_and_reap_expired(reason="unit_test_scan"))
    assert scan_report["state_file"].endswith("global_mutex_lease.json")
    assert "reclaimed_count" in scan_report

