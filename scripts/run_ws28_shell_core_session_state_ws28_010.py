#!/usr/bin/env python3
"""Run WS28-010 shell/core session-state checks."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import apiserver.api_server as api_server


DEFAULT_OUTPUT = Path("scratch/reports/ws28_010_shell_core_session_state.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(repo_root: Path, candidate: Path) -> Path:
    return candidate if candidate.is_absolute() else repo_root / candidate


def run_ws28_shell_core_session_state_ws28_010(
    *,
    repo_root: Path,
    output_file: Path = DEFAULT_OUTPUT,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    shell_session_id = api_server.message_manager.create_session(session_id="ws28-010-shell", temporary=True)
    try:
        first_core = api_server._apply_shell_core_session_state(
            {
                "route_semantic": "core_execution",
                "router_decision": {"delegation_intent": "core_execution"},
            },
            shell_session_id=shell_session_id,
        )
        second_core = api_server._apply_shell_core_session_state(
            {
                "route_semantic": "core_execution",
                "router_decision": {"delegation_intent": "core_execution"},
            },
            shell_session_id=shell_session_id,
        )
        shell_route = api_server._apply_shell_core_session_state(
            {
                "route_semantic": "shell_readonly",
                "router_decision": {"delegation_intent": "read_only_exploration"},
            },
            shell_session_id=shell_session_id,
        )

        checks = {
            "core_execution_creates_core_session": bool(first_core.get("core_execution_session_created")),
            "core_execution_reuses_core_session": (
                first_core.get("core_execution_session_id")
                and first_core.get("core_execution_session_id") == second_core.get("core_execution_session_id")
                and second_core.get("core_execution_session_created") is False
            ),
            "non_core_execution_route_keeps_shell_session": shell_route.get("shell_session_id") == shell_session_id,
        }
        passed = all(checks.values())

        report: Dict[str, Any] = {
            "task_id": "NGA-WS28-010",
            "scenario": "shell_core_session_state_ws28_010",
            "generated_at": _utc_now(),
            "repo_root": _to_unix(root),
            "passed": passed,
            "checks": checks,
            "samples": {
                "first_core": first_core,
                "second_core": second_core,
                "shell_route": shell_route,
            },
        }
    finally:
        api_server.message_manager.delete_session(shell_session_id)
        api_server.message_manager.delete_session(f"{shell_session_id}__core")

    output = _resolve_path(root, output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["output_file"] = _to_unix(output)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS28-010 shell/core session-state checks")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSON report path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_ws28_shell_core_session_state_ws28_010(
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
