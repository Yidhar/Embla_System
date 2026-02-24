"""Process lineage registry tests (WS14-005/006)."""

from __future__ import annotations

from pathlib import Path

from system.process_lineage import ProcessLineageRegistry


def test_process_lineage_register_start_end():
    base = Path("scratch/test_process_lineage")
    base.mkdir(parents=True, exist_ok=True)
    registry = ProcessLineageRegistry(
        state_file=base / "lineage_state_1.json",
        audit_file=base / "lineage_audit_1.jsonl",
    )
    job_id = registry.register_start(
        call_id="call_1",
        command="echo hello",
        root_pid=12345,
        fencing_epoch=2,
    )
    running = registry.list_running()
    assert len(running) == 1
    assert running[0].job_root_id == job_id

    registry.register_end(job_id, return_code=0, status="ok")
    running_after = registry.list_running()
    assert running_after == []


def test_process_lineage_reap_by_epoch(monkeypatch):
    base = Path("scratch/test_process_lineage")
    base.mkdir(parents=True, exist_ok=True)
    registry = ProcessLineageRegistry(
        state_file=base / "lineage_state_2.json",
        audit_file=base / "lineage_audit_2.jsonl",
    )
    monkeypatch.setattr(ProcessLineageRegistry, "_kill_pid_tree", staticmethod(lambda pid: True))

    j1 = registry.register_start(
        call_id="call_old",
        command="old",
        root_pid=111,
        fencing_epoch=1,
    )
    _ = registry.register_start(
        call_id="call_new",
        command="new",
        root_pid=222,
        fencing_epoch=3,
    )

    killed = registry.reap_by_fencing_epoch(1)
    assert killed == 1

    # j1 should no longer be in running set.
    running_ids = {r.job_root_id for r in registry.list_running()}
    assert j1 not in running_ids


def test_process_lineage_kill_job_fallback_signature(monkeypatch):
    base = Path("scratch/test_process_lineage")
    base.mkdir(parents=True, exist_ok=True)
    registry = ProcessLineageRegistry(
        state_file=base / "lineage_state_3.json",
        audit_file=base / "lineage_audit_3.jsonl",
    )
    monkeypatch.setattr(ProcessLineageRegistry, "_kill_pid_tree", staticmethod(lambda pid: False))
    monkeypatch.setattr(ProcessLineageRegistry, "_kill_by_signature", lambda self, tokens, exclude_pids=None: 1)

    job_id = registry.register_start(
        call_id="call_detached",
        command="nohup python app.py &",
        root_pid=333,
        fencing_epoch=5,
    )
    ok = registry.kill_job(job_id, reason="unit_test_fallback")
    assert ok is True
    assert registry.list_running() == []


def test_reap_orphaned_running_jobs(monkeypatch):
    base = Path("scratch/test_process_lineage")
    base.mkdir(parents=True, exist_ok=True)
    registry = ProcessLineageRegistry(
        state_file=base / "lineage_state_4.json",
        audit_file=base / "lineage_audit_4.jsonl",
    )
    monkeypatch.setattr(ProcessLineageRegistry, "_is_pid_alive", staticmethod(lambda pid: False))
    monkeypatch.setattr(ProcessLineageRegistry, "_kill_by_signature", lambda self, tokens, exclude_pids=None: 0)

    _ = registry.register_start(
        call_id="call_orphan",
        command="nohup python worker.py &",
        root_pid=444,
        fencing_epoch=2,
    )
    cleaned = registry.reap_orphaned_running_jobs(reason="unit_test_orphan", max_epoch=2)
    assert cleaned == 1
    assert registry.list_running() == []


def test_reap_for_lock_scavenge_without_epoch(monkeypatch):
    base = Path("scratch/test_process_lineage")
    base.mkdir(parents=True, exist_ok=True)
    registry = ProcessLineageRegistry(
        state_file=base / "lineage_state_5.json",
        audit_file=base / "lineage_audit_5.jsonl",
    )
    monkeypatch.setattr(ProcessLineageRegistry, "_is_pid_alive", staticmethod(lambda pid: False))
    monkeypatch.setattr(ProcessLineageRegistry, "_kill_by_signature", lambda self, tokens, exclude_pids=None: 0)

    _ = registry.register_start(
        call_id="call_orphan_only",
        command="nohup python ghost.py &",
        root_pid=555,
        fencing_epoch=None,
    )
    report = registry.reap_for_lock_scavenge(fencing_epoch=None, reason="unit_test_lock_scavenge")
    assert report["cleanup_mode"] == "orphan_running_jobs"
    assert int(report["reaped_count"] or 0) == 1
    assert registry.list_running() == []
