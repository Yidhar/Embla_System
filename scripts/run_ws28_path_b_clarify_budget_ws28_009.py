#!/usr/bin/env python3
"""Run WS28-009 path-b clarify-budget guard checks."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import apiserver.api_server as api_server


DEFAULT_OUTPUT = Path("scratch/reports/ws28_009_path_b_clarify_budget.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(repo_root: Path, candidate: Path) -> Path:
    return candidate if candidate.is_absolute() else repo_root / candidate


def run_ws28_path_b_clarify_budget_ws28_009(
    *,
    repo_root: Path,
    output_file: Path = DEFAULT_OUTPUT,
) -> Dict[str, Any]:
    root = repo_root.resolve()

    session_id = "ws28-009-budget-session"
    api_server.message_manager.create_session(session_id=session_id, temporary=True)

    first_route = {
        "path": "path-b",
        "outer_readonly_hit": False,
        "core_escalation": False,
        "router_decision": {
            "delegation_intent": "general_assistance",
            "prompt_profile": "outer_general",
            "injection_mode": "normal",
        },
    }
    first_after = api_server._apply_path_b_clarify_budget(dict(first_route), session_id=session_id)

    second_route = {
        "path": "path-b",
        "outer_readonly_hit": False,
        "core_escalation": False,
        "router_decision": {
            "delegation_intent": "general_assistance",
            "prompt_profile": "outer_general",
            "injection_mode": "minimal",
        },
    }
    second_after = api_server._apply_path_b_clarify_budget(dict(second_route), session_id=session_id)

    checks = {
        "first_path_b_kept_for_clarify": (
            first_after.get("path") == "path-b" and first_after.get("path_b_budget_escalated") is False
        ),
        "second_path_b_auto_escalates_core": (
            second_after.get("path") == "path-c" and second_after.get("path_b_budget_escalated") is True
        ),
        "escalated_reason_is_reported": (
            second_after.get("path_b_budget_reason") == "clarify_budget_exceeded_auto_escalate_core"
        ),
    }
    passed = all(checks.values())

    report: Dict[str, Any] = {
        "task_id": "NGA-WS28-009",
        "scenario": "path_b_clarify_budget_ws28_009",
        "generated_at": _utc_now(),
        "repo_root": _to_unix(root),
        "passed": passed,
        "checks": checks,
        "samples": {
            "first_after": first_after,
            "second_after": second_after,
        },
    }
    output = _resolve_path(root, output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["output_file"] = _to_unix(output)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS28-009 path-b clarify-budget checks")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSON report path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_ws28_path_b_clarify_budget_ws28_009(
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
