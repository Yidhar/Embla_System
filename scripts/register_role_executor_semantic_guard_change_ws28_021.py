#!/usr/bin/env python3
"""Register audited change records for role_executor_semantic_guard.spec."""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from autonomous.tools.execution_bridge import DEFAULT_ROLE_EXECUTOR_SEMANTIC_GUARD_SPEC


DEFAULT_OUTPUT = Path("scratch/reports/ws28_role_executor_semantic_guard_change_register.json")


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _to_repo_relative_path(path: Path, *, repo_root: Path) -> str:
    try:
        return _to_unix_path(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return _to_unix_path(path)


def _resolve_path(repo_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_register_role_executor_semantic_guard_change_ws28_021(
    *,
    repo_root: Path,
    spec_file: Path = DEFAULT_ROLE_EXECUTOR_SEMANTIC_GUARD_SPEC,
    approval_ticket: str,
    changed_by: str,
    notes: str = "",
    output_file: Path = DEFAULT_OUTPUT,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    spec_path = _resolve_path(root, spec_file)
    output_path = _resolve_path(root, output_file)
    payload = _read_json(spec_path)

    checks = {
        "spec_exists": spec_path.exists(),
        "change_control_exists": False,
        "change_control_acl_ready": False,
        "approval_ticket_present": bool(str(approval_ticket or "").strip()),
        "ledger_event_written": False,
    }
    failed_checks = []

    change_control = payload.get("change_control") if isinstance(payload.get("change_control"), dict) else {}
    checks["change_control_exists"] = isinstance(change_control, dict) and bool(change_control)

    acl = change_control.get("acl") if isinstance(change_control, dict) else {}
    owners = acl.get("owners") if isinstance(acl, dict) else None
    approvers = acl.get("approvers") if isinstance(acl, dict) else None
    try:
        min_approvals = int(acl.get("min_approvals") or 0) if isinstance(acl, dict) else 0
    except (TypeError, ValueError):
        min_approvals = 0

    checks["change_control_acl_ready"] = (
        isinstance(owners, list)
        and len([item for item in owners if str(item).strip()]) > 0
        and isinstance(approvers, list)
        and len([item for item in approvers if str(item).strip()]) > 0
        and min_approvals >= 1
    )

    ticket_required = bool(change_control.get("approval_ticket_required")) if isinstance(change_control, dict) else False
    if ticket_required and not checks["approval_ticket_present"]:
        failed_checks.append("approval_ticket_present")

    ledger_raw = str(change_control.get("audit_ledger") or "").strip() if isinstance(change_control, dict) else ""
    ledger_path = _resolve_path(root, Path(ledger_raw)) if ledger_raw else Path("")

    if not checks["spec_exists"]:
        failed_checks.append("spec_exists")
    if not checks["change_control_exists"]:
        failed_checks.append("change_control_exists")
    if not checks["change_control_acl_ready"]:
        failed_checks.append("change_control_acl_ready")
    if ticket_required and not checks["approval_ticket_present"]:
        failed_checks.append("approval_ticket_present")
    if not ledger_raw:
        failed_checks.append("audit_ledger_configured")

    spec_sha256 = _sha256_file(spec_path) if checks["spec_exists"] else ""
    event: Dict[str, Any] = {}
    if not failed_checks and ledger_raw:
        event = {
            "event_type": "spec_change_registered",
            "generated_at": _utc_iso_now(),
            "change_id": f"ws28_021_{uuid.uuid4().hex[:12]}",
            "spec_path": _to_repo_relative_path(spec_path, repo_root=root),
            "spec_sha256": spec_sha256,
            "approval_ticket": str(approval_ticket).strip(),
            "changed_by": str(changed_by or "").strip(),
            "notes": str(notes or "").strip(),
            "acl_snapshot": {
                "owners": [str(item).strip() for item in list(owners or []) if str(item).strip()],
                "approvers": [str(item).strip() for item in list(approvers or []) if str(item).strip()],
                "min_approvals": int(min_approvals),
            },
        }
        _append_jsonl(ledger_path, event)
        checks["ledger_event_written"] = True
    elif "audit_ledger_configured" not in failed_checks:
        failed_checks.append("ledger_event_written")

    passed = len(failed_checks) == 0 and checks["ledger_event_written"]
    report: Dict[str, Any] = {
        "task_id": "NGA-WS28-021",
        "scenario": "role_executor_semantic_guard_change_register_ws28_021",
        "generated_at": _utc_iso_now(),
        "repo_root": _to_unix_path(root),
        "passed": passed,
        "checks": checks,
        "failed_checks": failed_checks,
        "spec_file": _to_unix_path(spec_path),
        "spec_sha256": spec_sha256,
        "change_control": {
            "approval_ticket_required": ticket_required,
            "audit_ledger": _to_unix_path(ledger_path) if ledger_raw else "",
            "acl_ready": checks["change_control_acl_ready"],
        },
        "registered_event": event,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["output_file"] = _to_unix_path(output_path)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Register change-control event for semantic guard spec")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--spec-file", type=Path, default=DEFAULT_ROLE_EXECUTOR_SEMANTIC_GUARD_SPEC, help="Spec path")
    parser.add_argument("--approval-ticket", type=str, default="", help="Change approval ticket")
    parser.add_argument("--changed-by", type=str, default="release-bot", help="Change operator")
    parser.add_argument("--notes", type=str, default="", help="Optional notes")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output report path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero if checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_register_role_executor_semantic_guard_change_ws28_021(
        repo_root=args.repo_root,
        spec_file=args.spec_file,
        approval_ticket=str(args.approval_ticket or ""),
        changed_by=str(args.changed_by or ""),
        notes=str(args.notes or ""),
        output_file=args.output,
    )
    print(
        json.dumps(
            {
                "passed": bool(report.get("passed")),
                "failed_checks": list(report.get("failed_checks") or []),
                "output": str(report.get("output_file") or ""),
            },
            ensure_ascii=False,
        )
    )
    if args.strict and not bool(report.get("passed")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
