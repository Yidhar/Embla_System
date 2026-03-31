#!/usr/bin/env python3
"""Run WS28-005 DNA .spec single-source guard checks."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from scripts.update_immutable_dna_manifest_ws23_003 import run_update_immutable_dna_manifest
from scripts.validate_immutable_dna_gate_ws23_003 import _resolve_required_prompt_files, run_immutable_dna_gate


DEFAULT_OUTPUT = Path("scratch/reports/ws28_005_dna_spec_gate.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(repo_root: Path, candidate: Path) -> Path:
    return candidate if candidate.is_absolute() else repo_root / candidate


def _prepare_runtime_prompts(repo_root: Path, runtime_root: Path) -> Path:
    src = repo_root / "system" / "prompts"
    dst = runtime_root / "prompts"
    dst.mkdir(parents=True, exist_ok=True)
    for name in _resolve_required_prompt_files(prompts_root=src):
        source = src / name
        target = dst / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            target.write_text(f"{name}-placeholder\n", encoding="utf-8")
    return dst


def run_ws28_dna_spec_gate_ws28_005(
    *,
    repo_root: Path,
    output_file: Path = DEFAULT_OUTPUT,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    runtime_root = root / "scratch" / "ws28_005_runtime"
    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    prompts_root = _prepare_runtime_prompts(root, runtime_root)
    audit_file = runtime_root / "audit.jsonl"
    manifest_spec = prompts_root / "immutable_dna_manifest.spec"
    manifest_json = prompts_root / "immutable_dna_manifest.json"

    json_gate_report = run_immutable_dna_gate(
        prompts_root=prompts_root,
        manifest_path=manifest_json,
        audit_file=audit_file,
        output_file=None,
        bootstrap_if_missing=False,
    )
    missing_ticket_report = run_update_immutable_dna_manifest(
        prompts_root=prompts_root,
        manifest_path=manifest_spec,
        audit_file=audit_file,
        output_file=None,
        approval_ticket="",
        approval_ticket_env="",
        change_reason="has reason but no ticket",
        strict_mode=True,
        verify_after_update=False,
    )
    missing_reason_report = run_update_immutable_dna_manifest(
        prompts_root=prompts_root,
        manifest_path=manifest_spec,
        audit_file=audit_file,
        output_file=None,
        approval_ticket="TICKET-WS28-005",
        approval_ticket_env="",
        change_reason="",
        strict_mode=True,
        verify_after_update=False,
    )
    success_report = run_update_immutable_dna_manifest(
        prompts_root=prompts_root,
        manifest_path=manifest_spec,
        audit_file=audit_file,
        output_file=None,
        approval_ticket="TICKET-WS28-005",
        approval_ticket_env="",
        change_reason="controlled update for ws28-005",
        strict_mode=True,
        verify_after_update=True,
    )

    checks = {
        "gate_rejects_json_manifest": (
            bool(json_gate_report.get("passed")) is False
            and json_gate_report.get("reason") == "manifest_extension_not_spec"
        ),
        "update_requires_approval_ticket": (
            bool(missing_ticket_report.get("passed")) is False
            and missing_ticket_report.get("reason") == "missing_approval_ticket"
        ),
        "strict_requires_change_reason": (
            bool(missing_reason_report.get("passed")) is False
            and missing_reason_report.get("reason") == "missing_change_reason"
        ),
        "spec_update_and_verify_passes": bool(success_report.get("passed")),
    }
    passed = all(checks.values())

    report: Dict[str, Any] = {
        "task_id": "NGA-WS28-005",
        "scenario": "dna_spec_single_source_and_controlled_update_ws28_005",
        "generated_at": _utc_now(),
        "repo_root": _to_unix(root),
        "runtime_root": _to_unix(runtime_root),
        "passed": passed,
        "checks": checks,
        "samples": {
            "json_gate_report": json_gate_report,
            "missing_ticket_report": missing_ticket_report,
            "missing_reason_report": missing_reason_report,
            "success_report": success_report,
        },
    }

    output = _resolve_path(root, output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["output_file"] = _to_unix(output)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS28-005 DNA .spec single-source guard checks")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSON report path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_ws28_dna_spec_gate_ws28_005(
        repo_root=args.repo_root,
        output_file=args.output,
    )
    print(
        json.dumps(
            {
                "passed": bool(report.get("passed")),
                "checks": report.get("checks", {}),
                "output": report.get("output_file"),
            },
            ensure_ascii=False,
        )
    )
    if args.strict and not bool(report.get("passed")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
