#!/usr/bin/env python3
"""Update WS23-003 immutable DNA manifest and optionally verify gate."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

# Support direct execution: `python scripts/update_immutable_dna_manifest_ws23_003.py`.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from system.immutable_dna import DNAFileSpec, ImmutableDNALoader

try:
    from scripts.validate_immutable_dna_gate_ws23_003 import (
        _resolve_required_prompt_files,
        run_immutable_dna_gate,
    )
except ModuleNotFoundError:
    from scripts.validate_immutable_dna_gate_ws23_003 import (  # type: ignore[no-redef]
        _resolve_required_prompt_files,
        run_immutable_dna_gate,
    )


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_ticket(
    approval_ticket: str | None,
    *,
    approval_ticket_env: str | None,
) -> str:
    text = str(approval_ticket or "").strip()
    if text:
        return text
    env_key = str(approval_ticket_env or "").strip()
    if not env_key:
        return ""
    import os

    return str(os.environ.get(env_key) or "").strip()


def run_update_immutable_dna_manifest(
    *,
    prompts_root: Path,
    manifest_path: Path | None = None,
    audit_file: Path | None = None,
    output_file: Path | None = None,
    approval_ticket: str | None = None,
    approval_ticket_env: str | None = "DNA_APPROVAL_TICKET",
    change_reason: str | None = None,
    strict_mode: bool = False,
    verify_after_update: bool = True,
) -> Dict[str, Any]:
    root = prompts_root.resolve()
    required_prompt_files = _resolve_required_prompt_files(prompts_root=root)
    manifest = manifest_path.resolve() if manifest_path is not None else (root / "immutable_dna_manifest.spec")
    audit = (
        audit_file.resolve()
        if audit_file is not None
        else Path("scratch/reports/immutable_dna_audit_ws23_003.jsonl").resolve()
    )
    ticket = _normalize_ticket(approval_ticket, approval_ticket_env=approval_ticket_env)
    normalized_change_reason = str(change_reason or "").strip()

    report: Dict[str, Any] = {
        "task_id": "NGA-WS23-003",
        "scenario": "immutable_dna_manifest_update",
        "generated_at": _utc_iso(),
        "prompts_root": str(root).replace("\\", "/"),
        "manifest_path": str(manifest).replace("\\", "/"),
        "audit_file": str(audit).replace("\\", "/"),
        "required_prompt_files": list(required_prompt_files),
        "verify_after_update": bool(verify_after_update),
        "change_reason": normalized_change_reason,
        "strict_mode": bool(strict_mode),
    }

    if not ticket:
        report.update(
            {
                "passed": False,
                "reason": "missing_approval_ticket",
                "approval_ticket_source": str(approval_ticket_env or ""),
            }
        )
        if output_file is not None:
            target = output_file.resolve() if output_file.is_absolute() else (Path(".").resolve() / output_file)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            report["output_file"] = str(target).replace("\\", "/")
        return report

    if strict_mode and not normalized_change_reason:
        report.update(
            {
                "passed": False,
                "reason": "missing_change_reason",
            }
        )
        if output_file is not None:
            target = output_file.resolve() if output_file.is_absolute() else (Path(".").resolve() / output_file)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            report["output_file"] = str(target).replace("\\", "/")
        return report

    loader = ImmutableDNALoader(
        root_dir=root,
        dna_files=[DNAFileSpec(path=name, required=True) for name in required_prompt_files],
        manifest_path=manifest,
        audit_file=audit,
    )
    new_manifest = loader.approved_update_manifest(approval_ticket=ticket)
    report["manifest_generated_at"] = str(new_manifest.generated_at)
    report["manifest_file_count"] = len(new_manifest.files)
    report["approval_ticket"] = ticket

    gate_report: Dict[str, Any] | None = None
    if verify_after_update:
        gate_report = run_immutable_dna_gate(
            prompts_root=root,
            manifest_path=manifest,
            audit_file=audit,
            output_file=None,
            bootstrap_if_missing=False,
        )
        report["gate_report"] = gate_report
        report["passed"] = bool(gate_report.get("passed"))
        report["reason"] = str(gate_report.get("reason") or "unknown")
    else:
        report["passed"] = True
        report["reason"] = "manifest_updated_without_verify"

    if output_file is not None:
        target = output_file.resolve() if output_file.is_absolute() else (Path(".").resolve() / output_file)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["output_file"] = str(target).replace("\\", "/")

    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update immutable DNA manifest for WS23-003")
    parser.add_argument("--prompts-root", type=Path, default=Path("system/prompts"), help="Prompt DNA root directory")
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=Path("system/prompts/immutable_dna_manifest.spec"),
        help="Immutable DNA manifest path",
    )
    parser.add_argument(
        "--audit-file",
        type=Path,
        default=Path("scratch/reports/immutable_dna_audit_ws23_003.jsonl"),
        help="Audit log output path",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("scratch/reports/immutable_dna_manifest_update_ws23_003.json"),
        help="Update report output path",
    )
    parser.add_argument(
        "--approval-ticket",
        type=str,
        default="",
        help="Change approval ticket for manifest update (or use --approval-ticket-env)",
    )
    parser.add_argument(
        "--approval-ticket-env",
        type=str,
        default="DNA_APPROVAL_TICKET",
        help="Environment variable name used when --approval-ticket is empty",
    )
    parser.add_argument(
        "--change-reason",
        type=str,
        default="",
        help="Reason for updating immutable DNA manifest (required in --strict mode)",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Only update manifest without gate verification",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero exit code when update result is failed",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_update_immutable_dna_manifest(
        prompts_root=args.prompts_root,
        manifest_path=args.manifest_path,
        audit_file=args.audit_file,
        output_file=args.output,
        approval_ticket=args.approval_ticket,
        approval_ticket_env=args.approval_ticket_env,
        change_reason=args.change_reason,
        strict_mode=bool(args.strict),
        verify_after_update=not bool(args.skip_verify),
    )
    print(
        json.dumps(
            {
                "passed": report.get("passed"),
                "reason": report.get("reason"),
                "output": report.get("output_file"),
            },
            ensure_ascii=False,
        )
    )
    if bool(args.strict) and not bool(report.get("passed")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
