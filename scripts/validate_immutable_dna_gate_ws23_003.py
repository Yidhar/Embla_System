#!/usr/bin/env python3
"""Validate WS23-003 immutable DNA integrity gate."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from system.immutable_dna import DNAFileSpec, ImmutableDNALoader


REQUIRED_PROMPT_FILES: tuple[str, ...] = (
    "conversation_style_prompt.txt",
    "conversation_analyzer_prompt.txt",
    "tool_dispatch_prompt.txt",
    "agentic_tool_prompt.txt",
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_manifest_files(manifest_path: Path) -> Dict[str, str]:
    if not manifest_path.exists():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    rows = payload.get("files")
    if not isinstance(rows, dict):
        return {}
    return {str(k): str(v) for k, v in rows.items()}


def _missing_required_files(manifest_files: Dict[str, str], required_files: Iterable[str]) -> List[str]:
    required = [str(item).strip() for item in required_files if str(item).strip()]
    return sorted([item for item in required if item not in manifest_files])


def run_immutable_dna_gate(
    *,
    prompts_root: Path,
    manifest_path: Path | None = None,
    audit_file: Path | None = None,
    output_file: Path | None = None,
    bootstrap_if_missing: bool = False,
) -> Dict[str, Any]:
    root = prompts_root.resolve()
    manifest = manifest_path.resolve() if manifest_path is not None else (root / "immutable_dna_manifest.spec")
    audit = audit_file.resolve() if audit_file is not None else (Path("scratch/reports/immutable_dna_audit_ws23_003.jsonl").resolve())
    loader = ImmutableDNALoader(
        root_dir=root,
        dna_files=[DNAFileSpec(path=name, required=True) for name in REQUIRED_PROMPT_FILES],
        manifest_path=manifest,
        audit_file=audit,
    )
    bootstrapped = False
    if bootstrap_if_missing and not manifest.exists():
        loader.bootstrap_manifest()
        bootstrapped = True

    verify = loader.verify()
    manifest_files = _load_manifest_files(manifest)
    missing_required = _missing_required_files(manifest_files, REQUIRED_PROMPT_FILES)

    passed = bool(verify.ok) and len(missing_required) == 0
    reason = str(verify.reason)
    if verify.ok and missing_required:
        reason = "manifest_incomplete"

    report: Dict[str, Any] = {
        "task_id": "NGA-WS23-003",
        "scenario": "immutable_dna_gate_validation",
        "generated_at": _utc_iso(),
        "prompts_root": str(root).replace("\\", "/"),
        "manifest_path": str(manifest).replace("\\", "/"),
        "audit_file": str(audit).replace("\\", "/"),
        "bootstrapped_manifest": bootstrapped,
        "required_prompt_files": list(REQUIRED_PROMPT_FILES),
        "missing_required_files": missing_required,
        "verify": verify.to_dict(),
        "passed": passed,
        "reason": reason,
    }

    if output_file is not None:
        target = output_file.resolve() if output_file.is_absolute() else (Path(".").resolve() / output_file)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["output_file"] = str(target).replace("\\", "/")

    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate immutable DNA gate for WS23-003")
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
        default=Path("scratch/reports/immutable_dna_gate_ws23_003_result.json"),
        help="Validation report output path",
    )
    parser.add_argument(
        "--bootstrap-if-missing",
        action="store_true",
        help="Bootstrap manifest when it is missing before validation",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_immutable_dna_gate(
        prompts_root=args.prompts_root,
        manifest_path=args.manifest_path,
        audit_file=args.audit_file,
        output_file=args.output,
        bootstrap_if_missing=bool(args.bootstrap_if_missing),
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
    return 0 if bool(report.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
