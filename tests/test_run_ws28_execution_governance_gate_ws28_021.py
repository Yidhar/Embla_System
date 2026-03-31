from __future__ import annotations

import json
import shutil
import uuid
import hashlib
from pathlib import Path

from core.security import AuditLedger

import scripts.run_ws28_execution_governance_gate_ws28_021 as ws28_gate


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_semantic_guard_spec(repo_root: Path) -> Path:
    spec_path = repo_root / "policy" / "role_executor_semantic_guard.spec"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(
        json.dumps(
            {
                "schema_version": "ws28-role-executor-semantic-guard-v1",
                "roles": {
                    "frontend": {"allowed_semantic_toolchains": ["frontend", "docs", "config"]},
                    "backend": {"allowed_semantic_toolchains": ["backend", "docs", "config", "ops"]},
                    "ops": {"allowed_semantic_toolchains": ["ops", "docs", "config"]},
                },
                "change_control": {
                    "schema_version": "ws28-role-executor-semantic-guard-change-control-v1",
                    "approval_ticket_required": True,
                    "audit_ledger": "doc/task/reports/role_executor_semantic_guard_change_ledger_ws28_021.jsonl",
                    "acl": {
                        "owners": ["AG-PH3-BS-01"],
                        "approvers": ["release-owner", "security-reviewer"],
                        "min_approvals": 1,
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    sha256 = hashlib.sha256(spec_path.read_bytes()).hexdigest()
    ledger_path = repo_root / "doc/task/reports/role_executor_semantic_guard_change_ledger_ws28_021.jsonl"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger = AuditLedger(ledger_file=ledger_path)
    ledger.append_record(
        record_type="spec_change_registered",
        change_id="ws28_021_test_baseline",
        scope="policy",
        risk_level="high",
        requested_by="qa-bot",
        approved_by="qa-bot",
        approval_ticket="CAB-WS28-021-TEST",
        payload={
            "event_type": "spec_change_registered",
            "spec_sha256": sha256,
            "changed_by": "qa-bot",
        },
    )
    return spec_path


def test_run_ws28_execution_governance_gate_passes_when_within_budget(monkeypatch) -> None:
    case_root = _make_case_root("test_run_ws28_execution_governance_gate_ws28_021")
    try:
        repo_root = case_root / "repo"
        repo_root.mkdir(parents=True, exist_ok=True)
        _write_semantic_guard_spec(repo_root)

        from apiserver import routes_ops

        monkeypatch.setattr(
            routes_ops,
            "_ops_build_runtime_posture_payload",
            lambda events_limit=5000: {
                "status": "success",
                "data": {
                    "summary": {"execution_bridge_governance_status": "warning"},
                    "execution_bridge_governance": {
                        "status": "warning",
                        "reason_codes": ["ROLE_EXECUTOR_GUARD_WARNING"],
                        "governed_warning_ratio": 0.2,
                        "rejection_ratio": 0.1,
                    },
                },
            },
        )
        monkeypatch.setattr(
            routes_ops,
            "_ops_build_incidents_latest_payload",
            lambda limit=50: {
                "status": "success",
                "data": {
                    "summary": {
                        "execution_bridge_governance": {
                            "status": "warning",
                            "governed_critical_count": 0,
                        }
                    }
                },
            },
        )

        output_file = repo_root / "scratch" / "reports" / "ws28_gate.json"
        runtime_output = repo_root / "scratch" / "reports" / "runtime_posture.json"
        incidents_output = repo_root / "scratch" / "reports" / "incidents.json"
        report = ws28_gate.run_ws28_execution_governance_gate_ws28_021(
            repo_root=repo_root,
            output_file=output_file.relative_to(repo_root),
            runtime_posture_output=runtime_output.relative_to(repo_root),
            incidents_output=incidents_output.relative_to(repo_root),
            max_warning_ratio=0.3,
            max_rejection_ratio=0.2,
        )

        assert report["passed"] is True
        assert report["checks"]["runtime_posture_payload_success"] is True
        assert report["checks"]["incidents_payload_success"] is True
        assert report["checks"]["runtime_governance_status_not_critical"] is True
        assert report["checks"]["critical_governance_issue_count_zero"] is True
        assert report["checks"]["semantic_guard_spec_exists"] is True
        assert report["checks"]["semantic_guard_spec_schema_valid"] is True
        assert report["checks"]["semantic_guard_spec_roles_ready"] is True
        assert report["checks"]["semantic_guard_change_control_ready"] is True
        assert report["checks"]["semantic_guard_change_control_ledger_exists"] is True
        assert report["checks"]["semantic_guard_change_control_ledger_chain_valid"] is True
        assert report["checks"]["semantic_guard_change_control_latest_event_valid"] is True
        assert report["checks"]["semantic_guard_change_control_latest_sha_match"] is True
        assert output_file.exists() is True
        assert runtime_output.exists() is True
        assert incidents_output.exists() is True

        persisted = _read_json(output_file)
        assert persisted["passed"] is True
        assert persisted["governance"]["warning_ratio"] == 0.2
        assert persisted["governance"]["rejection_ratio"] == 0.1
        assert persisted["semantic_guard_spec"]["schema_version"] == "ws28-role-executor-semantic-guard-v1"
        assert bool(persisted["semantic_guard_spec"]["sha256"])
        assert persisted["semantic_guard_spec"]["change_control"]["approval_ticket_required"] is True
        assert persisted["semantic_guard_spec"]["change_control"]["latest_event"]["approval_ticket_present"] is True
    finally:
        _cleanup_case_root(case_root)


def test_run_ws28_execution_governance_gate_fails_when_critical_present(monkeypatch) -> None:
    case_root = _make_case_root("test_run_ws28_execution_governance_gate_ws28_021")
    try:
        repo_root = case_root / "repo"
        repo_root.mkdir(parents=True, exist_ok=True)
        _write_semantic_guard_spec(repo_root)

        from apiserver import routes_ops

        monkeypatch.setattr(
            routes_ops,
            "_ops_build_runtime_posture_payload",
            lambda events_limit=5000: {
                "status": "success",
                "data": {
                    "summary": {"execution_bridge_governance_status": "critical"},
                    "execution_bridge_governance": {
                        "status": "critical",
                        "reason_codes": ["SEMANTIC_TOOLCHAIN_VIOLATION"],
                        "governed_warning_ratio": 0.7,
                        "rejection_ratio": 0.5,
                    },
                },
            },
        )
        monkeypatch.setattr(
            routes_ops,
            "_ops_build_incidents_latest_payload",
            lambda limit=50: {
                "status": "success",
                "data": {
                    "summary": {
                        "execution_bridge_governance": {
                            "status": "critical",
                            "governed_critical_count": 2,
                        }
                    }
                },
            },
        )

        report = ws28_gate.run_ws28_execution_governance_gate_ws28_021(
            repo_root=repo_root,
            output_file=Path("scratch/reports/ws28_gate_fail.json"),
            runtime_posture_output=Path("scratch/reports/runtime_posture_fail.json"),
            incidents_output=Path("scratch/reports/incidents_fail.json"),
            max_warning_ratio=0.3,
            max_rejection_ratio=0.2,
        )

        assert report["passed"] is False
        failed_checks = set(report["failed_checks"])
        assert "runtime_governance_status_not_critical" in failed_checks
        assert "incidents_governance_status_not_critical" in failed_checks
        assert "critical_governance_issue_count_zero" in failed_checks
        assert "governance_warning_ratio_within_budget" in failed_checks
        assert "governance_rejection_ratio_within_budget" in failed_checks
        assert "semantic_guard_spec_exists" not in failed_checks
        assert "semantic_guard_spec_schema_valid" not in failed_checks
        assert "semantic_guard_spec_roles_ready" not in failed_checks
        assert "semantic_guard_change_control_ready" not in failed_checks
        assert "semantic_guard_change_control_ledger_exists" not in failed_checks
        assert "semantic_guard_change_control_ledger_chain_valid" not in failed_checks
        assert "semantic_guard_change_control_latest_event_valid" not in failed_checks
        assert "semantic_guard_change_control_latest_sha_match" not in failed_checks
    finally:
        _cleanup_case_root(case_root)


def test_run_ws28_execution_governance_gate_fails_when_semantic_spec_missing(monkeypatch) -> None:
    case_root = _make_case_root("test_run_ws28_execution_governance_gate_ws28_021")
    try:
        repo_root = case_root / "repo"
        repo_root.mkdir(parents=True, exist_ok=True)

        from apiserver import routes_ops

        monkeypatch.setattr(
            routes_ops,
            "_ops_build_runtime_posture_payload",
            lambda events_limit=5000: {
                "status": "success",
                "data": {
                    "summary": {"execution_bridge_governance_status": "ok"},
                    "execution_bridge_governance": {
                        "status": "ok",
                        "reason_codes": ["EXECUTION_BRIDGE_GOVERNANCE_OK"],
                        "governed_warning_ratio": 0.0,
                        "rejection_ratio": 0.0,
                    },
                },
            },
        )
        monkeypatch.setattr(
            routes_ops,
            "_ops_build_incidents_latest_payload",
            lambda limit=50: {
                "status": "success",
                "data": {
                    "summary": {
                        "execution_bridge_governance": {
                            "status": "ok",
                            "governed_critical_count": 0,
                        }
                    }
                },
            },
        )

        report = ws28_gate.run_ws28_execution_governance_gate_ws28_021(
            repo_root=repo_root,
            output_file=Path("scratch/reports/ws28_gate_spec_missing.json"),
            runtime_posture_output=Path("scratch/reports/runtime_posture_spec_missing.json"),
            incidents_output=Path("scratch/reports/incidents_spec_missing.json"),
            max_warning_ratio=0.3,
            max_rejection_ratio=0.2,
        )

        assert report["passed"] is False
        failed_checks = set(report["failed_checks"])
        assert "semantic_guard_spec_exists" in failed_checks
        assert "semantic_guard_spec_schema_valid" in failed_checks
        assert "semantic_guard_spec_roles_ready" in failed_checks
        assert "semantic_guard_change_control_ready" in failed_checks
        assert "semantic_guard_change_control_ledger_exists" in failed_checks
        assert "semantic_guard_change_control_ledger_chain_valid" in failed_checks
        assert "semantic_guard_change_control_latest_event_valid" in failed_checks
        assert "semantic_guard_change_control_latest_sha_match" in failed_checks
        assert report["semantic_guard_spec"]["failed_reasons"] == ["semantic_guard_spec_missing"]
    finally:
        _cleanup_case_root(case_root)
