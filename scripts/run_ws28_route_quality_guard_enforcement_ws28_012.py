#!/usr/bin/env python3
"""Run WS28-012 route-quality guard enforcement checks."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import apiserver.api_server
from apiserver import routes_ops as api_server


DEFAULT_OUTPUT = Path("scratch/reports/ws28_012_route_quality_guard_enforcement.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _resolve_path(repo_root: Path, candidate: Path) -> Path:
    return candidate if candidate.is_absolute() else repo_root / candidate


class _CaptureEventStore:
    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []

    def emit(self, event_type: str, payload: Dict[str, Any], source: str = "") -> None:
        self.rows.append(
            {
                "event_type": str(event_type or ""),
                "payload": dict(payload or {}),
                "source": str(source or ""),
            }
        )


def run_ws28_route_quality_guard_enforcement_ws28_012(
    *,
    repo_root: Path,
    output_file: Path = DEFAULT_OUTPUT,
) -> Dict[str, Any]:
    root = repo_root.resolve()

    warning_session_id = "ws28-012-warning"
    critical_session_id = "ws28-012-critical"
    api_server.message_manager.create_session(session_id=warning_session_id, temporary=True)
    api_server.message_manager.create_session(session_id=critical_session_id, temporary=True)

    warning_summary = {
        "status": "warning",
        "reason_codes": ["PATH_B_BUDGET_ESCALATION_WARNING"],
        "reason_text": "Route-quality warning detected.",
        "trend": {
            "status": "warning",
            "direction": "degrading",
            "sample_count": 40,
        },
        "evaluated_at": "2026-02-26T00:00:00+00:00",
    }
    critical_summary = {
        "status": "critical",
        "reason_codes": ["READONLY_WRITE_EXPOSURE_CRITICAL", "ROUTE_QUALITY_TREND_CRITICAL"],
        "reason_text": "Route-quality critical detected.",
        "trend": {
            "status": "critical",
            "direction": "degrading",
            "sample_count": 120,
        },
        "evaluated_at": "2026-02-26T00:00:00+00:00",
    }

    original_guard_summary = api_server._get_chat_route_quality_guard_summary
    original_store = api_server._CHAT_ROUTE_EVENT_STORE
    capture_store = _CaptureEventStore()
    api_server._CHAT_ROUTE_EVENT_STORE = capture_store

    warning_after_bridge: Dict[str, Any] = {}
    critical_after_bridge: Dict[str, Any] = {}
    try:
        api_server._get_chat_route_quality_guard_summary = lambda force_refresh=False: dict(warning_summary)
        warning_route = {
            "path": "path-b",
            "risk_level": "unknown",
            "outer_readonly_hit": False,
            "core_escalation": False,
            "router_decision": {
                "delegation_intent": "general_assistance",
                "prompt_profile": "outer_general",
                "injection_mode": "normal",
            },
        }
        warning_guarded = api_server._apply_chat_route_quality_guard(dict(warning_route))
        warning_after_budget = api_server._apply_path_b_clarify_budget(
            dict(warning_guarded),
            session_id=warning_session_id,
        )
        warning_after_bridge = api_server._apply_outer_core_session_bridge(
            warning_after_budget,
            outer_session_id=warning_session_id,
        )
        api_server._emit_chat_route_guard_event(warning_after_bridge, session_id=warning_session_id)

        api_server._get_chat_route_quality_guard_summary = lambda force_refresh=False: dict(critical_summary)
        critical_route = {
            "path": "path-a",
            "risk_level": "write_repo",
            "outer_readonly_hit": True,
            "core_escalation": False,
            "router_decision": {
                "delegation_intent": "read_only_exploration",
                "prompt_profile": "outer_readonly_summary",
                "injection_mode": "minimal",
            },
        }
        critical_guarded = api_server._apply_chat_route_quality_guard(dict(critical_route))
        critical_after_budget = api_server._apply_path_b_clarify_budget(
            dict(critical_guarded),
            session_id=critical_session_id,
        )
        critical_after_bridge = api_server._apply_outer_core_session_bridge(
            critical_after_budget,
            outer_session_id=critical_session_id,
        )
        api_server._emit_chat_route_guard_event(critical_after_bridge, session_id=critical_session_id)
    finally:
        api_server._get_chat_route_quality_guard_summary = original_guard_summary
        api_server._CHAT_ROUTE_EVENT_STORE = original_store

    event_types = [str(item.get("event_type") or "") for item in capture_store.rows]
    checks = {
        "warning_guard_sets_path_b_limit_override_zero": (
            warning_after_bridge.get("path_b_clarify_limit_override") == 0
            and bool(warning_after_bridge.get("route_quality_guard_applied"))
        ),
        "warning_guard_budget_override_escalates_to_core": (
            str(warning_after_bridge.get("path") or "") == "path-c"
            and str(warning_after_bridge.get("path_b_budget_reason") or "")
            == "clarify_budget_guard_override_auto_escalate_core"
        ),
        "critical_guard_forces_suspicious_path_a_to_core": (
            str(critical_after_bridge.get("path") or "") == "path-c"
            and bool(critical_after_bridge.get("core_escalation"))
            and "ROUTE_QUALITY_CRITICAL_FORCE_CORE"
            in (critical_after_bridge.get("route_quality_guard_reason_codes") or [])
        ),
        "guard_events_emitted_for_warning_and_critical": (
            "RouteQualityGuardEscalatedWarning" in event_types
            and "RouteQualityGuardEscalatedCritical" in event_types
        ),
        "incident_severity_map_covers_guard_events": (
            api_server._OPS_INCIDENT_EVENT_SEVERITY.get("RouteQualityGuardEscalatedWarning") == "warning"
            and api_server._OPS_INCIDENT_EVENT_SEVERITY.get("RouteQualityGuardEscalatedCritical") == "critical"
        ),
    }
    passed = all(checks.values())

    report: Dict[str, Any] = {
        "task_id": "NGA-WS28-012",
        "scenario": "route_quality_guard_enforcement_ws28_012",
        "generated_at": _utc_now(),
        "repo_root": _to_unix(root),
        "passed": passed,
        "checks": checks,
        "samples": {
            "warning_route": warning_after_bridge,
            "critical_route": critical_after_bridge,
            "guard_events": capture_store.rows,
        },
    }

    output = _resolve_path(root, output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["output_file"] = _to_unix(output)

    for session_id in (warning_session_id, critical_session_id):
        api_server.message_manager.delete_session(session_id)
        api_server.message_manager.delete_session(f"{session_id}__core")

    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WS28-012 route-quality guard enforcement checks")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSON report path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when checks fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_ws28_route_quality_guard_enforcement_ws28_012(
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
