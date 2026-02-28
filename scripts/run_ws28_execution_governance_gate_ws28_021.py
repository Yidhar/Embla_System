#!/usr/bin/env python3
"""Run WS28-021 execution-governance gate based on runtime posture/incidents summaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from autonomous.tools.execution_bridge import (
    DEFAULT_ROLE_EXECUTOR_SEMANTIC_GUARD_SPEC,
    ROLE_EXECUTOR_SEMANTIC_GUARD_SPEC_SCHEMA,
)
from core.security import AuditLedger


DEFAULT_OUTPUT = Path("scratch/reports/ws28_execution_governance_gate_ws28_021.json")
DEFAULT_RUNTIME_POSTURE_OUTPUT = Path("scratch/reports/ws28_execution_governance_runtime_posture_ws28_021.json")
DEFAULT_INCIDENTS_OUTPUT = Path("scratch/reports/ws28_execution_governance_incidents_ws28_021.json")
DEFAULT_SEMANTIC_GUARD_SPEC = DEFAULT_ROLE_EXECUTOR_SEMANTIC_GUARD_SPEC
_REQUIRED_SEMANTIC_ROLES = ("frontend", "backend", "ops")


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(repo_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _sha256_file(path: Path) -> str:
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""
    return digest


def _resolve_ledger_path(repo_root: Path, ledger_raw: str) -> Path:
    candidate = Path(str(ledger_raw).strip())
    return candidate if candidate.is_absolute() else repo_root / candidate


def _load_latest_change_event(ledger_path: Path) -> Dict[str, Any]:
    if not ledger_path.exists():
        return {}
    latest: Dict[str, Any] = {}
    try:
        lines = ledger_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for line in lines:
        raw = str(line or "").strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        latest = payload

    if not latest:
        return {}

    nested = latest.get("payload") if isinstance(latest.get("payload"), dict) else {}
    normalized = dict(latest)
    if "event_type" not in normalized:
        normalized["event_type"] = str(latest.get("record_type") or nested.get("event_type") or "")
    if "generated_at" not in normalized:
        normalized["generated_at"] = str(latest.get("generated_at") or latest.get("ts") or "")
    if "spec_sha256" not in normalized:
        normalized["spec_sha256"] = str(nested.get("spec_sha256") or "")
    if "changed_by" not in normalized:
        normalized["changed_by"] = str(nested.get("changed_by") or latest.get("requested_by") or "")
    if "change_id" not in normalized:
        normalized["change_id"] = str(latest.get("change_id") or "")
    return normalized


def _validate_semantic_guard_spec(spec_path: Path, *, repo_root: Path) -> Dict[str, Any]:
    checks = {
        "semantic_guard_spec_exists": spec_path.exists(),
        "semantic_guard_spec_schema_valid": False,
        "semantic_guard_spec_roles_ready": False,
        "semantic_guard_change_control_ready": False,
        "semantic_guard_change_control_ledger_exists": False,
        "semantic_guard_change_control_ledger_chain_valid": False,
        "semantic_guard_change_control_latest_event_valid": False,
        "semantic_guard_change_control_latest_sha_match": False,
    }
    failed_reasons = []
    schema_version = ""
    roles_summary: Dict[str, Any] = {}
    sha256 = ""
    change_control_summary: Dict[str, Any] = {}

    if not checks["semantic_guard_spec_exists"]:
        failed_reasons.append("semantic_guard_spec_missing")
        return {
            "path": _to_unix_path(spec_path),
            "schema_version": schema_version,
            "sha256": sha256,
            "checks": checks,
            "failed_reasons": failed_reasons,
            "roles": roles_summary,
            "change_control": change_control_summary,
        }

    sha256 = _sha256_file(spec_path)
    payload: Dict[str, Any] = {}
    try:
        loaded = json.loads(spec_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            payload = loaded
    except (OSError, json.JSONDecodeError):
        payload = {}

    schema_version = str(payload.get("schema_version") or "").strip()
    checks["semantic_guard_spec_schema_valid"] = schema_version == ROLE_EXECUTOR_SEMANTIC_GUARD_SPEC_SCHEMA
    if not checks["semantic_guard_spec_schema_valid"]:
        failed_reasons.append("semantic_guard_spec_schema_invalid")

    roles = payload.get("roles") if isinstance(payload.get("roles"), dict) else {}
    role_checks: Dict[str, bool] = {}
    for role in _REQUIRED_SEMANTIC_ROLES:
        config = roles.get(role) if isinstance(roles, dict) else None
        allowed_toolchains = config.get("allowed_semantic_toolchains") if isinstance(config, dict) else None
        role_checks[role] = isinstance(allowed_toolchains, list) and len([item for item in allowed_toolchains if str(item).strip()]) > 0
        roles_summary[role] = {
            "configured": isinstance(config, dict),
            "allowed_semantic_toolchains_count": len(allowed_toolchains) if isinstance(allowed_toolchains, list) else 0,
        }
    checks["semantic_guard_spec_roles_ready"] = all(role_checks.values())
    if not checks["semantic_guard_spec_roles_ready"]:
        failed_reasons.append("semantic_guard_spec_roles_incomplete")

    change_control = payload.get("change_control") if isinstance(payload.get("change_control"), dict) else {}
    acl = change_control.get("acl") if isinstance(change_control, dict) else {}
    owners = acl.get("owners") if isinstance(acl, dict) else None
    approvers = acl.get("approvers") if isinstance(acl, dict) else None
    min_approvals = _safe_int(acl.get("min_approvals") if isinstance(acl, dict) else 0, default=0)
    ticket_required = bool(change_control.get("approval_ticket_required")) if isinstance(change_control, dict) else False
    ledger_raw = str(change_control.get("audit_ledger") or "").strip() if isinstance(change_control, dict) else ""
    ledger_path = _resolve_ledger_path(repo_root, ledger_raw) if ledger_raw else Path("")

    checks["semantic_guard_change_control_ready"] = (
        isinstance(owners, list)
        and len([item for item in owners if str(item).strip()]) > 0
        and isinstance(approvers, list)
        and len([item for item in approvers if str(item).strip()]) > 0
        and min_approvals >= 1
        and ticket_required
        and bool(ledger_raw)
    )
    if not checks["semantic_guard_change_control_ready"]:
        failed_reasons.append("semantic_guard_change_control_not_ready")

    checks["semantic_guard_change_control_ledger_exists"] = bool(ledger_raw) and ledger_path.exists()
    if not checks["semantic_guard_change_control_ledger_exists"]:
        failed_reasons.append("semantic_guard_change_control_ledger_missing")
    else:
        verify = AuditLedger(ledger_file=ledger_path).verify_chain()
        checks["semantic_guard_change_control_ledger_chain_valid"] = bool(verify.passed and verify.checked_count >= 1)
        if not checks["semantic_guard_change_control_ledger_chain_valid"]:
            failed_reasons.append("semantic_guard_change_control_ledger_chain_invalid")

    latest_event = _load_latest_change_event(ledger_path) if checks["semantic_guard_change_control_ledger_exists"] else {}
    latest_ticket = str(latest_event.get("approval_ticket") or "").strip() if isinstance(latest_event, dict) else ""
    latest_sha = str(latest_event.get("spec_sha256") or "").strip() if isinstance(latest_event, dict) else ""
    checks["semantic_guard_change_control_latest_event_valid"] = bool(latest_ticket) and bool(latest_sha)
    if not checks["semantic_guard_change_control_latest_event_valid"]:
        failed_reasons.append("semantic_guard_change_control_latest_event_invalid")

    checks["semantic_guard_change_control_latest_sha_match"] = bool(latest_sha) and latest_sha == sha256
    if not checks["semantic_guard_change_control_latest_sha_match"]:
        failed_reasons.append("semantic_guard_change_control_sha_mismatch")

    change_control_summary = {
        "schema_version": str(change_control.get("schema_version") or "") if isinstance(change_control, dict) else "",
        "approval_ticket_required": ticket_required,
        "audit_ledger": _to_unix_path(ledger_path) if ledger_raw else "",
        "acl": {
            "owners": [str(item).strip() for item in list(owners or []) if str(item).strip()],
            "approvers": [str(item).strip() for item in list(approvers or []) if str(item).strip()],
            "min_approvals": int(min_approvals),
        },
        "latest_event": {
            "event_type": str(latest_event.get("event_type") or "") if isinstance(latest_event, dict) else "",
            "generated_at": str(latest_event.get("generated_at") or "") if isinstance(latest_event, dict) else "",
            "approval_ticket_present": bool(latest_ticket),
            "spec_sha256": latest_sha,
            "changed_by": str(latest_event.get("changed_by") or "") if isinstance(latest_event, dict) else "",
        },
    }

    return {
        "path": _to_unix_path(spec_path),
        "schema_version": schema_version,
        "sha256": sha256,
        "checks": checks,
        "failed_reasons": failed_reasons,
        "roles": roles_summary,
        "change_control": change_control_summary,
    }


def run_ws28_execution_governance_gate_ws28_021(
    *,
    repo_root: Path,
    output_file: Path = DEFAULT_OUTPUT,
    runtime_posture_output: Path = DEFAULT_RUNTIME_POSTURE_OUTPUT,
    incidents_output: Path = DEFAULT_INCIDENTS_OUTPUT,
    events_limit: int = 5000,
    incidents_limit: int = 50,
    max_warning_ratio: float = 0.30,
    max_rejection_ratio: float = 0.20,
    semantic_guard_spec: Path = DEFAULT_SEMANTIC_GUARD_SPEC,
) -> Dict[str, Any]:
    started = time.time()
    root = repo_root.resolve()
    runtime_output_path = _resolve_path(root, runtime_posture_output)
    incidents_output_path = _resolve_path(root, incidents_output)
    output_path = _resolve_path(root, output_file)
    semantic_guard_spec_path = _resolve_path(root, semantic_guard_spec)

    import apiserver.api_server as api_server

    original_repo_root = api_server._ops_repo_root  # noqa: SLF001
    try:
        api_server._ops_repo_root = lambda: root  # type: ignore[assignment]  # noqa: SLF001
        runtime_posture_payload = api_server._ops_build_runtime_posture_payload(events_limit=max(1, int(events_limit)))  # noqa: SLF001
        incidents_payload = api_server._ops_build_incidents_latest_payload(limit=max(1, int(incidents_limit)))  # noqa: SLF001
    finally:
        api_server._ops_repo_root = original_repo_root  # type: ignore[assignment]  # noqa: SLF001

    _write_json(runtime_output_path, runtime_posture_payload)
    _write_json(incidents_output_path, incidents_payload)

    runtime_data = runtime_posture_payload.get("data") if isinstance(runtime_posture_payload.get("data"), dict) else {}
    runtime_summary = runtime_data.get("summary") if isinstance(runtime_data.get("summary"), dict) else {}
    runtime_governance = (
        runtime_data.get("execution_bridge_governance")
        if isinstance(runtime_data.get("execution_bridge_governance"), dict)
        else {}
    )
    runtime_governance_status = str(
        runtime_summary.get("execution_bridge_governance_status") or runtime_governance.get("status") or "unknown"
    ).strip().lower()

    incidents_data = incidents_payload.get("data") if isinstance(incidents_payload.get("data"), dict) else {}
    incidents_summary = incidents_data.get("summary") if isinstance(incidents_data.get("summary"), dict) else {}
    incidents_governance = (
        incidents_summary.get("execution_bridge_governance")
        if isinstance(incidents_summary.get("execution_bridge_governance"), dict)
        else {}
    )
    incidents_governance_status = str(incidents_governance.get("status") or "unknown").strip().lower()
    critical_issue_count = _safe_int(incidents_governance.get("governed_critical_count"), default=0)

    warning_ratio = _safe_float(runtime_governance.get("governed_warning_ratio"))
    rejection_ratio = _safe_float(runtime_governance.get("rejection_ratio"))
    semantic_guard_spec_report = _validate_semantic_guard_spec(semantic_guard_spec_path, repo_root=root)
    semantic_guard_spec_checks = (
        semantic_guard_spec_report.get("checks")
        if isinstance(semantic_guard_spec_report.get("checks"), dict)
        else {}
    )

    checks = {
        "runtime_posture_payload_success": str(runtime_posture_payload.get("status") or "") == "success",
        "incidents_payload_success": str(incidents_payload.get("status") or "") == "success",
        "runtime_governance_status_not_critical": runtime_governance_status != "critical",
        "incidents_governance_status_not_critical": incidents_governance_status != "critical",
        "critical_governance_issue_count_zero": critical_issue_count == 0,
        "governance_warning_ratio_within_budget": warning_ratio is None or warning_ratio <= float(max_warning_ratio),
        "governance_rejection_ratio_within_budget": rejection_ratio is None or rejection_ratio <= float(max_rejection_ratio),
        "semantic_guard_spec_exists": bool(semantic_guard_spec_checks.get("semantic_guard_spec_exists")),
        "semantic_guard_spec_schema_valid": bool(semantic_guard_spec_checks.get("semantic_guard_spec_schema_valid")),
        "semantic_guard_spec_roles_ready": bool(semantic_guard_spec_checks.get("semantic_guard_spec_roles_ready")),
        "semantic_guard_change_control_ready": bool(
            semantic_guard_spec_checks.get("semantic_guard_change_control_ready")
        ),
        "semantic_guard_change_control_ledger_exists": bool(
            semantic_guard_spec_checks.get("semantic_guard_change_control_ledger_exists")
        ),
        "semantic_guard_change_control_ledger_chain_valid": bool(
            semantic_guard_spec_checks.get("semantic_guard_change_control_ledger_chain_valid")
        ),
        "semantic_guard_change_control_latest_event_valid": bool(
            semantic_guard_spec_checks.get("semantic_guard_change_control_latest_event_valid")
        ),
        "semantic_guard_change_control_latest_sha_match": bool(
            semantic_guard_spec_checks.get("semantic_guard_change_control_latest_sha_match")
        ),
    }
    passed = all(bool(value) for value in checks.values())
    failed_checks = [key for key, value in checks.items() if not bool(value)]

    report: Dict[str, Any] = {
        "task_id": "NGA-WS28-021",
        "scenario": "execution_bridge_governance_gate_ws28_021",
        "generated_at": _utc_iso_now(),
        "repo_root": _to_unix_path(root),
        "passed": passed,
        "checks": checks,
        "failed_checks": failed_checks,
        "thresholds": {
            "max_warning_ratio": float(max_warning_ratio),
            "max_rejection_ratio": float(max_rejection_ratio),
        },
        "governance": {
            "runtime_status": runtime_governance_status,
            "incidents_status": incidents_governance_status,
            "critical_issue_count": critical_issue_count,
            "warning_ratio": warning_ratio,
            "rejection_ratio": rejection_ratio,
            "reason_codes": list(runtime_governance.get("reason_codes") or []),
        },
        "semantic_guard_spec": semantic_guard_spec_report,
        "outputs": {
            "runtime_posture_output": _to_unix_path(runtime_output_path),
            "incidents_output": _to_unix_path(incidents_output_path),
        },
        "elapsed_seconds": round(time.time() - started, 4),
    }
    _write_json(output_path, report)
    report["output_file"] = _to_unix_path(output_path)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS28-021 execution governance gate")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Gate output JSON path")
    parser.add_argument(
        "--runtime-posture-output",
        type=Path,
        default=DEFAULT_RUNTIME_POSTURE_OUTPUT,
        help="Runtime posture snapshot output path",
    )
    parser.add_argument(
        "--incidents-output",
        type=Path,
        default=DEFAULT_INCIDENTS_OUTPUT,
        help="Incidents snapshot output path",
    )
    parser.add_argument("--events-limit", type=int, default=5000, help="Events limit for runtime posture collector")
    parser.add_argument("--incidents-limit", type=int, default=50, help="Incidents limit for incidents collector")
    parser.add_argument(
        "--max-warning-ratio",
        type=float,
        default=0.30,
        help="Maximum accepted governance warning ratio",
    )
    parser.add_argument(
        "--max-rejection-ratio",
        type=float,
        default=0.20,
        help="Maximum accepted governance rejection ratio",
    )
    parser.add_argument(
        "--semantic-guard-spec",
        type=Path,
        default=DEFAULT_SEMANTIC_GUARD_SPEC,
        help="Semantic guard policy .spec path",
    )
    parser.add_argument("--strict", action="store_true", help="Return non-zero when checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_ws28_execution_governance_gate_ws28_021(
        repo_root=args.repo_root,
        output_file=args.output,
        runtime_posture_output=args.runtime_posture_output,
        incidents_output=args.incidents_output,
        events_limit=max(1, int(args.events_limit)),
        incidents_limit=max(1, int(args.incidents_limit)),
        max_warning_ratio=max(0.0, float(args.max_warning_ratio)),
        max_rejection_ratio=max(0.0, float(args.max_rejection_ratio)),
        semantic_guard_spec=args.semantic_guard_spec,
    )
    print(
        json.dumps(
            {
                "passed": bool(report.get("passed")),
                "failed_checks": report.get("failed_checks", []),
                "output": report.get("output_file", ""),
            },
            ensure_ascii=False,
        )
    )
    if args.strict and not bool(report.get("passed")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
