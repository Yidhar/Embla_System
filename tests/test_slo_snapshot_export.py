from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agents.runtime.workflow_store import WorkflowStore
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


def _write_autonomous_config(
    path: Path,
    *,
    max_error_rate: float,
    max_latency_p95_ms: float,
    batch_size: int,
    rollout_percent: int = 100,
    fail_open_budget_ratio: float = 0.15,
) -> None:
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
                "    lease_name: global_orchestrator",
                "  subagent_runtime:",
                f"    rollout_percent: {rollout_percent}",
                f"    fail_open_budget_ratio: {fail_open_budget_ratio}",
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
            repo_root / "config" / "autonomous_runtime.yaml",
            max_error_rate=0.2,
            max_latency_p95_ms=300.0,
            batch_size=1,
            rollout_percent=50,
            fail_open_budget_ratio=0.6,
        )

        events = [
            {
                "timestamp": now_dt.isoformat(),
                "event_type": "TaskExecutionCompleted",
                "payload": {"success": True, "duration_seconds": 0.2},
            },
            {
                "timestamp": (now_dt + timedelta(seconds=1)).isoformat(),
                "event_type": "TaskExecutionCompleted",
                "payload": {"success": False, "duration_seconds": 0.4},
            },
            {
                "timestamp": (now_dt + timedelta(seconds=2)).isoformat(),
                "event_type": "TaskExecutionCompleted",
                "payload": {"success": True, "duration_seconds": 0.1},
            },
            {
                "timestamp": (now_dt + timedelta(seconds=3)).isoformat(),
                "event_type": "SubAgentRuntimeRolloutDecision",
                "payload": {"runtime_mode": "subagent", "decision_reason": "rollout_bucket_hit"},
            },
            {
                "timestamp": (now_dt + timedelta(seconds=4)).isoformat(),
                "event_type": "SubAgentRuntimeRolloutDecision",
                "payload": {"runtime_mode": "subagent", "decision_reason": "rollout_bucket_miss_subagent_only"},
            },
            {
                "timestamp": (now_dt + timedelta(seconds=5)).isoformat(),
                "event_type": "SubAgentRuntimeCompleted",
                "payload": {"runtime_id": "sar-1"},
            },
            {
                "timestamp": (now_dt + timedelta(seconds=6)).isoformat(),
                "event_type": "SubAgentRuntimeCompleted",
                "payload": {"runtime_id": "sar-2"},
            },
            {
                "timestamp": (now_dt + timedelta(seconds=7)).isoformat(),
                "event_type": "SubAgentRuntimeFailOpen",
                "payload": {"runtime_id": "sar-2", "gate_failure": "scaffold"},
            },
            {
                "timestamp": (now_dt + timedelta(seconds=8)).isoformat(),
                "event_type": "LeaseAcquired",
                "payload": {"fencing_epoch": 1},
            },
            {
                "timestamp": (now_dt + timedelta(seconds=9)).isoformat(),
                "event_type": "LeaseLost",
                "payload": {"fencing_epoch": 1},
            },
            {
                "timestamp": (now_dt + timedelta(seconds=10)).isoformat(),
                "event_type": "PromptInjectionComposed",
                "payload": {
                    "route_semantic": "shell_readonly",
                    "trigger": "shell_readonly",
                    "selected_slice_count": 2,
                    "dropped_slice_count": 2,
                    "dropped_conflict_count": 2,
                    "selected_layer_counts": {
                        "L0_DNA": 1,
                        "L1_TASK_BASE": 1,
                    },
                    "delegation_intent": "read_only_exploration",
                    "delegation_hit": False,
                    "shell_readonly_hit": True,
                    "readonly_write_tool_exposed": False,
                    "readonly_write_tool_selected_count": 0,
                    "readonly_write_tool_dropped_count": 1,
                    "prefix_cache_hit": False,
                    "tail_hash": "tail-a",
                    "recovery_hit": False,
                },
            },
            {
                "timestamp": (now_dt + timedelta(seconds=11)).isoformat(),
                "event_type": "PromptInjectionComposed",
                "payload": {
                    "route_semantic": "core_execution",
                    "trigger": "core_execution",
                    "selected_slice_count": 3,
                    "dropped_slice_count": 0,
                    "dropped_conflict_count": 0,
                    "selected_layer_counts": {
                        "L0_DNA": 1,
                        "L3_TOOL_POLICY": 1,
                        "L4_RECOVERY": 1,
                    },
                    "delegation_intent": "delegate_core_execution",
                    "delegation_hit": True,
                    "shell_readonly_hit": False,
                    "readonly_write_tool_exposed": False,
                    "readonly_write_tool_selected_count": 1,
                    "readonly_write_tool_dropped_count": 0,
                    "prefix_cache_hit": True,
                    "tail_hash": "tail-b",
                    "recovery_hit": True,
                    "contract_upgrade_latency_ms": 120.0,
                    "recovery_context_survived": True,
                },
            },
        ]
        _write_jsonl(repo_root / "logs" / "autonomous" / "events.jsonl", events)

        store = WorkflowStore(db_path=repo_root / "logs" / "autonomous" / "workflow.db")
        store.create_workflow(workflow_id="wf-1", task_id="task-1")
        store.enqueue_outbox("wf-1", "TaskApproved", {"ok": True})
        store.enqueue_outbox("wf-1", "TaskApproved", {"ok": True})
        store.try_acquire_or_renew_lease(
            lease_name="global_orchestrator",
            owner_id="owner-a",
            ttl_seconds=1,
        )

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
            "runtime_rollout",
            "runtime_fail_open",
            "runtime_lease",
            "prompt_slice_count_by_layer",
            "injection_trigger_distribution",
            "recovery_slice_hit_rate",
            "prompt_conflict_drop_count",
            "delegation_hit_rate",
            "shell_readonly_hit_rate",
            "readonly_write_tool_exposure_rate",
            "shell_to_core_dispatch_rate",
            "agent_route_semantic_distribution",
            "shell_clarify_budget_escalation_rate",
            "core_execution_session_creation_rate",
            "core_execution_route_distribution",
            "prompt_prefix_cache_hit_rate",
            "prompt_tail_churn_rate",
            "contract_upgrade_latency_ms",
            "recovery_context_survival_rate",
        }

        assert metrics["error_rate"]["source"] == "task_execution_events"
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

        assert metrics["runtime_rollout"]["total_decisions"] == 2
        assert metrics["runtime_rollout"]["subagent_decisions"] == 2
        assert metrics["runtime_rollout"]["legacy_decisions"] == 0
        assert metrics["runtime_rollout"]["value"] == pytest.approx(1.0)
        assert metrics["runtime_rollout"]["namespace_status"] == "archived_legacy"

        assert metrics["runtime_fail_open"]["subagent_attempt_count"] == 2
        assert metrics["runtime_fail_open"]["fail_open_count"] == 1
        assert metrics["runtime_fail_open"]["fail_open_blocked_count"] == 0
        assert metrics["runtime_fail_open"]["value"] == pytest.approx(0.5)
        assert metrics["runtime_fail_open"]["budget_exhausted"] is False
        assert metrics["runtime_fail_open"]["namespace_status"] == "archived_legacy"

        assert metrics["runtime_lease"]["lease_acquired_count"] == 1
        assert metrics["runtime_lease"]["lease_lost_count"] == 1
        assert metrics["runtime_lease"]["owner_id"] == "owner-a"
        assert metrics["runtime_lease"]["state"] == "near_expiry"

        assert metrics["prompt_slice_count_by_layer"]["value"] == pytest.approx(2.5)
        assert metrics["prompt_slice_count_by_layer"]["selected_layer_counts"]["L0_DNA"] == 2
        assert metrics["prompt_slice_count_by_layer"]["selected_layer_counts"]["L4_RECOVERY"] == 1
        assert metrics["injection_trigger_distribution"]["trigger_counts"]["shell_readonly"] == 1
        assert metrics["injection_trigger_distribution"]["trigger_counts"]["core_execution"] == 1
        assert metrics["recovery_slice_hit_rate"]["value"] == pytest.approx(0.5)
        assert metrics["prompt_conflict_drop_count"]["value"] == pytest.approx(2.0)
        assert metrics["delegation_hit_rate"]["value"] == pytest.approx(0.5)
        assert metrics["shell_readonly_hit_rate"]["value"] == pytest.approx(0.5)
        assert metrics["shell_readonly_hit_rate"]["value"] == pytest.approx(0.5)
        assert metrics["readonly_write_tool_exposure_rate"]["value"] == pytest.approx(0.0)
        assert metrics["readonly_write_tool_exposure_rate"]["sample_count"] == 1
        assert metrics["readonly_write_tool_exposure_rate"]["exposure_count"] == 0
        assert metrics["readonly_write_tool_exposure_rate"]["status"] == "ok"
        assert metrics["shell_to_core_dispatch_rate"]["value"] == pytest.approx(0.5)
        assert metrics["agent_route_semantic_distribution"]["route_semantic_counts"]["shell_readonly"] == 1
        assert metrics["agent_route_semantic_distribution"]["route_semantic_counts"]["shell_clarify"] == 0
        assert metrics["agent_route_semantic_distribution"]["route_semantic_counts"]["core_execution"] == 1
        assert metrics["agent_route_semantic_distribution"]["route_semantic_ratios"]["core_execution"] == pytest.approx(0.5)
        assert metrics["shell_clarify_budget_escalation_rate"]["sample_count"] == 0
        assert metrics["shell_clarify_budget_escalation_rate"]["value"] is None
        assert metrics["core_execution_session_creation_rate"]["sample_count"] == 1
        assert metrics["core_execution_session_creation_rate"]["value"] == pytest.approx(0.0)
        assert metrics["core_execution_route_distribution"]["sample_count"] == 1
        assert metrics["core_execution_route_distribution"]["route_counts"]["unspecified"] == 1
        assert metrics["prompt_prefix_cache_hit_rate"]["value"] == pytest.approx(0.5)
        assert metrics["prompt_tail_churn_rate"]["value"] == pytest.approx(1.0)
        assert metrics["contract_upgrade_latency_ms"]["value"] == pytest.approx(120.0)
        assert metrics["recovery_context_survival_rate"]["value"] == pytest.approx(1.0)

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
            repo_root / "config" / "autonomous_runtime.yaml",
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


def test_build_snapshot_lock_status_idle_state_is_ok() -> None:
    repo_root = _make_repo_root()
    now_dt = datetime.now(timezone.utc)
    try:
        _write_autonomous_config(
            repo_root / "config" / "autonomous_runtime.yaml",
            max_error_rate=0.2,
            max_latency_p95_ms=300.0,
            batch_size=5,
        )
        _write_jsonl(repo_root / "logs" / "autonomous" / "events.jsonl", [])

        lock_file = repo_root / "logs" / "runtime" / "global_mutex_lease.json"
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        lock_file.write_text(
            json.dumps(
                {
                    "lease_state": "idle",
                    "state": "idle",
                    "lease_id": "",
                    "owner_id": "",
                    "job_id": "",
                    "fencing_epoch": 3,
                    "ttl_seconds": 10.0,
                    "issued_at": now_dt.timestamp(),
                    "expires_at": now_dt.timestamp() + 10.0,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        snapshot = build_snapshot(repo_root=repo_root, now=now_dt)
        lock_status = snapshot["metrics"]["lock_status"]
        assert lock_status["state"] == "idle"
        assert lock_status["status"] == "ok"
        assert lock_status["source"] == "global_mutex_state_idle"
    finally:
        _cleanup_repo_root(repo_root)
