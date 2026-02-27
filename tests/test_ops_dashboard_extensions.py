from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import apiserver.api_server as api_server


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
    path.write_text(content, encoding="utf-8")


def test_ops_evidence_index_payload_flags_hard_gate_failures(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path
    reports_dir = repo_root / "scratch" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        reports_dir / "release_closure_chain_full_m0_m12_result.json",
        {
            "scenario": "release_closure_chain_full_m0_m12",
            "generated_at": "2026-02-25T10:00:00+00:00",
            "passed": True,
            "checks": {"full_chain_passed": True},
        },
    )
    _write_json(
        reports_dir / "ws27_subagent_cutover_status_ws27_002.json",
        {
            "scenario": "legacy_to_subagent_full_cutover_and_rollback_window",
            "generated_at": "2026-02-25T10:05:00+00:00",
            "passed": False,
            "checks": {"subagent_runtime_enabled": False},
        },
    )
    _write_json(
        reports_dir / "ws27_72h_wallclock_acceptance_ws27_001.json",
        {
            "scenario": "ws27_72h_wallclock_acceptance",
            "generated_at": "2026-02-25T10:06:00+00:00",
            "passed": False,
            "checks": {"wallclock_target_reached": False},
        },
    )

    monkeypatch.setattr(api_server, "_ops_repo_root", lambda: repo_root)
    payload = api_server._ops_build_evidence_index_payload(max_reports=20)

    assert payload["status"] == "success"
    assert payload["severity"] == "critical"
    assert payload["reason_code"] == "EVIDENCE_HARD_REPORT_MISSING"

    summary = payload["data"]["summary"]
    assert summary["required_total"] == len(api_server._OPS_REQUIRED_REPORT_DEFINITIONS)
    assert summary["required_present"] == 3
    assert summary["hard_missing"] >= 1
    assert summary["hard_failed"] == 1
    assert summary["soft_failed"] == 1

    required_reports = payload["data"]["required_reports"]
    assert any(item["id"] == "full_chain_m0_m12" and item["status"] == "passed" for item in required_reports)
    assert any(item["id"] == "cutover_status_ws27_002" and item["status"] == "failed" for item in required_reports)


def test_ops_incidents_latest_payload_merges_events_and_report_issues(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path
    now = datetime(2026, 2, 25, 12, 0, tzinfo=timezone.utc)
    events_file = repo_root / "logs" / "autonomous" / "events.jsonl"
    _write_jsonl(
        events_file,
        [
            {
                "timestamp": now.isoformat(),
                "event_type": "LeaseLost",
                "payload": {"owner_id": "runner-a"},
            },
            {
                "timestamp": now.replace(minute=1).isoformat(),
                "event_type": "SubAgentRuntimeFailOpen",
                "payload": {"runtime_id": "sar-001"},
            },
        ],
    )

    reports_dir = repo_root / "scratch" / "reports"
    _write_json(
        reports_dir / "ws27_72h_wallclock_acceptance_ws27_001.json",
        {
            "scenario": "ws27_72h_wallclock_acceptance",
            "generated_at": "2026-02-25T12:02:00+00:00",
            "passed": False,
            "checks": {"wallclock_target_reached": False},
        },
    )

    monkeypatch.setattr(api_server, "_ops_repo_root", lambda: repo_root)
    from scripts import export_slo_snapshot

    monkeypatch.setattr(
        export_slo_snapshot,
        "build_snapshot",
        lambda **_kwargs: {
            "metrics": {
                "outer_readonly_hit_rate": {"value": 0.6, "sample_count": 10, "hit_count": 6, "status": "ok"},
                "readonly_write_tool_exposure_rate": {
                    "value": 0.1,
                    "sample_count": 10,
                    "exposure_count": 1,
                    "exposed_slice_count": 1,
                    "status": "warning",
                },
                "chat_route_path_distribution": {
                    "sample_count": 10,
                    "path_counts": {"path-a": 4, "path-b": 2, "path-c": 4},
                    "path_ratios": {"path-a": 0.4, "path-b": 0.2, "path-c": 0.4},
                    "status": "ok",
                },
                "path_b_budget_escalation_rate": {
                    "value": 0.5,
                    "sample_count": 2,
                    "escalated_count": 1,
                    "status": "warning",
                },
                "core_session_creation_rate": {
                    "value": 0.75,
                    "sample_count": 4,
                    "created_count": 3,
                    "status": "warning",
                },
            }
        },
    )
    payload = api_server._ops_build_incidents_latest_payload(limit=30)

    assert payload["status"] == "success"
    assert payload["severity"] == "critical"
    assert payload["data"]["events_scanned"] == 2
    assert payload["data"]["event_counters"]["LeaseLost"] == 1
    assert payload["data"]["event_counters"]["SubAgentRuntimeFailOpen"] == 1

    incidents = payload["data"]["incidents"]
    assert any(item["source"] == "events" for item in incidents)
    assert any(item["source"] == "report" for item in incidents)
    assert any(item["event_type"] == "EvidenceGateIssue" for item in incidents)
    assert any(path.endswith("events.jsonl") for path in payload["source_reports"])

    runtime_prompt_safety = payload["data"]["summary"]["runtime_prompt_safety"]
    assert runtime_prompt_safety["outer_readonly_hit_rate"]["value"] == 0.6
    assert runtime_prompt_safety["readonly_write_tool_exposure_rate"]["value"] == 0.1
    assert runtime_prompt_safety["readonly_write_tool_exposure_rate"]["status"] == "warning"
    assert runtime_prompt_safety["chat_route_path_distribution"]["path_ratios"]["path-c"] == 0.4
    assert runtime_prompt_safety["path_b_budget_escalation_rate"]["escalated_count"] == 1
    assert runtime_prompt_safety["core_session_creation_rate"]["created_count"] == 3
    assert runtime_prompt_safety["route_quality"]["status"] == "warning"
    assert "READONLY_WRITE_EXPOSURE_WARNING" in runtime_prompt_safety["route_quality"]["reason_codes"]
    assert runtime_prompt_safety["route_quality"]["trend"]["status"] == "unknown"
    assert runtime_prompt_safety["route_quality"]["trend"]["sample_count"] == 0


def test_ops_incidents_latest_payload_includes_brainstem_stale_incident(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path
    now = datetime(2026, 2, 26, 12, 0, tzinfo=timezone.utc)
    heartbeat_file = repo_root / "scratch" / "runtime" / "brainstem_control_plane_heartbeat_ws23_001.json"
    _write_json(
        heartbeat_file,
        {
            "generated_at": datetime(2026, 2, 26, 10, 0, tzinfo=timezone.utc).isoformat(),
            "pid": 43001,
            "tick": 8,
            "mode": "daemon",
            "healthy": True,
            "service_count": 2,
            "unhealthy_services": [],
        },
    )

    monkeypatch.setattr(api_server, "_ops_repo_root", lambda: repo_root)
    monkeypatch.setattr(api_server, "_ops_collect_required_reports", lambda _repo_root: [])
    monkeypatch.setattr(api_server.time, "time", lambda: now.timestamp())
    from scripts import export_slo_snapshot

    monkeypatch.setattr(export_slo_snapshot, "build_snapshot", lambda **_kwargs: {"metrics": {}})
    payload = api_server._ops_build_incidents_latest_payload(limit=30)

    incidents = payload["data"]["incidents"]
    stale = [item for item in incidents if str(item.get("event_type")) == "BrainstemHeartbeatStale"]
    assert len(stale) == 1
    stale_item = stale[0]
    assert stale_item["source"] == "report"
    assert stale_item["severity"] == "critical"
    assert stale_item["payload_excerpt"]["reason_code"] == "BRAINSTEM_HEARTBEAT_STALE_CRITICAL"
    assert any(path.endswith("brainstem_control_plane_heartbeat_ws23_001.json") for path in payload["source_reports"])


def test_ops_incidents_latest_payload_includes_watchdog_daemon_stale_incident(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path
    now = datetime(2026, 2, 26, 12, 0, tzinfo=timezone.utc)
    watchdog_state_file = repo_root / "scratch" / "runtime" / "watchdog_daemon_state_ws28_025.json"
    _write_json(
        watchdog_state_file,
        {
            "generated_at": datetime(2026, 2, 26, 10, 0, tzinfo=timezone.utc).isoformat(),
            "pid": 52001,
            "tick": 9,
            "mode": "daemon",
            "warn_only": False,
            "threshold_hit": False,
            "status": "ok",
            "snapshot": {},
            "action": None,
        },
    )

    monkeypatch.setattr(api_server, "_ops_repo_root", lambda: repo_root)
    monkeypatch.setattr(api_server, "_ops_collect_required_reports", lambda _repo_root: [])
    monkeypatch.setattr(api_server.time, "time", lambda: now.timestamp())
    from scripts import export_slo_snapshot

    monkeypatch.setattr(export_slo_snapshot, "build_snapshot", lambda **_kwargs: {"metrics": {}})
    payload = api_server._ops_build_incidents_latest_payload(limit=30)

    incidents = payload["data"]["incidents"]
    stale = [item for item in incidents if str(item.get("event_type")) == "WatchdogDaemonStateStale"]
    assert len(stale) == 1
    stale_item = stale[0]
    assert stale_item["source"] == "report"
    assert stale_item["severity"] == "critical"
    assert stale_item["payload_excerpt"]["reason_code"] == "WATCHDOG_DAEMON_STALE_CRITICAL"
    assert any(path.endswith("watchdog_daemon_state_ws28_025.json") for path in payload["source_reports"])


def test_ops_runtime_posture_payload_includes_execution_bridge_governance(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path
    events_file = repo_root / "logs" / "autonomous" / "events.jsonl"
    _write_jsonl(
        events_file,
        [
            {
                "timestamp": "2026-02-27T09:00:00+00:00",
                "event_type": "SubTaskExecutionCompleted",
                "payload": {
                    "task_id": "task-gov-1",
                    "subtask_id": "be-1",
                    "role": "backend",
                    "success": False,
                    "execution_bridge_governance": {
                        "status": "critical",
                        "severity": "critical",
                        "category": "semantic_toolchain",
                        "reason_code": "SEMANTIC_TOOLCHAIN_VIOLATION",
                        "reason": "execution_bridge_semantic_toolchain_violation:backend",
                        "executor": "backend",
                        "policy_source": "task.contract_schema.role_executor_policy",
                        "violation_count": 1,
                        "violations": ["scripts/deploy_release.sh::ops"],
                    },
                },
            }
        ],
    )

    def _fake_snapshot(*, repo_root: Path, events_limit: int):  # noqa: ARG001
        return {
            "summary": {"overall_status": "ok", "metric_status": {}},
            "metrics": {},
            "threshold_profile": {},
            "sources": {"events_file": "logs/autonomous/events.jsonl"},
        }

    from scripts import export_slo_snapshot

    monkeypatch.setattr(export_slo_snapshot, "build_snapshot", _fake_snapshot)
    monkeypatch.setattr(api_server, "_ops_repo_root", lambda: repo_root)

    payload = api_server._ops_build_runtime_posture_payload(events_limit=200)
    assert payload["status"] == "success"
    assert payload["severity"] == "critical"
    assert payload["reason_code"] == "EXECUTION_BRIDGE_GOVERNANCE_CRITICAL"

    summary = payload["data"]["summary"]
    assert summary["execution_bridge_governance_status"] == "critical"
    assert "SEMANTIC_TOOLCHAIN_VIOLATION" in summary["execution_bridge_governance_reason_codes"]

    governance = payload["data"]["execution_bridge_governance"]
    assert governance["status"] == "critical"
    assert governance["subtask_total"] == 1
    assert governance["subtask_rejected"] == 1
    assert governance["rejection_ratio"] == 1.0

    metrics = payload["data"]["metrics"]
    assert metrics["execution_bridge_rejection_ratio"]["value"] == 1.0
    assert metrics["execution_bridge_governance_warning_ratio"]["value"] == 1.0


def test_ops_incidents_latest_payload_includes_execution_bridge_governance_issue(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path
    events_file = repo_root / "logs" / "autonomous" / "events.jsonl"
    _write_jsonl(
        events_file,
        [
            {
                "timestamp": "2026-02-27T10:00:00+00:00",
                "event_type": "SubTaskRejected",
                "payload": {
                    "task_id": "task-gov-2",
                    "subtask_id": "ops-1",
                    "role": "ops",
                    "error": "execution_bridge_ops_ticket_required",
                    "execution_bridge_governance": {
                        "status": "critical",
                        "severity": "critical",
                        "category": "change_control",
                        "reason_code": "OPS_CHANGE_TICKET_REQUIRED",
                        "reason": "execution_bridge_ops_ticket_required",
                        "executor": "ops",
                        "policy_source": "task.contract_schema.role_executor_policy",
                        "violation_count": 0,
                        "violations": [],
                    },
                },
            }
        ],
    )

    monkeypatch.setattr(api_server, "_ops_repo_root", lambda: repo_root)
    monkeypatch.setattr(api_server, "_ops_collect_required_reports", lambda _repo_root: [])
    from scripts import export_slo_snapshot

    monkeypatch.setattr(export_slo_snapshot, "build_snapshot", lambda **_kwargs: {"metrics": {}})

    payload = api_server._ops_build_incidents_latest_payload(limit=30)
    assert payload["status"] == "success"
    assert payload["severity"] == "critical"
    assert payload["data"]["event_counters"]["ExecutionBridgeGovernanceIssue"] == 1

    summary = payload["data"]["summary"]
    assert summary["execution_bridge_governance"]["status"] == "critical"
    assert summary["runtime_prompt_safety"]["execution_bridge_governance"]["status"] == "critical"

    incidents = payload["data"]["incidents"]
    governance_incidents = [item for item in incidents if str(item.get("event_type")) == "ExecutionBridgeGovernanceIssue"]
    assert len(governance_incidents) == 1
    item = governance_incidents[0]
    assert item["severity"] == "critical"
    assert item["payload_excerpt"]["reason_code"] == "OPS_CHANGE_TICKET_REQUIRED"
    assert item["payload_excerpt"]["category"] == "change_control"


def test_ops_runtime_posture_payload_exposes_prompt_observability_metrics(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path
    ws26_report = repo_root / "scratch" / "reports" / "ws26_runtime_snapshot_ws26_002.json"
    _write_json(
        ws26_report,
        {
            "scenario": "runtime_rollout_fail_open_lease_unified_snapshot",
            "passed": True,
        },
    )

    def _fake_snapshot(*, repo_root: Path, events_limit: int):  # noqa: ARG001
        return {
            "summary": {
                "overall_status": "warning",
                "metric_status": {
                    "readonly_write_tool_exposure_rate": "warning",
                },
            },
            "metrics": {
                "runtime_rollout": {"value": 0.5, "status": "ok"},
                "runtime_fail_open": {"value": 0.1, "status": "ok"},
                "runtime_lease": {"value": 3.0, "status": "warning", "state": "near_expiry"},
                "queue_depth": {"value": 2, "status": "warning"},
                "lock_status": {"state": "near_expiry", "status": "warning"},
                "disk_watermark_ratio": {"value": 0.2, "status": "ok"},
                "error_rate": {"value": 0.02, "status": "ok"},
                "latency_p95_ms": {"value": 260.0, "status": "warning"},
                "prompt_slice_count_by_layer": {"value": 2.1, "status": "ok"},
                "outer_readonly_hit_rate": {"value": 0.4, "status": "ok"},
                "readonly_write_tool_exposure_rate": {
                    "value": 0.03,
                    "sample_count": 20,
                    "exposure_count": 1,
                    "status": "warning",
                },
                "chat_route_path_distribution": {
                    "sample_count": 20,
                    "path_counts": {"path-a": 8, "path-b": 4, "path-c": 8},
                    "path_ratios": {"path-a": 0.4, "path-b": 0.2, "path-c": 0.4},
                    "status": "ok",
                },
                "path_b_budget_escalation_rate": {
                    "value": 0.25,
                    "sample_count": 4,
                    "escalated_count": 1,
                    "status": "ok",
                },
                "core_session_creation_rate": {
                    "value": 0.5,
                    "sample_count": 8,
                    "created_count": 4,
                    "status": "warning",
                },
            },
            "threshold_profile": {"max_error_rate": 0.2},
            "sources": {
                "events_file": "logs/autonomous/events.jsonl",
                "workflow_db": "logs/autonomous/workflow.db",
                "global_mutex_state": "logs/runtime/global_mutex_lease.json",
                "autonomous_config": "autonomous/config/autonomous_config.yaml",
            },
        }

    from scripts import export_slo_snapshot

    monkeypatch.setattr(export_slo_snapshot, "build_snapshot", _fake_snapshot)
    monkeypatch.setattr(api_server, "_ops_repo_root", lambda: repo_root)

    payload = api_server._ops_build_runtime_posture_payload(events_limit=200)
    assert payload["status"] == "success"
    assert payload["severity"] == "warning"

    metrics = payload["data"]["metrics"]
    assert metrics["prompt_slice_count_by_layer"]["value"] == 2.1
    assert metrics["outer_readonly_hit_rate"]["value"] == 0.4
    assert metrics["readonly_write_tool_exposure_rate"]["value"] == 0.03
    assert metrics["readonly_write_tool_exposure_rate"]["sample_count"] == 20
    assert metrics["readonly_write_tool_exposure_rate"]["status"] == "warning"
    assert metrics["chat_route_path_distribution"]["path_ratios"]["path-b"] == 0.2
    assert metrics["path_b_budget_escalation_rate"]["value"] == 0.25
    assert metrics["core_session_creation_rate"]["created_count"] == 4
    assert payload["data"]["summary"]["route_quality"]["status"] == "warning"
    assert "CORE_SESSION_CREATION_WARNING" in payload["data"]["summary"]["route_quality"]["reason_codes"]
    assert payload["data"]["summary"]["route_quality"]["trend"]["status"] == "unknown"
    assert payload["data"]["summary"]["route_quality"]["trend"]["windows"] == []

    assert any(path.endswith("ws26_runtime_snapshot_ws26_002.json") for path in payload["source_reports"])


def test_ops_route_quality_trend_detects_degrading_windows(tmp_path) -> None:
    repo_root = tmp_path
    events_file = repo_root / "logs" / "autonomous" / "events.jsonl"
    base = datetime(2026, 2, 26, 8, 0, tzinfo=timezone.utc)

    rows: list[dict] = []
    for idx in range(20):
        rows.append(
            {
                "timestamp": base.replace(minute=idx % 60, second=idx % 50).isoformat(),
                "event_type": "PromptInjectionComposed",
                "payload": {
                    "path": "path-a",
                    "outer_readonly_hit": True,
                    "readonly_write_tool_exposed": False,
                    "readonly_write_tool_selected_count": 0,
                    "path_b_budget_escalated": False,
                    "core_session_created": False,
                },
            }
        )
    for idx in range(20):
        payload = {
            "path": "path-c",
            "outer_readonly_hit": False,
            "readonly_write_tool_exposed": False,
            "readonly_write_tool_selected_count": 0,
            "path_b_budget_escalated": idx < 8,
            "core_session_created": idx < 6,
        }
        if idx in {2, 4, 7}:
            payload.update(
                {
                    "path": "path-a",
                    "outer_readonly_hit": True,
                    "readonly_write_tool_exposed": True,
                    "readonly_write_tool_selected_count": 1,
                }
            )
        rows.append(
            {
                "timestamp": base.replace(hour=9, minute=idx % 60, second=idx % 50).isoformat(),
                "event_type": "PromptInjectionComposed",
                "payload": payload,
            }
        )

    _write_jsonl(events_file, rows)
    trend = api_server._ops_build_route_quality_trend(events_file, window_size=20, max_windows=2)

    assert trend["status"] in {"warning", "critical"}
    assert trend["direction"] == "degrading"
    assert trend["sample_count"] == 40
    assert trend["window_size"] == 20
    assert isinstance(trend["windows"], list) and len(trend["windows"]) == 2


def test_ops_runtime_posture_payload_brainstem_heartbeat_healthy_signal(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path
    heartbeat_file = repo_root / "scratch" / "runtime" / "brainstem_control_plane_heartbeat_ws23_001.json"
    now = datetime(2026, 2, 26, 12, 0, tzinfo=timezone.utc)
    _write_json(
        heartbeat_file,
        {
            "generated_at": now.isoformat(),
            "pid": 41001,
            "tick": 3,
            "mode": "daemon",
            "healthy": True,
            "service_count": 1,
            "unhealthy_services": [],
            "state_file": str((repo_root / "logs" / "autonomous" / "brainstem_supervisor_state.json").resolve()),
            "spec_file": str((repo_root / "system" / "brainstem_services.spec").resolve()),
        },
    )

    def _fake_snapshot(*, repo_root: Path, events_limit: int):  # noqa: ARG001
        return {
            "summary": {"overall_status": "unknown", "metric_status": {}},
            "metrics": {},
            "threshold_profile": {},
            "sources": {
                "events_file": "logs/autonomous/events.jsonl",
                "workflow_db": "logs/autonomous/workflow.db",
                "global_mutex_state": "logs/runtime/global_mutex_lease.json",
                "autonomous_config": "autonomous/config/autonomous_config.yaml",
            },
        }

    from scripts import export_slo_snapshot

    monkeypatch.setattr(export_slo_snapshot, "build_snapshot", _fake_snapshot)
    monkeypatch.setattr(api_server, "_ops_repo_root", lambda: repo_root)
    monkeypatch.setattr(api_server.time, "time", lambda: now.timestamp() + 10.0)

    payload = api_server._ops_build_runtime_posture_payload(events_limit=200)
    assert payload["status"] == "success"
    assert payload["severity"] == "ok"
    assert payload["data"]["summary"]["overall_status"] == "ok"
    assert payload["data"]["summary"]["brainstem_control_plane_status"] == "ok"

    brainstem = payload["data"]["brainstem_control_plane"]
    assert brainstem["status"] == "ok"
    assert brainstem["healthy"] is True
    assert brainstem["tick"] == 3
    assert isinstance(brainstem["heartbeat_age_seconds"], float)
    assert any(path.endswith("brainstem_control_plane_heartbeat_ws23_001.json") for path in payload["source_reports"])

    brainstem_metric = payload["data"]["metrics"]["brainstem_heartbeat"]
    assert brainstem_metric["status"] == "ok"
    assert brainstem_metric["healthy"] is True
    assert brainstem_metric["tick"] == 3


def test_ops_runtime_posture_payload_escalates_when_brainstem_heartbeat_stale(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path
    heartbeat_file = repo_root / "scratch" / "runtime" / "brainstem_control_plane_heartbeat_ws23_001.json"
    now = datetime(2026, 2, 26, 12, 30, tzinfo=timezone.utc)
    stale = now.replace(hour=11, minute=0)
    _write_json(
        heartbeat_file,
        {
            "generated_at": stale.isoformat(),
            "pid": 41001,
            "tick": 1,
            "mode": "daemon",
            "healthy": True,
            "service_count": 1,
            "unhealthy_services": [],
        },
    )

    def _fake_snapshot(*, repo_root: Path, events_limit: int):  # noqa: ARG001
        return {
            "summary": {"overall_status": "ok", "metric_status": {}},
            "metrics": {},
            "threshold_profile": {},
            "sources": {"events_file": "logs/autonomous/events.jsonl"},
        }

    from scripts import export_slo_snapshot

    monkeypatch.setattr(export_slo_snapshot, "build_snapshot", _fake_snapshot)
    monkeypatch.setattr(api_server, "_ops_repo_root", lambda: repo_root)
    monkeypatch.setattr(api_server.time, "time", lambda: now.timestamp())

    payload = api_server._ops_build_runtime_posture_payload(events_limit=200)
    assert payload["status"] == "success"
    assert payload["severity"] == "critical"
    assert payload["reason_code"] == "BRAINSTEM_CONTROL_PLANE_CRITICAL"
    assert payload["data"]["summary"]["overall_status"] == "critical"

    brainstem = payload["data"]["brainstem_control_plane"]
    assert brainstem["status"] == "critical"
    assert brainstem["reason_code"] == "BRAINSTEM_HEARTBEAT_STALE_CRITICAL"


def test_ops_runtime_posture_payload_includes_watchdog_daemon_signal(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path
    now = datetime(2026, 2, 26, 12, 0, tzinfo=timezone.utc)
    watchdog_state_file = repo_root / "scratch" / "runtime" / "watchdog_daemon_state_ws28_025.json"
    _write_json(
        watchdog_state_file,
        {
            "generated_at": now.isoformat(),
            "pid": 52001,
            "tick": 4,
            "mode": "daemon",
            "warn_only": False,
            "threshold_hit": True,
            "status": "warning",
            "snapshot": {"cpu_percent": 89.0},
            "action": {
                "level": "warn",
                "action": "throttle_new_workloads",
                "reasons": ["cpu_percent=89.00>=85.00"],
                "snapshot": {"cpu_percent": 89.0},
            },
        },
    )

    def _fake_snapshot(*, repo_root: Path, events_limit: int):  # noqa: ARG001
        return {
            "summary": {"overall_status": "ok", "metric_status": {}},
            "metrics": {},
            "threshold_profile": {},
            "sources": {"events_file": "logs/autonomous/events.jsonl"},
        }

    from scripts import export_slo_snapshot

    monkeypatch.setattr(export_slo_snapshot, "build_snapshot", _fake_snapshot)
    monkeypatch.setattr(api_server, "_ops_repo_root", lambda: repo_root)
    monkeypatch.setattr(api_server.time, "time", lambda: now.timestamp() + 5.0)

    payload = api_server._ops_build_runtime_posture_payload(events_limit=200)
    assert payload["status"] == "success"
    assert payload["severity"] == "warning"
    assert payload["reason_code"] == "WATCHDOG_DAEMON_WARNING"
    assert payload["data"]["summary"]["watchdog_daemon_status"] == "warning"

    watchdog = payload["data"]["watchdog_daemon"]
    assert watchdog["status"] == "warning"
    assert watchdog["reason_code"] == "WATCHDOG_DAEMON_THRESHOLD_WARNING"
    assert watchdog["tick"] == 4
    assert watchdog["threshold_hit"] is True
    assert any(path.endswith("watchdog_daemon_state_ws28_025.json") for path in payload["source_reports"])

    watchdog_metric = payload["data"]["metrics"]["watchdog_daemon"]
    assert watchdog_metric["status"] == "warning"
    assert watchdog_metric["tick"] == 4
