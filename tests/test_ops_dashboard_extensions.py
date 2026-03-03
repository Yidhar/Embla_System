from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import apiserver.api_server
from apiserver import routes_ops as api_server
from core.security import AuditLedger


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
    path.write_text(content, encoding="utf-8")


def _write_topic_events_db(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS topic_event (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                topic TEXT NOT NULL,
                event_type TEXT NOT NULL,
                source TEXT NOT NULL,
                severity TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                partition_ym TEXT NOT NULL DEFAULT '',
                envelope_json TEXT NOT NULL
            );
            """
        )
        for idx, row in enumerate(rows, start=1):
            envelope = {
                "event_id": str(row.get("event_id") or f"evt-{idx:04d}"),
                "timestamp": str(row.get("timestamp") or ""),
                "event_type": str(row.get("event_type") or ""),
                "topic": str(row.get("topic") or ""),
                "data": row.get("payload") if isinstance(row.get("payload"), dict) else {},
            }
            timestamp = str(row.get("timestamp") or "")
            partition_ym = str(row.get("partition_ym") or timestamp[:7].replace("-", ""))
            conn.execute(
                """
                INSERT INTO topic_event
                (event_id, topic, event_type, source, severity, idempotency_key, timestamp, partition_ym, envelope_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(row.get("event_id") or f"evt-{idx:04d}"),
                    str(row.get("topic") or ""),
                    str(row.get("event_type") or ""),
                    "test",
                    "info",
                    str(row.get("event_id") or f"idem-{idx:04d}"),
                    timestamp,
                    partition_ym,
                    json.dumps(envelope, ensure_ascii=False),
                ),
            )
        conn.commit()
    finally:
        conn.close()


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
            "scenario": "subagent_full_cutover_and_rollback_window",
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


def test_ops_workflow_events_payload_includes_event_database_summary(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path
    events_file = repo_root / "logs" / "autonomous" / "events.jsonl"
    events_db = events_file.with_name("events_topics.db")
    _write_topic_events_db(
        events_db,
        [
            {
                "event_id": "evt-db-001",
                "timestamp": "2026-03-01T06:00:00+00:00",
                "event_type": "LeaseLost",
                "topic": "mutex.lease.lost",
                "partition_ym": "202603",
                "payload": {"owner_id": "runner-a"},
            },
            {
                "event_id": "evt-db-002",
                "timestamp": "2026-03-01T06:05:00+00:00",
                "event_type": "SubAgentRuntimeFailOpen",
                "topic": "agent.runtime.failopen",
                "partition_ym": "202603",
                "payload": {"runtime_id": "sar-001"},
            },
            {
                "event_id": "evt-db-003",
                "timestamp": "2026-02-28T18:10:00+00:00",
                "event_type": "PromptInjectionComposed",
                "topic": "evolution.prompt.compose",
                "partition_ym": "202602",
                "payload": {"path": "path-c"},
            },
        ],
    )

    def _fake_snapshot(*, repo_root: Path, events_limit: int):  # noqa: ARG001
        return {
            "summary": {"overall_status": "ok"},
            "metrics": {"queue_depth": {"status": "ok", "value": 0}},
            "sources": {
                "events_file": str(events_file),
                "events_db": str(events_db),
                "workflow_db": str(repo_root / "logs" / "autonomous" / "workflow.db"),
            },
        }

    monkeypatch.setattr(api_server, "_ops_repo_root", lambda: repo_root)
    from scripts import export_slo_snapshot

    monkeypatch.setattr(export_slo_snapshot, "build_snapshot", _fake_snapshot)
    payload = api_server._ops_build_workflow_events_payload(events_limit=200, recent_critical_limit=20)

    assert payload["status"] == "success"
    assert payload["severity"] == "warning"
    summary = payload["data"]["summary"]
    assert summary["event_db_rows"] == 3
    assert summary["event_db_partitions"] == 2
    assert summary["event_db_status"] == "ok"
    assert summary["event_db_latest_at"] == "2026-03-01T06:05:00+00:00"

    event_db = payload["data"]["event_database"]
    assert event_db["exists"] is True
    assert event_db["total_rows"] == 3
    assert event_db["partition_count"] == 2
    assert event_db["latest_event_type"] == "SubAgentRuntimeFailOpen"
    assert event_db["latest_topic"] == "agent.runtime.failopen"
    assert len(event_db["partitions"]) == 2
    assert event_db["partitions"][0]["partition_ym"] == "202603"
    assert event_db["partitions"][0]["row_count"] == 2
    assert len(event_db["top_topics"]) >= 1
    assert any(path.endswith("events_topics.db") for path in payload["source_reports"])


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


def test_ops_runtime_posture_payload_includes_agentic_loop_completion_summary(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path
    events_file = repo_root / "logs" / "autonomous" / "events.jsonl"
    _write_jsonl(
        events_file,
        [
            {
                "timestamp": "2026-03-01T02:00:00+00:00",
                "event_type": "AgenticLoopCompletionSubmitted",
                "payload": {"session_id": "sess-ok-1", "reason": "submitted_completion"},
            },
            {
                "timestamp": "2026-03-01T02:05:00+00:00",
                "event_type": "AgenticLoopCompletionNotSubmitted",
                "payload": {"session_id": "sess-fail-1", "reason": "completion_not_submitted"},
            },
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
    assert payload["reason_code"] == "AGENTIC_LOOP_COMPLETION_CRITICAL"
    assert payload["data"]["summary"]["agentic_loop_completion_status"] == "critical"

    completion = payload["data"]["agentic_loop_completion"]
    assert completion["submitted_count"] == 1
    assert completion["not_submitted_count"] == 1
    assert completion["total_count"] == 2
    assert completion["reason_code"] == "AGENTIC_LOOP_COMPLETION_NOT_SUBMITTED_PRESENT"

    metric = payload["data"]["metrics"]["agentic_loop_completion_not_submitted_ratio"]
    assert metric["status"] == "critical"
    assert metric["submitted_count"] == 1
    assert metric["not_submitted_count"] == 1
    assert metric["total_count"] == 2


def test_ops_runtime_posture_payload_includes_immutable_dna_preflight(monkeypatch, tmp_path) -> None:
    repo_root = tmp_path

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

    previous_preflight = getattr(api_server.app.state, "immutable_dna_preflight", None)
    api_server.app.state.immutable_dna_preflight = {
        "enabled": True,
        "required": True,
        "passed": True,
        "reason": "ok",
        "manifest_path": str(repo_root / "system" / "prompts" / "immutable_dna_manifest.spec"),
        "audit_file": str(repo_root / "scratch" / "reports" / "immutable_dna_runtime_injection_audit.jsonl"),
        "manifest_hash": "abc123",
        "verify": {"ok": True, "reason": "ok"},
    }
    try:
        payload = api_server._ops_build_runtime_posture_payload(events_limit=200)
    finally:
        if previous_preflight is None:
            try:
                delattr(api_server.app.state, "immutable_dna_preflight")
            except AttributeError:
                pass
        else:
            api_server.app.state.immutable_dna_preflight = previous_preflight

    assert payload["status"] == "success"
    assert payload["data"]["summary"]["immutable_dna_status"] == "ok"
    immutable_dna = payload["data"]["immutable_dna"]
    assert immutable_dna["passed"] is True
    assert immutable_dna["status"] == "ok"
    assert payload["data"]["metrics"]["immutable_dna"]["manifest_hash"] == "abc123"


def test_ops_runtime_posture_payload_marks_immutable_dna_failure_as_critical(monkeypatch, tmp_path) -> None:
    repo_root = tmp_path

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

    previous_preflight = getattr(api_server.app.state, "immutable_dna_preflight", None)
    api_server.app.state.immutable_dna_preflight = {
        "enabled": True,
        "required": True,
        "passed": False,
        "reason": "dna_hash_mismatch",
        "manifest_path": str(repo_root / "system" / "prompts" / "immutable_dna_manifest.spec"),
        "audit_file": str(repo_root / "scratch" / "reports" / "immutable_dna_runtime_injection_audit.jsonl"),
        "verify": {"ok": False, "reason": "dna_hash_mismatch"},
    }
    try:
        payload = api_server._ops_build_runtime_posture_payload(events_limit=200)
    finally:
        if previous_preflight is None:
            try:
                delattr(api_server.app.state, "immutable_dna_preflight")
            except AttributeError:
                pass
        else:
            api_server.app.state.immutable_dna_preflight = previous_preflight

    assert payload["status"] == "success"
    assert payload["severity"] == "critical"
    assert payload["reason_code"] == "IMMUTABLE_DNA_CRITICAL"
    assert payload["data"]["summary"]["immutable_dna_status"] == "critical"
    immutable_dna = payload["data"]["immutable_dna"]
    assert immutable_dna["passed"] is False
    assert immutable_dna["reason_code"] == "IMMUTABLE_DNA_PREFLIGHT_FAILED"


def test_ops_runtime_posture_payload_includes_audit_ledger_summary(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path

    def _fake_snapshot(*, repo_root: Path, events_limit: int):  # noqa: ARG001
        return {
            "summary": {"overall_status": "ok", "metric_status": {}},
            "metrics": {},
            "threshold_profile": {},
            "sources": {"events_file": "logs/autonomous/events.jsonl"},
        }

    ledger_path = repo_root / "scratch" / "runtime" / "audit_ledger.jsonl"
    ledger = AuditLedger(ledger_file=ledger_path, signing_key="test-signing-key")
    ledger.append_record(
        record_type="change_promoted",
        change_id="chg_ops_001",
        scope="policy",
        risk_level="high",
        requested_by="qa-bot",
        approved_by="release-owner",
        approval_ticket="CAB-OPS-001",
        payload={"summary": "runtime posture ledger smoke"},
    )

    from scripts import export_slo_snapshot

    monkeypatch.setattr(export_slo_snapshot, "build_snapshot", _fake_snapshot)
    monkeypatch.setattr(api_server, "_ops_repo_root", lambda: repo_root)

    payload = api_server._ops_build_runtime_posture_payload(events_limit=200)
    assert payload["status"] == "success"
    assert payload["data"]["summary"]["audit_ledger_status"] == "ok"

    audit_ledger = payload["data"]["audit_ledger"]
    assert audit_ledger["status"] == "ok"
    assert audit_ledger["checked_count"] == 1
    assert audit_ledger["error_count"] == 0
    assert audit_ledger["latest_change_id"] == "chg_ops_001"

    metric = payload["data"]["metrics"]["audit_ledger"]
    assert metric["status"] == "ok"
    assert metric["value"] == 1
    assert metric["error_count"] == 0
    assert metric["reason_code"] == "OK"
    assert any(path.endswith("scratch/runtime/audit_ledger.jsonl") for path in payload["source_reports"])


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


def test_ops_incidents_latest_payload_includes_agentic_loop_completion_not_submitted(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path
    events_file = repo_root / "logs" / "autonomous" / "events.jsonl"
    _write_jsonl(
        events_file,
        [
            {
                "timestamp": "2026-03-01T03:00:00+00:00",
                "event_type": "AgenticLoopCompletionNotSubmitted",
                "payload": {"session_id": "sess-loop-001", "reason": "completion_not_submitted"},
            }
        ],
    )

    monkeypatch.setattr(api_server, "_ops_repo_root", lambda: repo_root)
    monkeypatch.setattr(api_server, "_ops_collect_required_reports", lambda _repo_root: [])
    from scripts import export_slo_snapshot

    monkeypatch.setattr(export_slo_snapshot, "build_snapshot", lambda **_kwargs: {"metrics": {}})

    payload = api_server._ops_build_incidents_latest_payload(limit=20)
    assert payload["status"] == "success"
    assert payload["severity"] == "critical"
    assert payload["data"]["event_counters"]["AgenticLoopCompletionNotSubmitted"] == 1

    summary = payload["data"]["summary"]
    prompt_safety = summary["runtime_prompt_safety"]
    assert prompt_safety["agentic_loop_completion"]["status"] == "critical"
    assert prompt_safety["agentic_loop_completion"]["reason_code"] == "AGENTIC_LOOP_COMPLETION_NOT_SUBMITTED_PRESENT"

    incidents = payload["data"]["incidents"]
    completion_incidents = [
        item for item in incidents if str(item.get("event_type")) == "AgenticLoopCompletionNotSubmitted"
    ]
    assert len(completion_incidents) == 1
    item = completion_incidents[0]
    assert item["severity"] == "critical"
    assert item["payload_excerpt"]["session_id"] == "sess-loop-001"


def test_ops_runtime_posture_payload_includes_control_plane_guard_summaries(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path
    now_iso = datetime.now(timezone.utc).isoformat()
    _write_json(
        repo_root / "scratch" / "runtime" / "process_guard_state_ws28_028.json",
        {
            "generated_at": now_iso,
            "status": "warning",
            "reason_code": "PROCESS_GUARD_ORPHAN_REAPED",
            "reason_text": "orphan jobs reaped",
            "running_jobs": 2,
            "orphan_jobs": 1,
            "stale_jobs": 0,
            "orphan_reaped_count": 1,
        },
    )
    _write_json(
        repo_root / "scratch" / "runtime" / "killswitch_guard_state_ws28_028.json",
        {
            "generated_at": now_iso,
            "status": "critical",
            "reason_code": "KILLSWITCH_ENGAGED",
            "reason_text": "KillSwitch is active",
            "active": True,
            "mode": "freeze_with_oob_allowlist",
            "commands_count": 8,
        },
    )
    _write_json(
        repo_root / "scratch" / "runtime" / "budget_guard_state_ws28_028.json",
        {
            "generated_at": now_iso,
            "status": "warning",
            "reason_code": "DAILY_COST_LIMIT_EXCEEDED",
            "reason_text": "budget guard triggered",
            "action": "freeze_noncritical_budget",
            "task_id": "task-bgt-1",
            "tool_name": "run_cmd",
            "details": {"daily_cost": 10.0},
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

    payload = api_server._ops_build_runtime_posture_payload(events_limit=200)
    assert payload["status"] == "success"
    assert payload["severity"] == "critical"
    assert payload["reason_code"] == "KILLSWITCH_GUARD_CRITICAL"

    summary = payload["data"]["summary"]
    assert summary["process_guard_status"] == "warning"
    assert summary["killswitch_guard_status"] == "critical"
    assert summary["budget_guard_status"] == "warning"

    assert payload["data"]["process_guard"]["orphan_reaped_count"] == 1
    assert payload["data"]["killswitch_guard"]["active"] is True
    assert payload["data"]["budget_guard"]["action"] == "freeze_noncritical_budget"


def test_ops_runtime_posture_payload_marks_legacy_autonomous_disabled(monkeypatch, tmp_path) -> None:
    repo_root = tmp_path

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
    monkeypatch.setattr(
        "system.config.get_config",
        lambda: SimpleNamespace(autonomous=SimpleNamespace(legacy_system_agent_enabled=False)),
    )

    payload = api_server._ops_build_runtime_posture_payload(events_limit=200)
    assert payload["status"] == "success"

    summary = payload["data"]["summary"]
    assert summary["control_plane_mode"] == "single_control_plane"
    assert summary["single_control_plane"] is True
    assert summary["legacy_autonomous_status"] == "disabled"
    assert summary["legacy_autonomous"] == "disabled"

    control_plane_mode = payload["data"]["control_plane_mode"]
    assert control_plane_mode["runtime_mode"] == "single_control_plane"
    assert control_plane_mode["reason_code"] == "LEGACY_AUTONOMOUS_DISABLED"
    assert control_plane_mode["legacy_autonomous"] == "disabled"

    metric = payload["data"]["metrics"]["control_plane_mode"]
    assert metric["status"] == "ok"
    assert metric["value"] == 0
    assert metric["legacy_autonomous"] == "disabled"


def test_ops_incidents_latest_payload_includes_control_plane_guard_incidents(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path
    now_iso = datetime.now(timezone.utc).isoformat()
    _write_json(
        repo_root / "scratch" / "runtime" / "process_guard_state_ws28_028.json",
        {
            "generated_at": now_iso,
            "status": "critical",
            "reason_code": "PROCESS_GUARD_ORPHAN_RUNNING_JOBS",
            "reason_text": "orphan jobs still running",
            "running_jobs": 3,
            "orphan_jobs": 2,
            "stale_jobs": 0,
            "orphan_reaped_count": 0,
        },
    )
    _write_json(
        repo_root / "scratch" / "runtime" / "killswitch_guard_state_ws28_028.json",
        {
            "generated_at": now_iso,
            "status": "critical",
            "reason_code": "KILLSWITCH_ENGAGED",
            "reason_text": "KillSwitch is active",
            "active": True,
            "mode": "freeze_with_oob_allowlist",
            "commands_count": 8,
        },
    )
    _write_json(
        repo_root / "scratch" / "runtime" / "budget_guard_state_ws28_028.json",
        {
            "generated_at": now_iso,
            "status": "critical",
            "reason_code": "TASK_COST_LIMIT_EXCEEDED",
            "reason_text": "budget guard triggered",
            "action": "terminate_task_budget_exceeded",
            "task_id": "task-bgt-2",
            "tool_name": "python_repl",
            "details": {"task_cost": 5.6},
        },
    )

    monkeypatch.setattr(api_server, "_ops_repo_root", lambda: repo_root)
    monkeypatch.setattr(api_server, "_ops_collect_required_reports", lambda _repo_root: [])
    from scripts import export_slo_snapshot

    monkeypatch.setattr(export_slo_snapshot, "build_snapshot", lambda **_kwargs: {"metrics": {}})

    payload = api_server._ops_build_incidents_latest_payload(limit=30)
    assert payload["status"] == "success"
    assert payload["severity"] == "critical"
    counters = payload["data"]["event_counters"]
    assert counters["ProcessGuardZombieDetected"] == 1
    assert counters["KillSwitchEngaged"] == 1
    assert counters["BudgetGuardTriggered"] == 1

    incidents = payload["data"]["incidents"]
    assert any(str(item.get("event_type")) == "ProcessGuardZombieDetected" for item in incidents)
    assert any(str(item.get("event_type")) == "KillSwitchEngaged" for item in incidents)
    assert any(str(item.get("event_type")) == "BudgetGuardTriggered" for item in incidents)


def test_ops_incidents_latest_payload_includes_audit_ledger_chain_invalid(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path
    ledger_path = repo_root / "scratch" / "runtime" / "audit_ledger.jsonl"
    ledger = AuditLedger(ledger_file=ledger_path)
    ledger.append_record(
        record_type="change_promoted",
        change_id="chg_audit_ok_001",
        scope="policy",
        risk_level="high",
        requested_by="qa-bot",
        approval_ticket="CAB-001",
        payload={"step": "before tamper"},
    )
    ledger.append_record(
        record_type="change_promoted",
        change_id="chg_audit_ok_002",
        scope="policy",
        risk_level="high",
        requested_by="qa-bot",
        approval_ticket="CAB-002",
        payload={"step": "will tamper"},
    )

    rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows[-1]["change_id"] = "chg_audit_tampered_999"
    ledger_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(api_server, "_ops_repo_root", lambda: repo_root)
    monkeypatch.setattr(api_server, "_ops_collect_required_reports", lambda _repo_root: [])
    from scripts import export_slo_snapshot

    monkeypatch.setattr(export_slo_snapshot, "build_snapshot", lambda **_kwargs: {"metrics": {}})

    payload = api_server._ops_build_incidents_latest_payload(limit=20)
    assert payload["status"] == "success"
    assert payload["severity"] == "critical"
    assert payload["data"]["event_counters"]["AuditLedgerChainInvalid"] == 1

    incidents = payload["data"]["incidents"]
    audit_incidents = [item for item in incidents if str(item.get("event_type")) == "AuditLedgerChainInvalid"]
    assert len(audit_incidents) == 1
    incident = audit_incidents[0]
    assert incident["severity"] == "critical"
    assert incident["payload_excerpt"]["reason_code"] == "AUDIT_LEDGER_CHAIN_INVALID"
    assert incident["payload_excerpt"]["error_count"] >= 1
    assert str(incident["report_path"]).endswith("scratch/runtime/audit_ledger.jsonl")


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
