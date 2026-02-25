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

