#!/usr/bin/env python3
"""Run WS28-003 prompt ACL guard checks."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from system.config import evaluate_prompt_acl


DEFAULT_OUTPUT = Path("scratch/reports/ws28_003_prompt_acl_guard.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(repo_root: Path, candidate: Path) -> Path:
    return candidate if candidate.is_absolute() else repo_root / candidate


def run_ws28_prompt_acl_guard_ws28_003(
    *,
    repo_root: Path,
    output_file: Path = DEFAULT_OUTPUT,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    s0 = evaluate_prompt_acl(
        prompt_name="immutable_dna_manifest",
        approval_ticket="TICKET-S0",
        change_reason="attempt update locked file",
    )
    s1_missing_ticket = evaluate_prompt_acl(
        prompt_name="conversation_style_prompt",
        approval_ticket="",
        change_reason="missing ticket should fail",
    )
    s1_with_ticket = evaluate_prompt_acl(
        prompt_name="conversation_style_prompt",
        approval_ticket="TICKET-S1",
        change_reason="controlled update",
    )
    s2 = evaluate_prompt_acl(
        prompt_name="custom_prompt",
        approval_ticket="",
        change_reason="",
    )

    checks = {
        "s0_locked_rejected": bool(s0.get("blocked")) and s0.get("reason_code") == "PROMPT_ACL_S0_LOCKED",
        "s1_requires_ticket": bool(s1_missing_ticket.get("blocked"))
        and s1_missing_ticket.get("reason_code") == "PROMPT_ACL_APPROVAL_TICKET_REQUIRED",
        "s1_with_ticket_allowed": bool(s1_with_ticket.get("allowed")) and not bool(s1_with_ticket.get("blocked")),
        "s2_flexible_allowed": bool(s2.get("allowed")) and s2.get("matched_rule", {}).get("level") == "S2_FLEXIBLE",
    }
    passed = all(checks.values())

    report: Dict[str, Any] = {
        "task_id": "NGA-WS28-003",
        "scenario": "prompt_acl_api_guard_ws28_003",
        "generated_at": _utc_now(),
        "repo_root": _to_unix(root),
        "passed": passed,
        "checks": checks,
        "samples": {
            "s0_locked": s0,
            "s1_missing_ticket": s1_missing_ticket,
            "s1_with_ticket": s1_with_ticket,
            "s2_flexible": s2,
        },
    }

    output = _resolve_path(root, output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["output_file"] = _to_unix(output)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS28-003 prompt ACL guard checks")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSON report path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_ws28_prompt_acl_guard_ws28_003(
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
