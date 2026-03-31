from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path

import scripts.register_role_executor_semantic_guard_change_ws28_021 as ws28_register


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _write_spec(repo_root: Path) -> Path:
    spec_path = repo_root / "policy" / "role_executor_semantic_guard.spec"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(
        json.dumps(
            {
                "schema_version": "ws28-role-executor-semantic-guard-v1",
                "roles": {
                    "frontend": {"allowed_semantic_toolchains": ["frontend"]},
                    "backend": {"allowed_semantic_toolchains": ["backend"]},
                    "ops": {"allowed_semantic_toolchains": ["ops"]},
                },
                "change_control": {
                    "schema_version": "ws28-role-executor-semantic-guard-change-control-v1",
                    "approval_ticket_required": True,
                    "audit_ledger": "doc/task/reports/role_executor_semantic_guard_change_ledger_ws28_021.jsonl",
                    "acl": {
                        "owners": ["AG-PH3-BS-01"],
                        "approvers": ["release-owner"],
                        "min_approvals": 1,
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return spec_path


def test_register_semantic_guard_change_writes_audit_ledger_event() -> None:
    case_root = _make_case_root("test_register_role_executor_semantic_guard_change_ws28_021")
    try:
        repo_root = case_root / "repo"
        spec_path = _write_spec(repo_root)
        output = repo_root / "scratch" / "reports" / "register.json"

        report = ws28_register.run_register_role_executor_semantic_guard_change_ws28_021(
            repo_root=repo_root,
            approval_ticket="CAB-WS28-021-LOCAL",
            changed_by="release-bot",
            notes="test register",
            output_file=output.relative_to(repo_root),
        )

        assert report["passed"] is True
        assert report["checks"]["ledger_event_written"] is True
        assert report["checks"]["approval_gate_passed"] is True
        assert report["checks"]["ledger_hash_chain_verified"] is True
        assert report["spec_sha256"] == hashlib.sha256(spec_path.read_bytes()).hexdigest()
        assert output.exists() is True

        ledger = repo_root / "doc/task/reports/role_executor_semantic_guard_change_ledger_ws28_021.jsonl"
        assert ledger.exists() is True
        line = ledger.read_text(encoding="utf-8").strip().splitlines()[-1]
        event = json.loads(line)
        assert event["approval_ticket"] == "CAB-WS28-021-LOCAL"
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        assert payload["spec_sha256"] == report["spec_sha256"]
        assert event["ledger_hash"]
        assert event["prev_ledger_hash"]
    finally:
        _cleanup_case_root(case_root)


def test_register_semantic_guard_change_rejects_missing_ticket_when_required() -> None:
    case_root = _make_case_root("test_register_role_executor_semantic_guard_change_ws28_021")
    try:
        repo_root = case_root / "repo"
        _write_spec(repo_root)

        report = ws28_register.run_register_role_executor_semantic_guard_change_ws28_021(
            repo_root=repo_root,
            approval_ticket="",
            changed_by="release-bot",
            notes="missing ticket",
            output_file=Path("scratch/reports/register_missing_ticket.json"),
        )

        assert report["passed"] is False
        assert "approval_ticket_present" in set(report["failed_checks"])
        assert "approval_gate_passed" in set(report["failed_checks"])
        assert report["checks"]["ledger_event_written"] is False
    finally:
        _cleanup_case_root(case_root)
