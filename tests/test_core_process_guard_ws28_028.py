from __future__ import annotations

import json
from pathlib import Path

from core.supervisor.process_guard import ProcessGuardDaemon
from system.process_lineage import ProcessLineageRegistry


def test_process_guard_detects_orphan_running_job(tmp_path: Path) -> None:
    registry = ProcessLineageRegistry(
        state_file=tmp_path / "lineage_state.json",
        audit_file=tmp_path / "lineage_events.jsonl",
    )
    job_root_id = registry.register_start(
        call_id="call_ws28_028_001",
        command="python -m demo",
        root_pid=999999,  # intentionally non-existing PID
        fencing_epoch=1,
    )
    assert job_root_id

    daemon = ProcessGuardDaemon(registry=registry)
    payload = daemon.run_once(auto_reap=False)
    assert payload["status"] == "critical"
    assert payload["reason_code"] == "PROCESS_GUARD_ORPHAN_RUNNING_JOBS"
    assert payload["orphan_jobs"] >= 1


def test_process_guard_daemon_writes_state_file(tmp_path: Path) -> None:
    registry = ProcessLineageRegistry(
        state_file=tmp_path / "lineage_state.json",
        audit_file=tmp_path / "lineage_events.jsonl",
    )
    state_file = tmp_path / "process_guard_state.json"
    daemon = ProcessGuardDaemon(registry=registry)
    report = daemon.run_daemon(state_file=state_file, interval_seconds=0.0, max_ticks=2)

    assert report["ticks_completed"] == 2
    assert state_file.exists() is True
    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert payload["tick"] == 2
    assert payload["mode"] == "daemon"
    assert payload["status"] in {"ok", "warning", "critical"}
