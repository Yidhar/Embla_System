#!/usr/bin/env python3
"""Run WS28-011 chat route-bridge observability checks."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import apiserver.api_server as api_server


DEFAULT_OUTPUT = Path("scratch/reports/ws28_011_chat_route_bridge_observability.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(repo_root: Path, candidate: Path) -> Path:
    return candidate if candidate.is_absolute() else repo_root / candidate


def run_ws28_chat_route_bridge_observability_ws28_011(
    *,
    repo_root: Path,
    output_file: Path = DEFAULT_OUTPUT,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    outer_session_id = api_server.message_manager.create_session(temporary=True)
    core_session_id = ""
    try:
        route_meta = api_server._apply_outer_core_session_bridge(
            {
                "path": "path-c",
                "router_decision": {
                    "delegation_intent": "core_execution",
                    "prompt_profile": "core_exec_general",
                    "injection_mode": "normal",
                },
                "path_b_clarify_turns": 1,
                "path_b_clarify_limit": api_server._CHAT_ROUTE_PATH_B_CLARIFY_LIMIT,
                "path_b_budget_escalated": True,
                "path_b_budget_reason": "clarify_budget_exceeded_auto_escalate_core",
            },
            outer_session_id=outer_session_id,
        )
        core_session_id = str(route_meta.get("core_session_id") or "")
        api_server._emit_chat_route_prompt_event(route_meta, session_id=outer_session_id)

        snapshot = api_server._build_chat_route_bridge_payload(outer_session_id, limit=20)
        v1_snapshot = asyncio.run(api_server.get_chat_route_bridge_v1(session_id=outer_session_id, limit=20))

        matched_events = [
            event
            for event in snapshot.get("recent_route_events", [])
            if str(event.get("outer_session_id") or "") == outer_session_id
        ]
        checks = {
            "bridge_snapshot_contains_outer_core_mapping": (
                snapshot.get("outer_session_id") == outer_session_id
                and bool(core_session_id)
                and snapshot.get("core_session_id") == core_session_id
                and snapshot.get("execution_session_id") == core_session_id
            ),
            "bridge_snapshot_includes_clarify_budget_state": (
                int(snapshot.get("state", {}).get("path_b_clarify_limit") or 0)
                == int(api_server._CHAT_ROUTE_PATH_B_CLARIFY_LIMIT)
            ),
            "bridge_snapshot_has_recent_prompt_events": len(matched_events) > 0,
            "v1_endpoint_alias_returns_same_snapshot": (
                v1_snapshot.get("status") == "success"
                and v1_snapshot.get("outer_session_id") == outer_session_id
                and v1_snapshot.get("core_session_id") == core_session_id
            ),
        }
        passed = all(checks.values())
        report: Dict[str, Any] = {
            "task_id": "NGA-WS28-011",
            "scenario": "chat_route_bridge_observability_ws28_011",
            "generated_at": _utc_now(),
            "repo_root": _to_unix(root),
            "passed": passed,
            "checks": checks,
            "samples": {
                "outer_session_id": outer_session_id,
                "core_session_id": core_session_id,
                "route_bridge_snapshot": snapshot,
            },
        }
    finally:
        api_server.message_manager.delete_session(outer_session_id)
        if core_session_id:
            api_server.message_manager.delete_session(core_session_id)

    output = _resolve_path(root, output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["output_file"] = _to_unix(output)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS28-011 chat route bridge observability checks")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSON report path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_ws28_chat_route_bridge_observability_ws28_011(
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
