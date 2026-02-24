from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from autonomous.state import WorkflowStore
from scripts.export_slo_snapshot import build_snapshot, export_snapshot
from system.artifact_store import ArtifactStore, ArtifactStoreConfig, ContentType


def _make_repo_root() -> Path:
    repo_root = Path("scratch") / "test_slo_snapshot_export" / uuid.uuid4().hex[:12]
    repo_root.mkdir(parents=True, exist_ok=True)
    return repo_root


def _cleanup_repo_root(repo_root: Path) -> None:
    shutil.rmtree(repo_root, ignore_errors=True)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(payload + "\n", encoding="utf-8")


def _write_autonomous_config(path: Path, *, max_error_rate: float, max_latency_p95_ms: float, batch_size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "autonomous:",
                "  release:",
                f"    max_error_rate: {max_error_rate}",
                f"    max_latency_p95_ms: {max_latency_p95_ms}",
                "  outbox_dispatch:",
                f"    batch_size: {batch_size}",
                "  lease:",
                "    ttl_seconds: 10",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_build_snapshot_schema_and_values() -> None:
    repo_root = _make_repo_root()
    now_dt = datetime.now(timezone.utc)

    try:
        _write_autonomous_config(
            repo_root / "autonomous" / "config" / "autonomous_config.yaml",
            max_error_rate=0.2,
            max_latency_p95_ms=300.0,
            batch_size=1,
        )

        events = [
            {
                "timestamp": now_dt.isoformat(),
                "event_type": "CliExecutionCompleted",
                "payload": {"success": True, "duration_seconds": 0.2},
            },
            {
                "timestamp": (now_dt + timedelta(seconds=1)).isoformat(),
                "event_type": "CliExecutionCompleted",
                "payload": {"success": False, "duration_seconds": 0.4},
            },
            {
                "timestamp": (now_dt + timedelta(seconds=2)).isoformat(),
                "event_type": "CliExecutionCompleted",
                "payload": {"success": True, "duration_seconds": 0.1},
            },
        ]
        _write_jsonl(repo_root / "logs" / "autonomous" / "events.jsonl", events)

        store = WorkflowStore(db_path=repo_root / "logs" / "autonomous" / "workflow.db")
        store.create_workflow(workflow_id="wf-1", task_id="task-1")
        store.enqueue_outbox("wf-1", "TaskApproved", {"ok": True})
        store.enqueue_outbox("wf-1", "TaskApproved", {"ok": True})

        lock_payload = {
            "lease_id": "lease-test",
            "owner_id": "owner-a",
            "job_id": "job-a",
            "fencing_epoch": 2,
            "ttl_seconds": 10,
            "expires_at": now_dt.timestamp() + 1.0,
        }
        lock_file = repo_root / "logs" / "runtime" / "global_mutex_lease.json"
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        lock_file.write_text(json.dumps(lock_payload), encoding="utf-8")

        artifact_store = ArtifactStore(ArtifactStoreConfig(artifact_root=repo_root / "logs" / "artifacts"))
        ok, _, _ = artifact_store.store(
            content="sample-artifact",
            content_type=ContentType.TEXT_PLAIN,
            priority="normal",
        )
        assert ok is True

        snapshot = build_snapshot(repo_root=repo_root, now=now_dt)

        assert snapshot["schema_version"] == "1.0.0"
        assert "summary" in snapshot
        assert "metrics" in snapshot
        assert "threshold_profile" in snapshot
        assert "sources" in snapshot

        metrics = snapshot["metrics"]
        assert set(metrics.keys()) == {
            "error_rate",
            "latency_p95_ms",
            "queue_depth",
            "disk_watermark_ratio",
            "lock_status",
        }

        assert metrics["error_rate"]["source"] == "cli_execution_events"
        assert metrics["error_rate"]["value"] == pytest.approx(1 / 3)
        assert metrics["error_rate"]["status"] == "critical"

        assert metrics["latency_p95_ms"]["value"] == pytest.approx(400.0)
        assert metrics["latency_p95_ms"]["status"] == "critical"

        assert metrics["queue_depth"]["value"] == 2
        assert metrics["queue_depth"]["status"] == "warning"

        assert metrics["disk_watermark_ratio"]["source"] == "artifact_store"
        assert metrics["disk_watermark_ratio"]["artifact_count"] >= 1

        assert metrics["lock_status"]["state"] == "near_expiry"
        assert metrics["lock_status"]["status"] == "warning"

        assert snapshot["summary"]["overall_status"] == "critical"

        written = export_snapshot(snapshot, output_file=repo_root / "logs" / "runtime" / "snapshot.json")
        assert written.exists()
        restored = json.loads(written.read_text(encoding="utf-8"))
        assert restored["metrics"]["error_rate"]["value"] == pytest.approx(1 / 3)
    finally:
        _cleanup_repo_root(repo_root)


def test_build_snapshot_fallback_to_canary_windows() -> None:
    repo_root = _make_repo_root()
    now_dt = datetime.now(timezone.utc)

    try:
        _write_autonomous_config(
            repo_root / "autonomous" / "config" / "autonomous_config.yaml",
            max_error_rate=0.25,
            max_latency_p95_ms=260.0,
            batch_size=5,
        )

        events = [
            {
                "timestamp": now_dt.isoformat(),
                "event_type": "ChangePromoted",
                "payload": {
                    "decision": {
                        "evaluated_windows": [
                            {
                                "window_minutes": 15,
                                "sample_count": 100,
                                "error_rate": 0.1,
                                "latency_p95_ms": 100.0,
                                "eligible": True,
                            },
                            {
                                "window_minutes": 15,
                                "sample_count": 100,
                                "error_rate": 0.3,
                                "latency_p95_ms": 250.0,
                                "eligible": True,
                            },
                        ]
                    }
                },
            }
        ]
        _write_jsonl(repo_root / "logs" / "autonomous" / "events.jsonl", events)

        snapshot = build_snapshot(repo_root=repo_root, now=now_dt)

        error_rate = snapshot["metrics"]["error_rate"]
        latency = snapshot["metrics"]["latency_p95_ms"]

        assert error_rate["source"] == "canary_evaluated_windows"
        assert error_rate["sample_count"] == 200
        assert error_rate["value"] == pytest.approx(0.2)
        assert error_rate["status"] == "warning"

        assert latency["source"] == "canary_evaluated_windows"
        assert latency["value"] == pytest.approx(250.0)
        assert latency["status"] == "warning"
    finally:
        _cleanup_repo_root(repo_root)
