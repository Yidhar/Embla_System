"""Chaos drills for runtime lineage cleanup and artifact storage pressure (NGA-WS17-006)."""

from __future__ import annotations

import errno
import json
import shutil
import uuid
from pathlib import Path

import system.artifact_store as artifact_store_module
from system.artifact_store import ArtifactStore, ArtifactStoreConfig, ContentType
from system.process_lineage import ProcessLineageRegistry


def _fresh_case_dir(name: str) -> Path:
    root = Path("scratch") / "test_chaos_runtime_storage" / f"{name}_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def test_chaos_double_fork_fencing_reaps_detached_ghost_chain(monkeypatch) -> None:
    case_dir = _fresh_case_dir("double_fork")
    registry = ProcessLineageRegistry(
        state_file=case_dir / "lineage_state.json",
        audit_file=case_dir / "lineage_audit.jsonl",
    )

    killed_pids: list[int] = []

    def fake_kill_pid_tree(pid: int) -> bool:
        killed_pids.append(int(pid))
        # Simulate root process already gone, but detached descendants still killable.
        return int(pid) in {9001, 9002}

    monkeypatch.setattr(ProcessLineageRegistry, "_kill_pid_tree", staticmethod(fake_kill_pid_tree))
    monkeypatch.setattr(
        ProcessLineageRegistry,
        "_list_process_rows",
        lambda self: [
            {"pid": 9001, "ppid": 1, "cmdline": "python /srv/chaos_worker.py --trace detached-chain"},
            {"pid": 9002, "ppid": 9001, "cmdline": "python /srv/chaos_worker.py --trace detached-chain --child"},
            {"pid": 8111, "ppid": 1, "cmdline": "python /srv/unrelated_task.py"},
        ],
    )

    try:
        job_id = registry.register_start(
            call_id="call_double_fork",
            command="nohup python /srv/chaos_worker.py --trace detached-chain &",
            root_pid=4242,
            fencing_epoch=7,
        )

        reaped = registry.reap_by_fencing_epoch(7)
        assert reaped == 1
        assert registry.list_running() == []

        saved_state = json.loads((case_dir / "lineage_state.json").read_text(encoding="utf-8"))
        ended = saved_state[job_id]
        assert ended["status"] == "killed"
        assert "fencing_takeover<=epoch_7" in ended["reason"]
        assert "signature_killed=2" in ended["reason"]
        assert killed_pids[0] == 4242
        assert 9001 in killed_pids
        assert 9002 in killed_pids
    finally:
        _cleanup(case_dir)


def test_chaos_enospc_store_failure_keeps_metadata_consistent(monkeypatch) -> None:
    case_dir = _fresh_case_dir("enospc")
    root = case_dir / "artifacts"
    store = ArtifactStore(
        ArtifactStoreConfig(
            artifact_root=root,
            max_total_size_mb=8,
            max_single_artifact_mb=4,
            max_artifact_count=20,
        )
    )

    try:
        ok, _, baseline_meta = store.store(
            content="baseline-content",
            content_type=ContentType.TEXT_PLAIN,
            source_tool="chaos_seed",
        )
        assert ok is True
        assert baseline_meta is not None

        metadata_file = root / store.config.metadata_file
        initial_disk_metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        assert set(initial_disk_metadata.keys()) == {baseline_meta.artifact_id}

        real_open = open

        def enospc_on_artifact_write(file, mode="r", *args, **kwargs):
            path = Path(file)
            if "w" in str(mode) and path.suffix == ".dat":
                raise OSError(errno.ENOSPC, "No space left on device")
            return real_open(file, mode, *args, **kwargs)

        monkeypatch.setattr(artifact_store_module, "open", enospc_on_artifact_write, raising=False)

        ok, message, failed_meta = store.store(
            content="y" * 4096,
            content_type=ContentType.TEXT_PLAIN,
            source_tool="chaos_pressure",
        )
        assert ok is False
        assert failed_meta is None
        assert "Failed to write artifact" in message
        assert "No space left on device" in message

        runtime_metrics = store.get_metrics_snapshot()
        assert runtime_metrics["store_attempt"] == 2
        assert runtime_metrics["store_success"] == 1
        assert runtime_metrics["artifact_count"] == 1

        disk_metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        assert set(disk_metadata.keys()) == {baseline_meta.artifact_id}
        assert len(list(root.rglob("*.dat"))) == 1

        ok, _, restored = store.retrieve(baseline_meta.artifact_id)
        assert ok is True
        assert restored == "baseline-content"
    finally:
        _cleanup(case_dir)
