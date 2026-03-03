"""Ops (observability) route handlers extracted from api_server.py.

Phase 1 of the api_server.py split. All endpoints are read-only aggregation
queries that assemble runtime posture, MCP fabric, memory graph, workflow
events, incident, and evidence payloads.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from ._shared import (
    OPS_STATUS_RANK as _OPS_STATUS_RANK,
    ops_max_status as _ops_max_status,
    ops_metric_status as _ops_metric_status,
    ops_parse_iso_datetime as _ops_parse_iso_datetime,
    ops_read_json_file as _shared_ops_read_json_file,
    ops_repo_root as _ops_repo_root,
    ops_safe_int as _ops_safe_int,
    ops_status_to_severity as _ops_status_to_severity,
    ops_unix_path as _ops_unix_path,
    ops_utc_iso_now as _ops_utc_iso_now,
)

from core.supervisor.watchdog_daemon import WatchdogDaemon

try:
    from system.config import get_embla_system_config
except ImportError:
    def get_embla_system_config() -> dict:  # type: ignore[misc]
        return {}

logger = logging.getLogger(__name__)
_OPS_APP_CONTEXT: Dict[str, Any] = {"app": None}

__all__ = [
    "_OPS_AUDIT_LEDGER_RELATIVE_PATH",
    "_OPS_BRAINSTEM_HEARTBEAT_RELATIVE_PATH",
    "_OPS_BRAINSTEM_HEARTBEAT_STALE_CRITICAL_SECONDS",
    "_OPS_BRAINSTEM_HEARTBEAT_STALE_WARNING_SECONDS",
    "_OPS_BUDGET_GUARD_STALE_CRITICAL_SECONDS",
    "_OPS_BUDGET_GUARD_STALE_WARNING_SECONDS",
    "_OPS_BUDGET_GUARD_STATE_RELATIVE_PATH",
    "_OPS_INCIDENT_EVENT_SEVERITY",
    "_OPS_KILLSWITCH_GUARD_STATE_RELATIVE_PATH",
    "_OPS_PROCESS_GUARD_STALE_CRITICAL_SECONDS",
    "_OPS_PROCESS_GUARD_STALE_WARNING_SECONDS",
    "_OPS_PROCESS_GUARD_STATE_RELATIVE_PATH",
    "_OPS_REQUIRED_REPORT_DEFINITIONS",
    "_OPS_STATUS_RANK",
    "_OPS_WATCHDOG_DAEMON_STALE_CRITICAL_SECONDS",
    "_OPS_WATCHDOG_DAEMON_STALE_WARNING_SECONDS",
    "_OPS_WATCHDOG_DAEMON_STATE_RELATIVE_PATH",
    "_ops_build_agentic_loop_completion_summary",
    "_ops_build_audit_ledger_summary",
    "_ops_build_brainstem_control_plane_summary",
    "_ops_build_budget_guard_summary",
    "_ops_build_event_database_summary",
    "_ops_build_evidence_index_payload",
    "_ops_build_execution_bridge_governance_summary",
    "_ops_build_immutable_dna_summary",
    "_ops_build_incidents_latest_payload",
    "_ops_build_killswitch_guard_summary",
    "_ops_build_mcp_fabric_payload",
    "_ops_build_process_guard_summary",
    "_ops_build_response",
    "_ops_build_route_quality_summary",
    "_ops_build_route_quality_trend",
    "_ops_build_runtime_posture_payload",
    "_ops_build_vision_multimodal_summary",
    "_ops_build_watchdog_daemon_summary",
    "_bind_ops_app_context",
    "_ops_build_workflow_events_payload",
    "_ops_collect_required_reports",
    "_ops_compact_event_payload",
    "_ops_extract_execution_bridge_governance",
    "_ops_extract_failed_checks",
    "_ops_max_status",
    "_ops_metric_status",
    "_ops_parse_iso_datetime",
    "_ops_read_event_rows",
    "_ops_read_event_rows_from_db",
    "_ops_read_json_file",
    "_ops_repo_root",
    "_ops_resolve_audit_ledger_path",
    "_ops_resolve_control_plane_mode_summary",
    "_ops_resolve_event_db_path",
    "_ops_route_event_status",
    "_ops_safe_int",
    "_ops_status_to_severity",
    "_ops_unix_path",
    "_ops_utc_iso_now",
]


def _bind_ops_app_context(app: Any) -> None:
    """Bind FastAPI app instance to routes_ops to avoid lazy import cycles."""
    _OPS_APP_CONTEXT["app"] = app


def _ops_read_json_file(path: Path) -> Dict[str, Any]:
    """Compatibility wrapper: always return dict for existing ops call-sites."""
    payload = _shared_ops_read_json_file(path)
    return payload if isinstance(payload, dict) else {}


router = APIRouter()


def _ops_route_event_status(payload: Dict[str, Any]) -> str:
    outer_readonly = bool(payload.get("outer_readonly_hit"))
    readonly_exposed = bool(payload.get("readonly_write_tool_exposed"))
    readonly_selected_count = _ops_safe_int(payload.get("readonly_write_tool_selected_count"), default=0)
    readonly_exposure_hit = outer_readonly and (readonly_exposed or readonly_selected_count > 0)
    guard_status = _ops_status_to_severity(str(payload.get("route_quality_guard_status") or "unknown"))
    if readonly_exposure_hit:
        return "critical"
    if guard_status == "critical":
        return "critical"
    if bool(payload.get("path_b_budget_escalated")):
        return "warning"
    if guard_status == "warning" and bool(payload.get("route_quality_guard_applied")):
        return "warning"
    if bool(payload.get("core_session_created")):
        return "warning"
    return "ok"


def _ops_build_route_quality_trend(
    events_file: Path,
    *,
    window_size: int = 20,
    max_windows: int = 6,
) -> Dict[str, Any]:
    step = max(1, int(window_size))
    max_window_count = max(1, int(max_windows))
    rows = _ops_read_event_rows(events_file, limit=max(200, step * max_window_count * 8))
    prompt_rows: List[Dict[str, Any]] = []
    for row in rows:
        if str(row.get("event_type") or "").strip() != "PromptInjectionComposed":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        prompt_rows.append(
            {
                "timestamp": str(row.get("timestamp") or ""),
                "payload": payload,
            }
        )

    if not prompt_rows:
        return {
            "status": "unknown",
            "direction": "unknown",
            "volatility": None,
            "windows": [],
            "sample_count": 0,
            "window_size": step,
            "reason": "no_prompt_injection_events",
        }

    capped = prompt_rows[-step * max_window_count :]
    windows: List[Dict[str, Any]] = []
    for start in range(0, len(capped), step):
        segment = capped[start : start + step]
        if not segment:
            continue
        statuses = [_ops_route_event_status(item.get("payload") if isinstance(item.get("payload"), dict) else {}) for item in segment]
        total = len(statuses)
        critical_count = sum(1 for status in statuses if status == "critical")
        warning_count = sum(1 for status in statuses if status == "warning")
        ok_count = sum(1 for status in statuses if status == "ok")
        window_status = _ops_max_status(statuses)
        score = ((ok_count * 1.0) + (warning_count * 0.6) + (critical_count * 0.25)) / float(total)
        windows.append(
            {
                "start_at": str(segment[0].get("timestamp") or ""),
                "end_at": str(segment[-1].get("timestamp") or ""),
                "sample_count": total,
                "status": window_status,
                "critical_ratio": critical_count / float(total),
                "warning_ratio": warning_count / float(total),
                "score": round(score, 4),
            }
        )

    if not windows:
        return {
            "status": "unknown",
            "direction": "unknown",
            "volatility": None,
            "windows": [],
            "sample_count": 0,
            "window_size": step,
            "reason": "no_window_aggregates",
        }

    latest = windows[-1]
    first = windows[0]
    delta = float(latest.get("score") or 0.0) - float(first.get("score") or 0.0)
    if delta >= 0.08:
        direction = "improving"
    elif delta <= -0.08:
        direction = "degrading"
    else:
        direction = "stable"

    transitions = 0
    for idx in range(1, len(windows)):
        prev_status = str(windows[idx - 1].get("status") or "unknown")
        current_status = str(windows[idx].get("status") or "unknown")
        if prev_status != current_status:
            transitions += 1
    volatility = (transitions / float(len(windows) - 1)) if len(windows) > 1 else 0.0

    latest_status = _ops_status_to_severity(str(latest.get("status") or "unknown"))
    trend_status = latest_status
    if latest_status == "ok":
        if direction == "degrading" and float(latest.get("score") or 0.0) < 0.7:
            trend_status = "warning"
        elif volatility >= 0.7:
            trend_status = "warning"
    elif latest_status == "warning" and direction == "degrading" and float(latest.get("score") or 0.0) < 0.5:
        trend_status = "critical"

    return {
        "status": trend_status,
        "direction": direction,
        "volatility": round(volatility, 4),
        "windows": windows,
        "sample_count": len(capped),
        "window_size": step,
        "latest_window_status": latest_status,
    }


def _ops_build_route_quality_summary(
    metrics: Dict[str, Any],
    *,
    trend: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    outer_readonly = metrics.get("outer_readonly_hit_rate") if isinstance(metrics.get("outer_readonly_hit_rate"), dict) else {}
    readonly_exposure = (
        metrics.get("readonly_write_tool_exposure_rate")
        if isinstance(metrics.get("readonly_write_tool_exposure_rate"), dict)
        else {}
    )
    route_distribution = (
        metrics.get("chat_route_path_distribution")
        if isinstance(metrics.get("chat_route_path_distribution"), dict)
        else {}
    )
    path_b_budget_escalation = (
        metrics.get("path_b_budget_escalation_rate")
        if isinstance(metrics.get("path_b_budget_escalation_rate"), dict)
        else {}
    )
    core_session_creation = (
        metrics.get("core_session_creation_rate")
        if isinstance(metrics.get("core_session_creation_rate"), dict)
        else {}
    )

    status_map = {
        "outer_readonly_hit_rate": _ops_metric_status(outer_readonly),
        "readonly_write_tool_exposure_rate": _ops_metric_status(readonly_exposure),
        "chat_route_path_distribution": _ops_metric_status(route_distribution),
        "path_b_budget_escalation_rate": _ops_metric_status(path_b_budget_escalation),
        "core_session_creation_rate": _ops_metric_status(core_session_creation),
    }
    trend_payload = trend if isinstance(trend, dict) else {}
    trend_status = _ops_status_to_severity(str(trend_payload.get("status") or "unknown"))
    overall_status = _ops_max_status([*list(status_map.values()), trend_status])

    reason_codes: List[str] = []
    if status_map["readonly_write_tool_exposure_rate"] == "critical":
        reason_codes.append("READONLY_WRITE_EXPOSURE_CRITICAL")
    elif status_map["readonly_write_tool_exposure_rate"] == "warning":
        reason_codes.append("READONLY_WRITE_EXPOSURE_WARNING")

    if status_map["path_b_budget_escalation_rate"] == "critical":
        reason_codes.append("PATH_B_BUDGET_ESCALATION_CRITICAL")
    elif status_map["path_b_budget_escalation_rate"] == "warning":
        reason_codes.append("PATH_B_BUDGET_ESCALATION_WARNING")

    if status_map["core_session_creation_rate"] == "critical":
        reason_codes.append("CORE_SESSION_CREATION_CRITICAL")
    elif status_map["core_session_creation_rate"] == "warning":
        reason_codes.append("CORE_SESSION_CREATION_WARNING")

    if status_map["outer_readonly_hit_rate"] == "critical":
        reason_codes.append("OUTER_READONLY_HIT_CRITICAL")
    elif status_map["outer_readonly_hit_rate"] == "warning":
        reason_codes.append("OUTER_READONLY_HIT_WARNING")

    direction = str(trend_payload.get("direction") or "unknown")
    if trend_status == "critical":
        reason_codes.append("ROUTE_QUALITY_TREND_CRITICAL")
    elif trend_status == "warning":
        reason_codes.append("ROUTE_QUALITY_TREND_WARNING")
    if direction == "degrading":
        reason_codes.append("ROUTE_QUALITY_TREND_DEGRADING")

    if not reason_codes and overall_status == "ok":
        reason_codes.append("ROUTE_QUALITY_HEALTHY")
    if not reason_codes and overall_status == "unknown":
        reason_codes.append("ROUTE_QUALITY_SIGNAL_UNKNOWN")

    reason_text = ""
    if overall_status == "critical":
        reason_text = "Route-quality guard is critical; investigate routing drift, exposure, and escalation pressure."
    elif overall_status == "warning":
        reason_text = "Route-quality guard is warning; monitor exposure, escalation, and core session churn."
    elif overall_status == "ok":
        reason_text = "Route-quality guard is healthy."
    else:
        reason_text = "Route-quality signals are insufficient."

    return {
        "status": overall_status,
        "reason_codes": reason_codes,
        "reason_text": reason_text,
        "signal_status": status_map,
        "path_ratios": route_distribution.get("path_ratios", {}) if isinstance(route_distribution, dict) else {},
        "trend": trend_payload,
    }


_OPS_REQUIRED_REPORT_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "id": "full_chain_m0_m12",
        "label": "Release Closure Chain M0-M12",
        "relative_path": "scratch/reports/release_closure_chain_full_m0_m12_result.json",
        "gate_level": "hard",
    },
    {
        "id": "cutover_status_ws27_002",
        "label": "WS27-002 Cutover Status",
        "relative_path": "scratch/reports/ws27_subagent_cutover_status_ws27_002.json",
        "gate_level": "hard",
    },
    {
        "id": "oob_drill_ws27_003",
        "label": "WS27-003 OOB Repair Drill",
        "relative_path": "scratch/reports/ws27_oob_repair_drill_ws27_003.json",
        "gate_level": "hard",
    },
    {
        "id": "doc_consistency_ws27_005",
        "label": "WS27-005 Doc Consistency",
        "relative_path": "scratch/reports/ws27_m12_doc_consistency_ws27_005.json",
        "gate_level": "hard",
    },
    {
        "id": "wallclock_acceptance_ws27_001",
        "label": "WS27-001 72h Wallclock Acceptance",
        "relative_path": "scratch/reports/ws27_72h_wallclock_acceptance_ws27_001.json",
        "gate_level": "soft",
    },
    {
        "id": "release_report_ws27_006",
        "label": "WS27-006 Release Report",
        "relative_path": "scratch/reports/phase3_full_release_report_ws27_006.json",
        "gate_level": "soft",
    },
    {
        "id": "signoff_chain_ws27_006",
        "label": "WS27-006 Signoff Chain",
        "relative_path": "scratch/reports/release_phase3_full_signoff_chain_ws27_006_result.json",
        "gate_level": "soft",
    },
]

_OPS_INCIDENT_EVENT_SEVERITY: Dict[str, str] = {
    "IncidentOpened": "critical",
    "SubAgentRuntimeAutoDegraded": "critical",
    "LeaseLost": "critical",
    "RouteQualityGuardEscalatedCritical": "critical",
    "RouteArbiterGuardEscalatedCritical": "critical",
    "ProcessGuardZombieDetected": "critical",
    "KillSwitchEngaged": "critical",
    "BudgetGuardTriggered": "critical",
    "ReleaseRollbackTriggered": "critical",
    "ReleaseRollbackFailed": "critical",
    "RuntimeFuseTriggeredCritical": "critical",
    "AgenticLoopCompletionNotSubmitted": "critical",
    "ImmutableDNATamperDetected": "critical",
    "SubAgentRuntimeFailOpenBlocked": "warning",
    "SubAgentRuntimeFailOpen": "warning",
    "RouteQualityGuardEscalatedWarning": "warning",
    "RouteArbiterGuardEscalatedWarning": "warning",
    "ProcessGuardOrphanReaped": "warning",
    "RuntimeFuseTriggeredWarning": "warning",
    "VisionMultimodalQAError": "warning",
}

_OPS_BRAINSTEM_HEARTBEAT_RELATIVE_PATH = Path("scratch/runtime/brainstem_control_plane_heartbeat_ws23_001.json")
_OPS_BRAINSTEM_HEARTBEAT_STALE_WARNING_SECONDS = 120.0
_OPS_BRAINSTEM_HEARTBEAT_STALE_CRITICAL_SECONDS = 300.0
_OPS_WATCHDOG_DAEMON_STATE_RELATIVE_PATH = Path("scratch/runtime/watchdog_daemon_state_ws28_025.json")
_OPS_WATCHDOG_DAEMON_STALE_WARNING_SECONDS = 120.0
_OPS_WATCHDOG_DAEMON_STALE_CRITICAL_SECONDS = 300.0
_OPS_PROCESS_GUARD_STATE_RELATIVE_PATH = Path("scratch/runtime/process_guard_state_ws28_028.json")
_OPS_PROCESS_GUARD_STALE_WARNING_SECONDS = 120.0
_OPS_PROCESS_GUARD_STALE_CRITICAL_SECONDS = 300.0
_OPS_KILLSWITCH_GUARD_STATE_RELATIVE_PATH = Path("scratch/runtime/killswitch_guard_state_ws28_028.json")
_OPS_BUDGET_GUARD_STATE_RELATIVE_PATH = Path("scratch/runtime/budget_guard_state_ws28_028.json")
_OPS_BUDGET_GUARD_STALE_WARNING_SECONDS = 120.0
_OPS_BUDGET_GUARD_STALE_CRITICAL_SECONDS = 300.0
_OPS_AUDIT_LEDGER_RELATIVE_PATH = Path("scratch/runtime/audit_ledger.jsonl")


def _ops_resolve_audit_ledger_path(repo_root: Path) -> Path:
    try:
        embla_system = get_embla_system_config()
    except Exception:
        embla_system = {}
    security = embla_system.get("security") if isinstance(embla_system, dict) else {}
    ledger_raw = str(security.get("audit_ledger_file") or "").strip() if isinstance(security, dict) else ""
    if ledger_raw:
        candidate = Path(ledger_raw)
        if candidate.is_absolute():
            return candidate
        return repo_root / candidate
    return repo_root / _OPS_AUDIT_LEDGER_RELATIVE_PATH


def _ops_resolve_control_plane_mode_summary() -> Dict[str, Any]:
    """Resolve runtime control-plane mode (single vs dual)."""
    legacy_enabled = False
    source = "config.default"
    try:
        from system.config import get_config

        cfg = get_config()
        auto_cfg = getattr(cfg, "autonomous", None)
        if auto_cfg is not None:
            legacy_enabled = bool(getattr(auto_cfg, "legacy_system_agent_enabled", False))
            source = "system.config.autonomous.legacy_system_agent_enabled"
    except Exception:
        legacy_enabled = False

    runtime_mode = "dual_control_plane" if legacy_enabled else "single_control_plane"
    status = "warning" if legacy_enabled else "ok"
    reason_code = "LEGACY_AUTONOMOUS_ENABLED" if legacy_enabled else "LEGACY_AUTONOMOUS_DISABLED"
    reason_text = (
        "legacy autonomous system agent is enabled alongside chat pipeline."
        if legacy_enabled
        else "legacy autonomous system agent is disabled; chat pipeline is the single runtime control-plane."
    )
    return {
        "status": status,
        "runtime_mode": runtime_mode,
        "single_control_plane": not legacy_enabled,
        "legacy_autonomous_enabled": legacy_enabled,
        "legacy_autonomous_status": "enabled" if legacy_enabled else "disabled",
        "legacy_autonomous": "enabled" if legacy_enabled else "disabled",
        "chat_pipeline_status": "enabled",
        "reason_code": reason_code,
        "reason_text": reason_text,
        "source": source,
    }


def _ops_extract_failed_checks(payload: Dict[str, Any]) -> List[str]:
    checks = payload.get("checks")
    if not isinstance(checks, dict):
        return []
    failed: List[str] = []
    for key, value in checks.items():
        if value is False:
            failed.append(str(key))
    return failed


def _ops_build_brainstem_control_plane_summary(repo_root: Path) -> Dict[str, Any]:
    heartbeat_file = repo_root / _OPS_BRAINSTEM_HEARTBEAT_RELATIVE_PATH
    heartbeat_payload = _ops_read_json_file(heartbeat_file)
    generated_at = str(heartbeat_payload.get("generated_at") or "")
    generated_ts = _ops_parse_iso_datetime(generated_at)
    now_ts = time.time()
    heartbeat_age_seconds: Optional[float] = None
    if generated_ts is not None:
        heartbeat_age_seconds = max(0.0, round(now_ts - generated_ts, 3))

    raw_unhealthy_services = heartbeat_payload.get("unhealthy_services")
    unhealthy_services: List[str] = []
    if isinstance(raw_unhealthy_services, list):
        unhealthy_services = [str(item) for item in raw_unhealthy_services if str(item).strip()]

    healthy_value = heartbeat_payload.get("healthy")
    healthy: Optional[bool]
    if isinstance(healthy_value, bool):
        healthy = healthy_value
    else:
        healthy = None

    status = "unknown"
    reason_code = "BRAINSTEM_HEARTBEAT_MISSING"
    reason_text = "Brainstem control-plane heartbeat file is missing."
    if heartbeat_file.exists():
        status = "unknown"
        reason_code = "BRAINSTEM_HEARTBEAT_NO_SIGNAL"
        reason_text = "Brainstem heartbeat file exists but lacks valid health signal."
        if generated_ts is None:
            status = "warning"
            reason_code = "BRAINSTEM_HEARTBEAT_TIMESTAMP_INVALID"
            reason_text = "Brainstem heartbeat timestamp is missing or invalid."
        elif heartbeat_age_seconds is not None and heartbeat_age_seconds > float(_OPS_BRAINSTEM_HEARTBEAT_STALE_CRITICAL_SECONDS):
            status = "critical"
            reason_code = "BRAINSTEM_HEARTBEAT_STALE_CRITICAL"
            reason_text = "Brainstem heartbeat is stale beyond critical threshold."
        elif heartbeat_age_seconds is not None and heartbeat_age_seconds > float(_OPS_BRAINSTEM_HEARTBEAT_STALE_WARNING_SECONDS):
            status = "warning"
            reason_code = "BRAINSTEM_HEARTBEAT_STALE_WARNING"
            reason_text = "Brainstem heartbeat is stale beyond warning threshold."
        elif healthy is False or unhealthy_services:
            status = "critical"
            reason_code = "BRAINSTEM_HEALTH_UNHEALTHY"
            reason_text = "Brainstem daemon reports unhealthy services."
        elif healthy is True:
            status = "ok"
            reason_code = "OK"
            reason_text = "Brainstem daemon heartbeat is healthy."
        else:
            status = "warning"
            reason_code = "BRAINSTEM_HEALTH_UNKNOWN"
            reason_text = "Brainstem heartbeat is fresh but healthy flag is missing."

    return {
        "status": _ops_status_to_severity(status),
        "reason_code": reason_code,
        "reason_text": reason_text,
        "heartbeat_file": _ops_unix_path(heartbeat_file),
        "exists": heartbeat_file.exists(),
        "generated_at": generated_at,
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "stale_warning_seconds": float(_OPS_BRAINSTEM_HEARTBEAT_STALE_WARNING_SECONDS),
        "stale_critical_seconds": float(_OPS_BRAINSTEM_HEARTBEAT_STALE_CRITICAL_SECONDS),
        "healthy": healthy,
        "service_count": _ops_safe_int(heartbeat_payload.get("service_count"), default=0),
        "tick": _ops_safe_int(heartbeat_payload.get("tick"), default=0),
        "mode": str(heartbeat_payload.get("mode") or ""),
        "pid": _ops_safe_int(heartbeat_payload.get("pid"), default=0),
        "state_file": str(heartbeat_payload.get("state_file") or ""),
        "spec_file": str(heartbeat_payload.get("spec_file") or ""),
        "unhealthy_services": unhealthy_services,
    }


def _ops_build_watchdog_daemon_summary(repo_root: Path) -> Dict[str, Any]:
    state_file = repo_root / _OPS_WATCHDOG_DAEMON_STATE_RELATIVE_PATH
    state = WatchdogDaemon.read_daemon_state(
        state_file,
        stale_warning_seconds=float(_OPS_WATCHDOG_DAEMON_STALE_WARNING_SECONDS),
        stale_critical_seconds=float(_OPS_WATCHDOG_DAEMON_STALE_CRITICAL_SECONDS),
    )
    action_payload = state.get("action") if isinstance(state.get("action"), dict) else {}
    snapshot = state.get("snapshot") if isinstance(state.get("snapshot"), dict) else {}
    return {
        "status": _ops_status_to_severity(str(state.get("status") or "unknown")),
        "reason_code": str(state.get("reason_code") or ""),
        "reason_text": str(state.get("reason_text") or ""),
        "state_file": str(state.get("state_file") or _ops_unix_path(state_file)),
        "exists": bool(state_file.exists()),
        "generated_at": str(state.get("generated_at") or ""),
        "heartbeat_age_seconds": state.get("heartbeat_age_seconds"),
        "stale_warning_seconds": float(state.get("stale_warning_seconds") or _OPS_WATCHDOG_DAEMON_STALE_WARNING_SECONDS),
        "stale_critical_seconds": float(
            state.get("stale_critical_seconds") or _OPS_WATCHDOG_DAEMON_STALE_CRITICAL_SECONDS
        ),
        "state": str(state.get("state") or ""),
        "tick": _ops_safe_int(state.get("tick"), default=0),
        "pid": _ops_safe_int(state.get("pid"), default=0),
        "mode": str(state.get("mode") or ""),
        "warn_only": bool(state.get("warn_only")),
        "threshold_hit": bool(state.get("threshold_hit")),
        "action": action_payload,
        "snapshot": snapshot,
    }


def _ops_build_process_guard_summary(repo_root: Path) -> Dict[str, Any]:
    state_file = repo_root / _OPS_PROCESS_GUARD_STATE_RELATIVE_PATH
    try:
        from core.supervisor.process_guard import ProcessGuardDaemon

        state = ProcessGuardDaemon.read_daemon_state(
            state_file,
            stale_warning_seconds=float(_OPS_PROCESS_GUARD_STALE_WARNING_SECONDS),
            stale_critical_seconds=float(_OPS_PROCESS_GUARD_STALE_CRITICAL_SECONDS),
        )
    except Exception as exc:
        state = {
            "status": "critical",
            "reason_code": "PROCESS_GUARD_READ_FAILED",
            "reason_text": f"process guard state read failed: {exc}",
            "state_file": _ops_unix_path(state_file),
        }
    return {
        "status": _ops_status_to_severity(str(state.get("status") or "unknown")),
        "reason_code": str(state.get("reason_code") or ""),
        "reason_text": str(state.get("reason_text") or ""),
        "state_file": str(state.get("state_file") or _ops_unix_path(state_file)),
        "exists": bool(state_file.exists()),
        "generated_at": str(state.get("generated_at") or ""),
        "heartbeat_age_seconds": state.get("heartbeat_age_seconds"),
        "stale_warning_seconds": float(
            state.get("stale_warning_seconds") or _OPS_PROCESS_GUARD_STALE_WARNING_SECONDS
        ),
        "stale_critical_seconds": float(
            state.get("stale_critical_seconds") or _OPS_PROCESS_GUARD_STALE_CRITICAL_SECONDS
        ),
        "running_jobs": _ops_safe_int(state.get("running_jobs"), default=0),
        "orphan_jobs": _ops_safe_int(state.get("orphan_jobs"), default=0),
        "stale_jobs": _ops_safe_int(state.get("stale_jobs"), default=0),
        "orphan_reaped_count": _ops_safe_int(state.get("orphan_reaped_count"), default=0),
    }


def _ops_build_killswitch_guard_summary(repo_root: Path) -> Dict[str, Any]:
    state_file = repo_root / _OPS_KILLSWITCH_GUARD_STATE_RELATIVE_PATH
    try:
        from core.security import KillSwitchController

        state = KillSwitchController(state_file=state_file).read_state()
    except Exception as exc:
        state = {
            "status": "critical",
            "reason_code": "KILLSWITCH_STATE_READ_FAILED",
            "reason_text": f"killswitch guard state read failed: {exc}",
            "state_file": _ops_unix_path(state_file),
            "active": False,
        }
    status = _ops_status_to_severity(str(state.get("status") or "unknown"))
    active = bool(state.get("active"))
    reason_code = str(state.get("reason_code") or "")
    reason_text = str(state.get("reason_text") or "")
    if active and status in {"ok", "unknown"}:
        status = "critical"
        reason_code = "KILLSWITCH_ENGAGED"
        reason_text = "KillSwitch state is active."
    return {
        "status": status,
        "reason_code": reason_code,
        "reason_text": reason_text,
        "state_file": str(state.get("state_file") or _ops_unix_path(state_file)),
        "exists": bool(state_file.exists()),
        "generated_at": str(state.get("generated_at") or ""),
        "active": active,
        "mode": str(state.get("mode") or ""),
        "approval_ticket": str(state.get("approval_ticket") or ""),
        "requested_by": str(state.get("requested_by") or ""),
        "commands_count": _ops_safe_int(state.get("commands_count"), default=0),
    }


def _ops_build_budget_guard_summary(repo_root: Path) -> Dict[str, Any]:
    state_file = repo_root / _OPS_BUDGET_GUARD_STATE_RELATIVE_PATH
    try:
        from core.security import BudgetGuardController

        state = BudgetGuardController(state_file=state_file).read_state(
            stale_warning_seconds=float(_OPS_BUDGET_GUARD_STALE_WARNING_SECONDS),
            stale_critical_seconds=float(_OPS_BUDGET_GUARD_STALE_CRITICAL_SECONDS),
        )
    except Exception as exc:
        state = {
            "status": "critical",
            "reason_code": "BUDGET_GUARD_STATE_READ_FAILED",
            "reason_text": f"budget guard state read failed: {exc}",
            "state_file": _ops_unix_path(state_file),
        }
    return {
        "status": _ops_status_to_severity(str(state.get("status") or "unknown")),
        "reason_code": str(state.get("reason_code") or ""),
        "reason_text": str(state.get("reason_text") or ""),
        "state_file": str(state.get("state_file") or _ops_unix_path(state_file)),
        "exists": bool(state_file.exists()),
        "generated_at": str(state.get("generated_at") or ""),
        "heartbeat_age_seconds": state.get("heartbeat_age_seconds"),
        "stale_warning_seconds": float(
            state.get("stale_warning_seconds") or _OPS_BUDGET_GUARD_STALE_WARNING_SECONDS
        ),
        "stale_critical_seconds": float(
            state.get("stale_critical_seconds") or _OPS_BUDGET_GUARD_STALE_CRITICAL_SECONDS
        ),
        "action": str(state.get("action") or ""),
        "task_id": str(state.get("task_id") or ""),
        "tool_name": str(state.get("tool_name") or ""),
        "details": state.get("details") if isinstance(state.get("details"), dict) else {},
    }


def _ops_build_immutable_dna_summary() -> Dict[str, Any]:
    app_obj = _OPS_APP_CONTEXT.get("app")
    if app_obj is None:
        # Fallback path for direct test imports before api_server binds app context.
        try:
            import apiserver.api_server as _api  # type: ignore

            app_obj = getattr(_api, "app", None)
        except Exception:
            app_obj = None

    app_state = getattr(app_obj, "state", None) if app_obj is not None else None
    preflight = getattr(app_state, "immutable_dna_preflight", None)
    monitor_state_file_raw = str(getattr(app_state, "immutable_dna_integrity_state_file", "") or "").strip()
    if monitor_state_file_raw:
        monitor_state_file = Path(monitor_state_file_raw)
    else:
        monitor_state_file = (_ops_repo_root() / Path("scratch/runtime/immutable_dna_integrity_state_ws30_001.json")).resolve()

    monitor_state: Dict[str, Any]
    try:
        from core.security import ImmutableDNAIntegrityMonitor

        monitor_state = ImmutableDNAIntegrityMonitor.read_state(monitor_state_file)
    except Exception as exc:
        monitor_state = {
            "status": "warning",
            "reason_code": "IMMUTABLE_DNA_MONITOR_STATE_READ_FAILED",
            "reason_text": f"immutable DNA monitor state read failed: {exc}",
            "state_file": str(monitor_state_file).replace("\\", "/"),
        }
    monitor_status = _ops_status_to_severity(str(monitor_state.get("status") or "unknown"))

    if not isinstance(preflight, dict):
        reason_code = "IMMUTABLE_DNA_PREFLIGHT_MISSING"
        reason_text = "Immutable DNA startup preflight is missing."
        status = "unknown"
        if monitor_status == "critical":
            status = "critical"
            reason_code = str(monitor_state.get("reason_code") or "IMMUTABLE_DNA_MONITOR_CRITICAL")
            reason_text = str(monitor_state.get("reason_text") or "Immutable DNA monitor detected integrity violation.")
        elif monitor_status == "warning":
            status = "warning"
            reason_code = str(monitor_state.get("reason_code") or "IMMUTABLE_DNA_MONITOR_WARNING")
            reason_text = str(monitor_state.get("reason_text") or "Immutable DNA monitor requires attention.")
        return {
            "status": _ops_status_to_severity(status),
            "reason_code": reason_code,
            "reason_text": reason_text,
            "enabled": True,
            "required": True,
            "passed": False,
            "exists": False,
            "manifest_path": "",
            "audit_file": "",
            "manifest_hash": str(monitor_state.get("manifest_hash") or ""),
            "verify": {},
            "monitor_status": monitor_status,
            "monitor": monitor_state,
        }

    enabled = bool(preflight.get("enabled", True))
    required = bool(preflight.get("required", True))
    passed = bool(preflight.get("passed", False))
    reason = str(preflight.get("reason") or "")
    manifest_path = str(preflight.get("manifest_path") or "")
    audit_file = str(preflight.get("audit_file") or "")
    verify = preflight.get("verify") if isinstance(preflight.get("verify"), dict) else {}
    manifest_hash = str(
        preflight.get("manifest_hash")
        or verify.get("manifest_hash")
        or monitor_state.get("manifest_hash")
        or ""
    )

    if not enabled:
        status = "warning"
        reason_code = "IMMUTABLE_DNA_RUNTIME_DISABLED"
        reason_text = "Immutable DNA runtime injection is disabled."
    elif passed:
        status = "ok"
        reason_code = "OK"
        reason_text = "Immutable DNA preflight passed."
    elif required:
        status = "critical"
        reason_code = "IMMUTABLE_DNA_PREFLIGHT_FAILED"
        reason_text = f"Immutable DNA preflight failed: {reason or 'unknown'}"
    else:
        status = "warning"
        reason_code = "IMMUTABLE_DNA_PREFLIGHT_FAILED_OPTIONAL"
        reason_text = f"Immutable DNA preflight failed (non-blocking): {reason or 'unknown'}"

    if monitor_status == "critical":
        status = "critical"
        reason_code = str(monitor_state.get("reason_code") or "IMMUTABLE_DNA_MONITOR_CRITICAL")
        reason_text = str(monitor_state.get("reason_text") or "Immutable DNA monitor detected integrity violation.")
    elif monitor_status == "warning" and _ops_status_to_severity(status) == "ok":
        status = "warning"
        reason_code = str(monitor_state.get("reason_code") or "IMMUTABLE_DNA_MONITOR_WARNING")
        reason_text = str(monitor_state.get("reason_text") or "Immutable DNA monitor requires attention.")

    return {
        "status": _ops_status_to_severity(status),
        "reason_code": reason_code,
        "reason_text": reason_text,
        "enabled": enabled,
        "required": required,
        "passed": passed,
        "exists": bool(preflight),
        "manifest_path": manifest_path,
        "audit_file": audit_file,
        "manifest_hash": manifest_hash,
        "verify": verify,
        "monitor_status": monitor_status,
        "monitor": monitor_state,
    }


def _ops_build_audit_ledger_summary(repo_root: Path) -> Dict[str, Any]:
    ledger_file = _ops_resolve_audit_ledger_path(repo_root)
    if not ledger_file.exists():
        return {
            "status": "unknown",
            "reason_code": "AUDIT_LEDGER_MISSING",
            "reason_text": "Audit ledger file is missing.",
            "ledger_file": _ops_unix_path(ledger_file),
            "exists": False,
            "checked_count": 0,
            "error_count": 0,
            "errors": [],
            "latest_generated_at": "",
            "latest_change_id": "",
            "latest_record_type": "",
        }

    try:
        from core.security import AuditLedger

        ledger = AuditLedger(ledger_file=ledger_file)
        records = ledger.read_records()
        verify = ledger.verify_chain()
    except Exception as exc:
        return {
            "status": "critical",
            "reason_code": "AUDIT_LEDGER_READ_FAILED",
            "reason_text": f"Audit ledger read/verify failed: {exc}",
            "ledger_file": _ops_unix_path(ledger_file),
            "exists": True,
            "checked_count": 0,
            "error_count": 1,
            "errors": [str(exc)],
            "latest_generated_at": "",
            "latest_change_id": "",
            "latest_record_type": "",
        }

    latest_generated_at = ""
    latest_change_id = ""
    latest_record_type = ""
    if records:
        latest = records[-1]
        latest_generated_at = str(latest.generated_at or "")
        latest_change_id = str(latest.change_id or "")
        latest_record_type = str(latest.record_type or "")

    if verify.passed and verify.checked_count >= 1:
        status = "ok"
        reason_code = "OK"
        reason_text = "Audit ledger hash chain is valid."
    elif verify.passed and verify.checked_count == 0:
        status = "warning"
        reason_code = "AUDIT_LEDGER_EMPTY"
        reason_text = "Audit ledger exists but has no valid records."
    else:
        status = "critical"
        reason_code = "AUDIT_LEDGER_CHAIN_INVALID"
        reason_text = "Audit ledger hash chain verification failed."

    return {
        "status": _ops_status_to_severity(status),
        "reason_code": reason_code,
        "reason_text": reason_text,
        "ledger_file": _ops_unix_path(ledger_file),
        "exists": True,
        "checked_count": int(verify.checked_count),
        "error_count": len(list(verify.errors or [])),
        "errors": list(verify.errors or []),
        "latest_generated_at": latest_generated_at,
        "latest_change_id": latest_change_id,
        "latest_record_type": latest_record_type,
    }


def _ops_collect_required_reports(repo_root: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for spec in _OPS_REQUIRED_REPORT_DEFINITIONS:
        relative_path = Path(str(spec["relative_path"]))
        absolute_path = repo_root / relative_path
        exists = absolute_path.exists()
        payload = _ops_read_json_file(absolute_path) if exists else {}
        passed_value = payload.get("passed")
        passed: Optional[bool]
        if isinstance(passed_value, bool):
            passed = passed_value
        else:
            passed = None
        failed_checks = _ops_extract_failed_checks(payload)
        status = "missing"
        if exists and passed is True:
            status = "passed"
        elif exists and passed is False:
            status = "failed"
        elif exists:
            status = "unknown"

        mtime_iso = ""
        try:
            if exists:
                from datetime import datetime, timezone

                mtime_iso = datetime.fromtimestamp(absolute_path.stat().st_mtime, tz=timezone.utc).isoformat()
        except OSError:
            mtime_iso = ""

        rows.append(
            {
                "id": str(spec["id"]),
                "label": str(spec["label"]),
                "gate_level": str(spec["gate_level"]),
                "path": _ops_unix_path(absolute_path),
                "exists": exists,
                "status": status,
                "passed": passed,
                "generated_at": str(payload.get("generated_at") or ""),
                "modified_at": mtime_iso,
                "scenario": str(payload.get("scenario") or payload.get("task_id") or ""),
                "failed_checks": failed_checks,
            }
        )
    return rows


def _ops_build_response(
    *,
    data: Dict[str, Any],
    severity: str,
    source_reports: Optional[List[str]] = None,
    source_endpoints: Optional[List[str]] = None,
    reason_code: Optional[str] = None,
    reason_text: Optional[str] = None,
    status: str = "success",
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "status": str(status or "success"),
        "generated_at": _ops_utc_iso_now(),
        "data": data,
        "severity": str(severity or "unknown"),
        "source_reports": list(source_reports or []),
        "source_endpoints": list(source_endpoints or []),
    }
    if reason_code:
        payload["reason_code"] = str(reason_code)
    if reason_text:
        payload["reason_text"] = str(reason_text)
    return payload


def _ops_build_runtime_posture_payload(events_limit: int = 5000) -> Dict[str, Any]:
    try:
        from scripts.export_slo_snapshot import build_snapshot

        repo_root = _ops_repo_root()
        snapshot = build_snapshot(repo_root=repo_root, events_limit=max(1, int(events_limit)))
    except Exception as exc:
        logger.error(f"构建 runtime posture 聚合失败: {exc}")
        raise

    metrics = snapshot.get("metrics") if isinstance(snapshot.get("metrics"), dict) else {}
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    threshold_profile = snapshot.get("threshold_profile") if isinstance(snapshot.get("threshold_profile"), dict) else {}
    sources = snapshot.get("sources") if isinstance(snapshot.get("sources"), dict) else {}
    events_file_raw = str(sources.get("events_file") or "").strip()
    events_file = Path(events_file_raw) if events_file_raw else Path("__missing_events_file__.jsonl")
    if events_file_raw and not events_file.is_absolute():
        events_file = _ops_repo_root() / events_file
    route_quality_trend = _ops_build_route_quality_trend(events_file, window_size=20, max_windows=6)
    execution_bridge_governance = _ops_build_execution_bridge_governance_summary(
        events_file=events_file,
        limit=max(200, int(events_limit)),
        issues_limit=20,
    )
    execution_bridge_governance_status = _ops_status_to_severity(str(execution_bridge_governance.get("status") or "unknown"))
    agentic_loop_completion = _ops_build_agentic_loop_completion_summary(
        events_file=events_file,
        limit=max(200, int(events_limit)),
    )
    agentic_loop_completion_status = _ops_status_to_severity(str(agentic_loop_completion.get("status") or "unknown"))
    vision_multimodal = _ops_build_vision_multimodal_summary(
        events_file=events_file,
        limit=max(200, int(events_limit)),
    )
    vision_multimodal_status = _ops_status_to_severity(str(vision_multimodal.get("status") or "unknown"))

    repo_root = _ops_repo_root()
    brainstem_control_plane = _ops_build_brainstem_control_plane_summary(repo_root)
    brainstem_status = _ops_status_to_severity(str(brainstem_control_plane.get("status") or "unknown"))
    control_plane_mode = _ops_resolve_control_plane_mode_summary()
    control_plane_mode_status = _ops_status_to_severity(str(control_plane_mode.get("status") or "unknown"))
    watchdog_daemon = _ops_build_watchdog_daemon_summary(repo_root)
    watchdog_daemon_status = _ops_status_to_severity(str(watchdog_daemon.get("status") or "unknown"))
    process_guard = _ops_build_process_guard_summary(repo_root)
    process_guard_status = _ops_status_to_severity(str(process_guard.get("status") or "unknown"))
    killswitch_guard = _ops_build_killswitch_guard_summary(repo_root)
    killswitch_guard_status = _ops_status_to_severity(str(killswitch_guard.get("status") or "unknown"))
    budget_guard = _ops_build_budget_guard_summary(repo_root)
    budget_guard_status = _ops_status_to_severity(str(budget_guard.get("status") or "unknown"))
    immutable_dna = _ops_build_immutable_dna_summary()
    immutable_dna_status = _ops_status_to_severity(str(immutable_dna.get("status") or "unknown"))
    audit_ledger = _ops_build_audit_ledger_summary(repo_root)
    audit_ledger_status = _ops_status_to_severity(str(audit_ledger.get("status") or "unknown"))

    metric_status = summary.get("metric_status") if isinstance(summary.get("metric_status"), dict) else {}
    snapshot_overall_status = str(summary.get("overall_status") or "unknown")
    overall_status = _ops_max_status(
        [
            snapshot_overall_status,
            control_plane_mode_status,
            brainstem_status,
            watchdog_daemon_status,
            process_guard_status,
            killswitch_guard_status,
            budget_guard_status,
            immutable_dna_status,
            audit_ledger_status,
            execution_bridge_governance_status,
            agentic_loop_completion_status,
            vision_multimodal_status,
        ]
    )
    severity = _ops_status_to_severity(overall_status)

    ws26_runtime_report = repo_root / "scratch" / "reports" / "ws26_runtime_snapshot_ws26_002.json"
    source_reports: List[str] = []
    ws26_runtime_report_payload: Dict[str, Any] = {}

    if ws26_runtime_report.exists():
        source_reports.append(_ops_unix_path(ws26_runtime_report))
        try:
            loaded_payload = json.loads(ws26_runtime_report.read_text(encoding="utf-8"))
            if isinstance(loaded_payload, dict):
                ws26_runtime_report_payload = loaded_payload
        except (OSError, json.JSONDecodeError):
            pass

    for key in ("events_file", "events_db", "workflow_db", "global_mutex_state", "autonomous_config"):
        path_value = sources.get(key)
        if isinstance(path_value, str) and path_value.strip():
            source_reports.append(path_value.replace("\\", "/"))

    if bool(brainstem_control_plane.get("exists")):
        source_reports.append(str(brainstem_control_plane.get("heartbeat_file") or ""))
    if bool(watchdog_daemon.get("exists")):
        source_reports.append(str(watchdog_daemon.get("state_file") or ""))
    if bool(process_guard.get("exists")):
        source_reports.append(str(process_guard.get("state_file") or ""))
    if bool(killswitch_guard.get("exists")):
        source_reports.append(str(killswitch_guard.get("state_file") or ""))
    if bool(budget_guard.get("exists")):
        source_reports.append(str(budget_guard.get("state_file") or ""))
    if str(immutable_dna.get("manifest_path") or "").strip():
        source_reports.append(str(immutable_dna.get("manifest_path") or ""))
    if str(immutable_dna.get("audit_file") or "").strip():
        source_reports.append(str(immutable_dna.get("audit_file") or ""))
    immutable_dna_monitor = immutable_dna.get("monitor") if isinstance(immutable_dna.get("monitor"), dict) else {}
    if str(immutable_dna_monitor.get("state_file") or "").strip():
        source_reports.append(str(immutable_dna_monitor.get("state_file") or ""))
    if bool(audit_ledger.get("exists")) and str(audit_ledger.get("ledger_file") or "").strip():
        source_reports.append(str(audit_ledger.get("ledger_file") or ""))

    response_data: Dict[str, Any] = {
        "summary": {
            "overall_status": overall_status,
            "metric_status": metric_status,
            "route_quality": _ops_build_route_quality_summary(metrics, trend=route_quality_trend),
            "control_plane_mode_status": control_plane_mode_status,
            "control_plane_mode": str(control_plane_mode.get("runtime_mode") or ""),
            "single_control_plane": bool(control_plane_mode.get("single_control_plane")),
            "legacy_autonomous_enabled": bool(control_plane_mode.get("legacy_autonomous_enabled")),
            "legacy_autonomous_status": str(control_plane_mode.get("legacy_autonomous_status") or "unknown"),
            "legacy_autonomous": str(control_plane_mode.get("legacy_autonomous") or ""),
            "brainstem_control_plane_status": brainstem_status,
            "watchdog_daemon_status": watchdog_daemon_status,
            "process_guard_status": process_guard_status,
            "killswitch_guard_status": killswitch_guard_status,
            "budget_guard_status": budget_guard_status,
            "immutable_dna_status": immutable_dna_status,
            "audit_ledger_status": audit_ledger_status,
            "execution_bridge_governance_status": execution_bridge_governance_status,
            "execution_bridge_governance_reason_codes": list(execution_bridge_governance.get("reason_codes") or []),
            "agentic_loop_completion_status": agentic_loop_completion_status,
            "vision_multimodal_status": vision_multimodal_status,
        },
        "metrics": {
            "runtime_rollout": metrics.get("runtime_rollout", {}),
            "runtime_fail_open": metrics.get("runtime_fail_open", {}),
            "runtime_lease": metrics.get("runtime_lease", {}),
            "queue_depth": metrics.get("queue_depth", {}),
            "lock_status": metrics.get("lock_status", {}),
            "disk_watermark_ratio": metrics.get("disk_watermark_ratio", {}),
            "error_rate": metrics.get("error_rate", {}),
            "latency_p95_ms": metrics.get("latency_p95_ms", {}),
            "prompt_slice_count_by_layer": metrics.get("prompt_slice_count_by_layer", {}),
            "outer_readonly_hit_rate": metrics.get("outer_readonly_hit_rate", {}),
            "readonly_write_tool_exposure_rate": metrics.get("readonly_write_tool_exposure_rate", {}),
            "chat_route_path_distribution": metrics.get("chat_route_path_distribution", {}),
            "path_b_budget_escalation_rate": metrics.get("path_b_budget_escalation_rate", {}),
            "core_session_creation_rate": metrics.get("core_session_creation_rate", {}),
            "control_plane_mode": {
                "status": control_plane_mode_status,
                "value": 0 if bool(control_plane_mode.get("single_control_plane")) else 1,
                "runtime_mode": str(control_plane_mode.get("runtime_mode") or ""),
                "single_control_plane": bool(control_plane_mode.get("single_control_plane")),
                "legacy_autonomous_enabled": bool(control_plane_mode.get("legacy_autonomous_enabled")),
                "legacy_autonomous_status": str(control_plane_mode.get("legacy_autonomous_status") or "unknown"),
                "legacy_autonomous": str(control_plane_mode.get("legacy_autonomous") or ""),
                "reason_code": str(control_plane_mode.get("reason_code") or ""),
            },
            "brainstem_heartbeat": {
                "status": brainstem_status,
                "value": brainstem_control_plane.get("heartbeat_age_seconds"),
                "healthy": brainstem_control_plane.get("healthy"),
                "service_count": brainstem_control_plane.get("service_count"),
                "stale_warning_seconds": brainstem_control_plane.get("stale_warning_seconds"),
                "stale_critical_seconds": brainstem_control_plane.get("stale_critical_seconds"),
                "tick": brainstem_control_plane.get("tick"),
            },
            "watchdog_daemon": {
                "status": watchdog_daemon_status,
                "value": watchdog_daemon.get("heartbeat_age_seconds"),
                "tick": watchdog_daemon.get("tick"),
                "threshold_hit": watchdog_daemon.get("threshold_hit"),
                "warn_only": watchdog_daemon.get("warn_only"),
                "stale_warning_seconds": watchdog_daemon.get("stale_warning_seconds"),
                "stale_critical_seconds": watchdog_daemon.get("stale_critical_seconds"),
                "reason_code": watchdog_daemon.get("reason_code"),
            },
            "process_guard_orphan_jobs": {
                "status": process_guard_status,
                "value": process_guard.get("orphan_jobs"),
                "running_jobs": process_guard.get("running_jobs"),
                "stale_jobs": process_guard.get("stale_jobs"),
                "orphan_reaped_count": process_guard.get("orphan_reaped_count"),
                "reason_code": process_guard.get("reason_code"),
            },
            "killswitch_guard": {
                "status": killswitch_guard_status,
                "active": killswitch_guard.get("active"),
                "mode": killswitch_guard.get("mode"),
                "commands_count": killswitch_guard.get("commands_count"),
                "reason_code": killswitch_guard.get("reason_code"),
            },
            "budget_guard": {
                "status": budget_guard_status,
                "value": budget_guard.get("heartbeat_age_seconds"),
                "action": budget_guard.get("action"),
                "task_id": budget_guard.get("task_id"),
                "tool_name": budget_guard.get("tool_name"),
                "reason_code": budget_guard.get("reason_code"),
            },
            "immutable_dna": {
                "status": immutable_dna_status,
                "enabled": immutable_dna.get("enabled"),
                "required": immutable_dna.get("required"),
                "passed": immutable_dna.get("passed"),
                "reason_code": immutable_dna.get("reason_code"),
                "manifest_hash": immutable_dna.get("manifest_hash"),
            },
            "audit_ledger": {
                "status": audit_ledger_status,
                "value": audit_ledger.get("checked_count"),
                "error_count": audit_ledger.get("error_count"),
                "reason_code": audit_ledger.get("reason_code"),
                "latest_generated_at": audit_ledger.get("latest_generated_at"),
                "latest_record_type": audit_ledger.get("latest_record_type"),
            },
            "execution_bridge_rejection_ratio": {
                "status": execution_bridge_governance_status,
                "value": execution_bridge_governance.get("rejection_ratio"),
                "subtask_total": execution_bridge_governance.get("subtask_total"),
                "subtask_rejected": execution_bridge_governance.get("subtask_rejected"),
            },
            "execution_bridge_governance_warning_ratio": {
                "status": execution_bridge_governance_status,
                "value": execution_bridge_governance.get("governed_warning_ratio"),
                "governed_rows_count": execution_bridge_governance.get("governed_rows_count"),
                "governed_warning_count": execution_bridge_governance.get("governed_warning_count"),
                "governed_critical_count": execution_bridge_governance.get("governed_critical_count"),
            },
            "agentic_loop_completion_not_submitted_ratio": {
                "status": agentic_loop_completion_status,
                "value": agentic_loop_completion.get("not_submitted_ratio"),
                "submitted_count": agentic_loop_completion.get("submitted_count"),
                "not_submitted_count": agentic_loop_completion.get("not_submitted_count"),
                "total_count": agentic_loop_completion.get("total_count"),
                "reason_code": agentic_loop_completion.get("reason_code"),
            },
            "vision_multimodal_fallback_ratio": {
                "status": vision_multimodal_status,
                "value": vision_multimodal.get("fallback_ratio"),
                "success_count": vision_multimodal.get("success_count"),
                "fallback_count": vision_multimodal.get("fallback_count"),
                "error_count": vision_multimodal.get("error_count"),
                "total_count": vision_multimodal.get("total_count"),
                "reason_code": vision_multimodal.get("reason_code"),
            },
        },
        "threshold_profile": threshold_profile,
        "sources": sources,
        "control_plane_mode": control_plane_mode,
        "brainstem_control_plane": brainstem_control_plane,
        "watchdog_daemon": watchdog_daemon,
        "process_guard": process_guard,
        "killswitch_guard": killswitch_guard,
        "budget_guard": budget_guard,
        "immutable_dna": immutable_dna,
        "audit_ledger": audit_ledger,
        "execution_bridge_governance": execution_bridge_governance,
        "agentic_loop_completion": agentic_loop_completion,
        "vision_multimodal": vision_multimodal,
    }
    if ws26_runtime_report_payload:
        response_data["ws26_runtime_snapshot_report"] = ws26_runtime_report_payload

    reason_code: Optional[str] = None
    reason_text: Optional[str] = None
    if brainstem_status == "critical":
        reason_code = "BRAINSTEM_CONTROL_PLANE_CRITICAL"
        reason_text = str(brainstem_control_plane.get("reason_text") or "Brainstem control-plane is unhealthy.")
    elif watchdog_daemon_status == "critical":
        reason_code = "WATCHDOG_DAEMON_CRITICAL"
        reason_text = str(watchdog_daemon.get("reason_text") or "Watchdog daemon reports critical state.")
    elif process_guard_status == "critical":
        reason_code = "PROCESS_GUARD_CRITICAL"
        reason_text = str(process_guard.get("reason_text") or "Process guard reports zombie/orphan process risk.")
    elif killswitch_guard_status == "critical":
        reason_code = "KILLSWITCH_GUARD_CRITICAL"
        reason_text = str(killswitch_guard.get("reason_text") or "KillSwitch guard is active.")
    elif budget_guard_status == "critical":
        reason_code = "BUDGET_GUARD_CRITICAL"
        reason_text = str(budget_guard.get("reason_text") or "Budget guard reports critical stop signal.")
    elif immutable_dna_status == "critical":
        reason_code = "IMMUTABLE_DNA_CRITICAL"
        reason_text = str(immutable_dna.get("reason_text") or "Immutable DNA preflight failed.")
    elif audit_ledger_status == "critical":
        reason_code = "AUDIT_LEDGER_CRITICAL"
        reason_text = str(audit_ledger.get("reason_text") or "Audit ledger integrity check failed.")
    elif execution_bridge_governance_status == "critical":
        reason_code = "EXECUTION_BRIDGE_GOVERNANCE_CRITICAL"
        reason_text = "Execution bridge governance has critical rejections; check role guards and policy contracts."
    elif agentic_loop_completion_status == "critical":
        reason_code = "AGENTIC_LOOP_COMPLETION_CRITICAL"
        reason_text = str(
            agentic_loop_completion.get("reason_text")
            or "Agentic loop completion gate contains completion_not_submitted events."
        )
    elif brainstem_status == "warning":
        reason_code = "BRAINSTEM_CONTROL_PLANE_WARNING"
        reason_text = str(brainstem_control_plane.get("reason_text") or "Brainstem control-plane requires attention.")
    elif watchdog_daemon_status == "warning":
        reason_code = "WATCHDOG_DAEMON_WARNING"
        reason_text = str(watchdog_daemon.get("reason_text") or "Watchdog daemon requires attention.")
    elif process_guard_status == "warning":
        reason_code = "PROCESS_GUARD_WARNING"
        reason_text = str(process_guard.get("reason_text") or "Process guard requires attention.")
    elif killswitch_guard_status == "warning":
        reason_code = "KILLSWITCH_GUARD_WARNING"
        reason_text = str(killswitch_guard.get("reason_text") or "KillSwitch guard requires attention.")
    elif budget_guard_status == "warning":
        reason_code = "BUDGET_GUARD_WARNING"
        reason_text = str(budget_guard.get("reason_text") or "Budget guard requires attention.")
    elif immutable_dna_status == "warning":
        reason_code = "IMMUTABLE_DNA_WARNING"
        reason_text = str(immutable_dna.get("reason_text") or "Immutable DNA preflight requires attention.")
    elif audit_ledger_status == "warning":
        reason_code = "AUDIT_LEDGER_WARNING"
        reason_text = str(audit_ledger.get("reason_text") or "Audit ledger requires attention.")
    elif execution_bridge_governance_status == "warning":
        reason_code = "EXECUTION_BRIDGE_GOVERNANCE_WARNING"
        reason_text = "Execution bridge governance has warning signals; review semantic/path guard drift."
    elif agentic_loop_completion_status == "warning":
        reason_code = "AGENTIC_LOOP_COMPLETION_WARNING"
        reason_text = str(agentic_loop_completion.get("reason_text") or "Agentic loop completion signals require attention.")
    elif control_plane_mode_status == "warning":
        reason_code = "CONTROL_PLANE_MODE_WARNING"
        reason_text = str(control_plane_mode.get("reason_text") or "Runtime is in dual control-plane mode.")
    elif vision_multimodal_status == "warning":
        reason_code = "VISION_MULTIMODAL_WARNING"
        reason_text = str(
            vision_multimodal.get("reason_text")
            or "Vision multimodal QA fallback detected; verify endpoint availability."
        )
    elif severity == "unknown":
        reason_code = "RUNTIME_SIGNAL_UNKNOWN"
        reason_text = "Runtime posture lacks enough signal coverage; verify events/workflow inputs."

    return _ops_build_response(
        data=response_data,
        severity=severity,
        source_reports=sorted(set(source_reports)),
        source_endpoints=[],
        reason_code=reason_code,
        reason_text=reason_text,
    )


def _ops_build_mcp_fabric_payload() -> Dict[str, Any]:
    registry_status: Dict[str, Any]
    reason_code: Optional[str] = None
    reason_text: Optional[str] = None

    try:
        from mcpserver.mcp_registry import auto_register_mcp, get_registry_status

        auto_register_mcp()
        registry_status = get_registry_status()
    except Exception as exc:
        logger.warning(f"获取 MCP registry 状态失败: {exc}")
        registry_status = {
            "registered_services": 0,
            "isolated_worker_services": 0,
            "rejected_plugin_manifests": 0,
            "cached_manifests": 0,
            "service_names": [],
            "isolated_worker_names": [],
            "rejected_plugin_names": [],
        }
        reason_code = "MCP_REGISTRY_UNAVAILABLE"
        reason_text = f"MCP registry status unavailable: {exc}"

    runtime_snapshot = _build_mcp_runtime_snapshot(registry_status=registry_status)
    task_snapshot = _build_mcp_task_snapshot(snapshot=runtime_snapshot)
    services_payload = get_mcp_services()
    services = services_payload.get("services") if isinstance(services_payload, dict) else []
    if not isinstance(services, list):
        services = []

    total_services = len(services)
    available_services = sum(1 for item in services if bool(item.get("available")))
    builtin_services = sum(1 for item in services if str(item.get("source") or "").strip().lower() == "builtin")
    mcporter_services = sum(1 for item in services if str(item.get("source") or "").strip().lower() == "mcporter")
    isolated_worker_services = int(registry_status.get("isolated_worker_services") or 0)
    rejected_plugin_manifests = int(registry_status.get("rejected_plugin_manifests") or 0)

    if total_services <= 0 and int(registry_status.get("registered_services") or 0) <= 0:
        severity = "unknown"
        reason_code = reason_code or "MCP_FABRIC_EMPTY"
        reason_text = reason_text or "No builtin or mcporter services discovered."
    elif available_services <= 0:
        severity = "critical"
        reason_code = reason_code or "MCP_FABRIC_UNAVAILABLE"
        reason_text = reason_text or "Services exist but none are currently available."
    elif available_services < total_services or rejected_plugin_manifests > 0:
        severity = "warning"
        if rejected_plugin_manifests > 0 and not reason_code:
            reason_code = "MCP_PLUGIN_REJECTED"
            reason_text = "One or more plugin manifests were rejected by policy."
    else:
        severity = "ok"

    source_reports: List[str] = []
    if MCPORTER_CONFIG_PATH.exists():
        source_reports.append(_ops_unix_path(MCPORTER_CONFIG_PATH))

    response_data = {
        "summary": {
            "total_services": total_services,
            "available_services": available_services,
            "builtin_services": builtin_services,
            "mcporter_services": mcporter_services,
            "isolated_worker_services": isolated_worker_services,
            "rejected_plugin_manifests": rejected_plugin_manifests,
        },
        "runtime_snapshot": runtime_snapshot,
        "registry": registry_status,
        "tasks": task_snapshot,
        "services": services,
    }

    return _ops_build_response(
        data=response_data,
        severity=severity,
        source_reports=source_reports,
        source_endpoints=["/mcp/status", "/mcp/services", "/mcp/tasks"],
        reason_code=reason_code,
        reason_text=reason_text,
    )

def _ops_resolve_event_db_path(events_file: Path) -> Path:
    from core.event_bus.topic_bus import resolve_topic_db_path_from_mirror

    return resolve_topic_db_path_from_mirror(events_file)


def _ops_read_event_rows_from_db(events_db: Path, *, limit: int) -> List[Dict[str, Any]]:
    if not events_db.exists() or limit <= 0:
        return []
    import sqlite3

    rows: List[Dict[str, Any]] = []
    try:
        conn = sqlite3.connect(str(events_db))
        conn.row_factory = sqlite3.Row
        query_rows = conn.execute(
            """
            SELECT envelope_json
            FROM topic_event
            ORDER BY seq DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
        conn.close()
    except Exception as exc:
        logger.debug(f"读取事件数据库失败，降级文件读取: {exc}")
        return []

    for row in reversed(query_rows):
        try:
            payload = json.loads(str(row["envelope_json"] or "{}"))
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append({**payload, "payload": dict(payload.get("data") or {})})
    return rows


def _ops_read_event_rows(events_file: Path, *, limit: int) -> List[Dict[str, Any]]:
    if limit <= 0:
        return []

    events_db = _ops_resolve_event_db_path(events_file)
    db_rows = _ops_read_event_rows_from_db(events_db, limit=max(1, int(limit)))

    file_rows: List[Dict[str, Any]] = []
    if events_file.exists():
        lines = events_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        for line in lines[-max(1, int(limit)) :]:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                file_rows.append(payload)

    merged: List[Dict[str, Any]] = []
    dedupe: set[str] = set()
    for row in (db_rows + file_rows):
        event_id = str(row.get("event_id") or "").strip()
        event_type = str(row.get("event_type") or "").strip()
        timestamp = str(row.get("timestamp") or "").strip()
        dedupe_key = event_id or f"{event_type}|{timestamp}|{json.dumps(row.get('payload', {}), ensure_ascii=False, sort_keys=True)}"
        if dedupe_key in dedupe:
            continue
        dedupe.add(dedupe_key)
        merged.append(row)

    merged.sort(key=lambda item: _ops_parse_iso_datetime(item.get("timestamp")) or 0.0)
    if len(merged) > int(limit):
        merged = merged[-int(limit) :]
    return merged


def _ops_build_event_database_summary(
    events_file: Path,
    *,
    max_partition_rows: int = 12,
    max_topic_rows: int = 12,
) -> Dict[str, Any]:
    try:
        events_db = _ops_resolve_event_db_path(events_file)
    except Exception as exc:
        return {
            "status": "unknown",
            "reason_code": "EVENT_DB_PATH_RESOLVE_FAILED",
            "reason_text": str(exc),
            "db_path": str(events_file).replace("\\", "/"),
            "exists": False,
            "size_bytes": 0,
            "total_rows": 0,
            "latest_seq": None,
            "latest_timestamp": "",
            "latest_event_type": "",
            "latest_topic": "",
            "partition_count": 0,
            "partitions": [],
            "top_topics": [],
        }

    summary: Dict[str, Any] = {
        "status": "unknown",
        "reason_code": "EVENT_DB_MISSING",
        "reason_text": "Event topic database file is missing.",
        "db_path": _ops_unix_path(events_db),
        "exists": bool(events_db.exists()),
        "size_bytes": 0,
        "total_rows": 0,
        "latest_seq": None,
        "latest_timestamp": "",
        "latest_event_type": "",
        "latest_topic": "",
        "partition_count": 0,
        "partitions": [],
        "top_topics": [],
    }

    if not events_db.exists():
        return summary

    try:
        summary["size_bytes"] = _ops_safe_int(events_db.stat().st_size, default=0)
    except OSError:
        summary["size_bytes"] = 0

    import sqlite3

    conn: Optional[sqlite3.Connection] = None
    try:
        conn = sqlite3.connect(str(events_db))
        conn.row_factory = sqlite3.Row

        total_row = conn.execute("SELECT COUNT(1) AS total_rows FROM topic_event").fetchone()
        latest_row = conn.execute(
            """
            SELECT seq, timestamp, event_type, topic
            FROM topic_event
            ORDER BY timestamp DESC, seq DESC
            LIMIT 1
            """
        ).fetchone()
        partition_count_row = conn.execute(
            "SELECT COUNT(DISTINCT coalesce(partition_ym, '')) AS partition_count FROM topic_event"
        ).fetchone()
        partition_rows = conn.execute(
            """
            SELECT coalesce(partition_ym, '') AS partition_ym, COUNT(1) AS row_count, MAX(timestamp) AS latest_timestamp
            FROM topic_event
            GROUP BY coalesce(partition_ym, '')
            ORDER BY partition_ym DESC
            LIMIT ?
            """,
            (max(1, int(max_partition_rows)),),
        ).fetchall()
        topic_rows = conn.execute(
            """
            SELECT topic, COUNT(1) AS row_count, MAX(timestamp) AS latest_timestamp
            FROM topic_event
            GROUP BY topic
            ORDER BY row_count DESC, topic ASC
            LIMIT ?
            """,
            (max(1, int(max_topic_rows)),),
        ).fetchall()
    except Exception as exc:
        logger.debug(f"查询事件数据库统计失败: {exc}")
        summary["reason_code"] = "EVENT_DB_QUERY_FAILED"
        summary["reason_text"] = str(exc)
        return summary
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    total_rows = _ops_safe_int(total_row["total_rows"] if total_row is not None else 0, default=0)
    partition_count = _ops_safe_int(
        partition_count_row["partition_count"] if partition_count_row is not None else 0,
        default=0,
    )
    latest_seq = _ops_safe_int(latest_row["seq"] if latest_row is not None else None, default=0)
    latest_timestamp = str(latest_row["timestamp"] or "") if latest_row is not None else ""
    latest_event_type = str(latest_row["event_type"] or "") if latest_row is not None else ""
    latest_topic = str(latest_row["topic"] or "") if latest_row is not None else ""

    partitions: List[Dict[str, Any]] = []
    for row in partition_rows:
        partitions.append(
            {
                "partition_ym": str(row["partition_ym"] or ""),
                "row_count": _ops_safe_int(row["row_count"], default=0),
                "latest_timestamp": str(row["latest_timestamp"] or ""),
            }
        )

    top_topics: List[Dict[str, Any]] = []
    for row in topic_rows:
        top_topics.append(
            {
                "topic": str(row["topic"] or ""),
                "row_count": _ops_safe_int(row["row_count"], default=0),
                "latest_timestamp": str(row["latest_timestamp"] or ""),
            }
        )

    if total_rows <= 0:
        status = "unknown"
        reason_code = "EVENT_DB_EMPTY"
        reason_text = "Event topic database exists but no events are stored."
    else:
        status = "ok"
        reason_code = "OK"
        reason_text = "Event topic database is online."

    summary.update(
        {
            "status": status,
            "reason_code": reason_code,
            "reason_text": reason_text,
            "total_rows": total_rows,
            "latest_seq": latest_seq if latest_row is not None else None,
            "latest_timestamp": latest_timestamp,
            "latest_event_type": latest_event_type,
            "latest_topic": latest_topic,
            "partition_count": partition_count,
            "partitions": partitions,
            "top_topics": top_topics,
        }
    )
    return summary


def _ops_compact_event_payload(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    compact: Dict[str, Any] = {}
    for key, value in payload.items():
        if len(compact) >= 8:
            break
        if isinstance(value, (str, int, float, bool)) or value is None:
            compact[str(key)] = value
            continue
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                if len(compact) >= 8:
                    break
                if isinstance(nested_value, (str, int, float, bool)) or nested_value is None:
                    compact[f"{key}.{nested_key}"] = nested_value
    return compact


def _ops_extract_execution_bridge_governance(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    governance: Dict[str, Any] = {}
    for candidate in (
        payload.get("execution_bridge_governance"),
        payload.get("bridge_receipt", {}).get("governance")
        if isinstance(payload.get("bridge_receipt"), dict)
        else {},
        payload.get("execution_bridge_receipt", {}).get("governance")
        if isinstance(payload.get("execution_bridge_receipt"), dict)
        else {},
    ):
        if isinstance(candidate, dict) and candidate:
            governance = dict(candidate)
            break

    if not governance:
        raw_reason = str(payload.get("error") or payload.get("reason") or "").strip()
        if raw_reason.startswith("execution_bridge_"):
            reason_code = "EXECUTION_BRIDGE_REJECTED"
            category = "execution_bridge"
            if raw_reason.startswith("execution_bridge_role_path_violation"):
                reason_code = "ROLE_PATH_VIOLATION"
                category = "path_policy"
            elif raw_reason.startswith("execution_bridge_semantic_toolchain_violation"):
                reason_code = "SEMANTIC_TOOLCHAIN_VIOLATION"
                category = "semantic_toolchain"
            elif raw_reason == "execution_bridge_ops_ticket_required":
                reason_code = "OPS_CHANGE_TICKET_REQUIRED"
                category = "change_control"
            elif raw_reason == "execution_bridge_missing_patch_intent":
                reason_code = "MISSING_PATCH_INTENT"
                category = "patch_intent"
            governance = {
                "status": "critical",
                "severity": "critical",
                "category": category,
                "reason_code": reason_code,
                "reason": raw_reason,
                "executor": str(payload.get("role") or ""),
                "policy_source": str(payload.get("role_executor_policy_source") or ""),
                "violation_count": 0,
                "violations": [],
            }

    if not governance:
        return {}

    violations: List[str] = []
    raw_violations = governance.get("violations")
    if isinstance(raw_violations, list):
        violations = [str(item) for item in raw_violations if str(item).strip()]
    violation_count = _ops_safe_int(governance.get("violation_count"), default=len(violations))
    status = _ops_status_to_severity(str(governance.get("severity") or governance.get("status") or "unknown"))

    return {
        "status": status,
        "severity": status,
        "category": str(governance.get("category") or ""),
        "reason_code": str(governance.get("reason_code") or ""),
        "reason": str(governance.get("reason") or ""),
        "executor": str(governance.get("executor") or ""),
        "policy_source": str(
            governance.get("policy_source") or payload.get("role_executor_policy_source") or ""
        ),
        "strict_role_paths": bool(governance.get("strict_role_paths", False)),
        "strict_semantic_guard": bool(governance.get("strict_semantic_guard", False)),
        "violation_count": max(0, int(violation_count)),
        "violations": violations,
    }


def _ops_build_execution_bridge_governance_summary(
    *,
    events_file: Path,
    limit: int = 5000,
    issues_limit: int = 20,
) -> Dict[str, Any]:
    rows = _ops_read_event_rows(events_file, limit=max(200, int(limit)))
    completed_total = 0
    completed_rejected = 0
    completed_governance_rows: List[Dict[str, Any]] = []
    rejected_governance_rows: List[Dict[str, Any]] = []

    for row in rows:
        event_type = str(row.get("event_type") or "").strip()
        payload = row.get("payload")
        payload_dict = payload if isinstance(payload, dict) else {}

        if event_type == "SubTaskExecutionCompleted":
            completed_total += 1
            if payload_dict.get("success") is False:
                completed_rejected += 1
            governance = _ops_extract_execution_bridge_governance(payload_dict)
            if governance:
                completed_governance_rows.append(
                    {
                        "timestamp": str(row.get("timestamp") or ""),
                        "event_type": event_type,
                        "subtask_id": str(payload_dict.get("subtask_id") or ""),
                        "task_id": str(payload_dict.get("task_id") or ""),
                        "role": str(payload_dict.get("role") or ""),
                        "success": bool(payload_dict.get("success")),
                        "governance": governance,
                    }
                )
            continue

        if event_type == "SubTaskRejected":
            governance = _ops_extract_execution_bridge_governance(payload_dict)
            if governance:
                rejected_governance_rows.append(
                    {
                        "timestamp": str(row.get("timestamp") or ""),
                        "event_type": event_type,
                        "subtask_id": str(payload_dict.get("subtask_id") or ""),
                        "task_id": str(payload_dict.get("task_id") or ""),
                        "role": str(payload_dict.get("role") or ""),
                        "error": str(payload_dict.get("error") or ""),
                        "governance": governance,
                    }
                )

    reference_rows = completed_governance_rows if completed_governance_rows else rejected_governance_rows
    status_counts: Dict[str, int] = {"ok": 0, "warning": 0, "critical": 0, "unknown": 0}
    reason_code_counts: Dict[str, int] = {}
    category_counts: Dict[str, int] = {}
    executor_counts: Dict[str, int] = {}
    policy_source_counts: Dict[str, int] = {}
    governance_warning_count = 0
    governance_critical_count = 0
    latest_issue_at = ""

    for row in reference_rows:
        governance = row.get("governance")
        if not isinstance(governance, dict):
            continue
        status = _ops_status_to_severity(str(governance.get("status") or "unknown"))
        status_counts[status] = int(status_counts.get(status, 0)) + 1
        if status == "warning":
            governance_warning_count += 1
        elif status == "critical":
            governance_critical_count += 1
        if status in {"warning", "critical"}:
            ts = str(row.get("timestamp") or "")
            if (_ops_parse_iso_datetime(ts) or 0.0) >= (_ops_parse_iso_datetime(latest_issue_at) or 0.0):
                latest_issue_at = ts

        reason_code = str(governance.get("reason_code") or "")
        if reason_code:
            reason_code_counts[reason_code] = int(reason_code_counts.get(reason_code, 0)) + 1
        category = str(governance.get("category") or "")
        if category:
            category_counts[category] = int(category_counts.get(category, 0)) + 1
        executor = str(governance.get("executor") or "")
        if executor:
            executor_counts[executor] = int(executor_counts.get(executor, 0)) + 1
        policy_source = str(governance.get("policy_source") or "")
        if policy_source:
            policy_source_counts[policy_source] = int(policy_source_counts.get(policy_source, 0)) + 1

    if governance_critical_count > 0:
        status = "critical"
    elif governance_warning_count > 0:
        status = "warning"
    elif completed_total > 0 or bool(reference_rows):
        status = "ok"
    else:
        status = "unknown"

    rejection_ratio = (completed_rejected / float(completed_total)) if completed_total > 0 else None
    governed_rows_count = len(reference_rows)
    governed_warning_ratio = (
        (governance_warning_count + governance_critical_count) / float(governed_rows_count)
        if governed_rows_count > 0
        else None
    )

    issue_rows = rejected_governance_rows if rejected_governance_rows else [
        item
        for item in completed_governance_rows
        if _ops_status_to_severity(str(item.get("governance", {}).get("status") or "unknown")) in {"warning", "critical"}
    ]
    issue_rows.sort(key=lambda row: _ops_parse_iso_datetime(row.get("timestamp")) or 0.0, reverse=True)
    recent_issues: List[Dict[str, Any]] = []
    for row in issue_rows[: max(1, int(issues_limit))]:
        governance = row.get("governance")
        if not isinstance(governance, dict):
            continue
        recent_issues.append(
            {
                "timestamp": str(row.get("timestamp") or ""),
                "event_type": str(row.get("event_type") or ""),
                "task_id": str(row.get("task_id") or ""),
                "subtask_id": str(row.get("subtask_id") or ""),
                "role": str(row.get("role") or ""),
                "severity": _ops_status_to_severity(str(governance.get("status") or "unknown")),
                "reason_code": str(governance.get("reason_code") or ""),
                "reason": str(governance.get("reason") or ""),
                "category": str(governance.get("category") or ""),
                "executor": str(governance.get("executor") or ""),
                "policy_source": str(governance.get("policy_source") or ""),
                "violation_count": _ops_safe_int(governance.get("violation_count"), default=0),
                "violations": list(governance.get("violations") or []),
                "error": str(row.get("error") or ""),
            }
        )

    reason_codes_sorted = [
        key
        for key, _ in sorted(reason_code_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    if status == "ok" and not reason_codes_sorted:
        reason_codes_sorted = ["EXECUTION_BRIDGE_GOVERNANCE_OK"]
    elif status == "unknown" and not reason_codes_sorted:
        reason_codes_sorted = ["EXECUTION_BRIDGE_GOVERNANCE_UNKNOWN"]

    return {
        "status": status,
        "reason_codes": reason_codes_sorted,
        "reason_code_counts": reason_code_counts,
        "category_counts": category_counts,
        "executor_counts": executor_counts,
        "policy_source_counts": policy_source_counts,
        "subtask_total": completed_total,
        "subtask_rejected": completed_rejected,
        "rejection_ratio": rejection_ratio,
        "governed_rows_count": governed_rows_count,
        "governed_warning_count": governance_warning_count,
        "governed_critical_count": governance_critical_count,
        "governed_warning_ratio": governed_warning_ratio,
        "latest_issue_at": latest_issue_at,
        "recent_issues": recent_issues,
    }


def _ops_build_agentic_loop_completion_summary(
    *,
    events_file: Path,
    limit: int = 5000,
) -> Dict[str, Any]:
    rows = _ops_read_event_rows(events_file, limit=max(200, int(limit)))
    events_db = _ops_resolve_event_db_path(events_file)
    submitted_count = 0
    not_submitted_count = 0
    latest_timestamp = ""
    latest_reason = ""

    for row in rows:
        event_type = str(row.get("event_type") or "").strip()
        if event_type == "AgenticLoopCompletionSubmitted":
            submitted_count += 1
            if not latest_timestamp:
                latest_timestamp = str(row.get("timestamp") or "")
                latest_reason = "submitted_completion"
        elif event_type == "AgenticLoopCompletionNotSubmitted":
            not_submitted_count += 1
            if not latest_timestamp:
                latest_timestamp = str(row.get("timestamp") or "")
                latest_reason = "completion_not_submitted"

    total_count = submitted_count + not_submitted_count
    not_submitted_ratio = float(not_submitted_count) / float(total_count) if total_count > 0 else None

    if total_count <= 0:
        status = "unknown"
        reason_code = "AGENTIC_LOOP_COMPLETION_SIGNAL_EMPTY"
        reason_text = "No agentic loop completion signal captured in runtime events."
    elif not_submitted_count > 0:
        status = "critical"
        reason_code = "AGENTIC_LOOP_COMPLETION_NOT_SUBMITTED_PRESENT"
        reason_text = "Detected completion_not_submitted stop reasons in recent agentic loop sessions."
    else:
        status = "ok"
        reason_code = "OK"
        reason_text = "All observed agentic loop sessions completed via submitted_completion."

    return {
        "status": _ops_status_to_severity(status),
        "reason_code": reason_code,
        "reason_text": reason_text,
        "submitted_count": submitted_count,
        "not_submitted_count": not_submitted_count,
        "total_count": total_count,
        "not_submitted_ratio": not_submitted_ratio,
        "latest_timestamp": latest_timestamp,
        "latest_reason": latest_reason,
        "events_file": _ops_unix_path(events_db if events_db.exists() else events_file),
    }


def _ops_build_vision_multimodal_summary(
    *,
    events_file: Path,
    limit: int = 5000,
) -> Dict[str, Any]:
    rows = _ops_read_event_rows(events_file, limit=max(200, int(limit)))
    events_db = _ops_resolve_event_db_path(events_file)

    success_count = 0
    fallback_count = 0
    error_count = 0
    latest_timestamp = ""
    latest_event_type = ""
    latest_model = ""
    latest_base_url = ""
    latest_fallback_reason = ""

    for row in rows:
        event_type = str(row.get("event_type") or "").strip()
        if event_type not in {
            "VisionMultimodalQASucceeded",
            "VisionMultimodalQAFallback",
            "VisionMultimodalQAError",
        }:
            continue

        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if event_type == "VisionMultimodalQASucceeded":
            success_count += 1
        elif event_type == "VisionMultimodalQAFallback":
            fallback_count += 1
        else:
            error_count += 1

        if not latest_timestamp:
            latest_timestamp = str(row.get("timestamp") or "")
            latest_event_type = event_type
            latest_model = str(payload.get("model") or "")
            latest_base_url = str(payload.get("base_url") or "")
            latest_fallback_reason = str(payload.get("fallback_reason") or "")

    total_count = success_count + fallback_count + error_count
    fallback_ratio = (float(fallback_count) / float(total_count)) if total_count > 0 else None
    error_ratio = (float(error_count) / float(total_count)) if total_count > 0 else None

    if total_count <= 0:
        status = "unknown"
        reason_code = "VISION_MULTIMODAL_SIGNAL_EMPTY"
        reason_text = "No vision multimodal QA signal captured in runtime events."
    elif error_count > 0:
        status = "warning"
        reason_code = "VISION_MULTIMODAL_ERROR_PRESENT"
        reason_text = "Vision multimodal QA errors detected; fallback answer may be used."
    elif fallback_count > 0:
        status = "warning"
        reason_code = "VISION_MULTIMODAL_FALLBACK_PRESENT"
        reason_text = "Vision QA contains metadata fallback sessions; verify multimodal endpoint coverage."
    else:
        status = "ok"
        reason_code = "OK"
        reason_text = "Vision QA sessions are served by multimodal endpoint."

    return {
        "status": _ops_status_to_severity(status),
        "reason_code": reason_code,
        "reason_text": reason_text,
        "success_count": success_count,
        "fallback_count": fallback_count,
        "error_count": error_count,
        "total_count": total_count,
        "fallback_ratio": fallback_ratio,
        "error_ratio": error_ratio,
        "latest_timestamp": latest_timestamp,
        "latest_event_type": latest_event_type,
        "latest_model": latest_model,
        "latest_base_url": latest_base_url,
        "latest_fallback_reason": latest_fallback_reason,
        "events_file": _ops_unix_path(events_db if events_db.exists() else events_file),
    }


def _ops_build_workflow_events_payload(
    *,
    events_limit: int = 5000,
    context_days: int = 7,
    recent_critical_limit: int = 50,
) -> Dict[str, Any]:
    try:
        from scripts.export_slo_snapshot import build_snapshot

        repo_root = Path(__file__).resolve().parent.parent
        snapshot = build_snapshot(repo_root=repo_root, events_limit=max(1, int(events_limit)))
    except Exception as exc:
        logger.error(f"构建 workflow/events 聚合失败: {exc}")
        raise

    metrics = snapshot.get("metrics") if isinstance(snapshot.get("metrics"), dict) else {}
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    sources = snapshot.get("sources") if isinstance(snapshot.get("sources"), dict) else {}
    severity = _ops_status_to_severity(str(summary.get("overall_status") or "unknown"))

    events_file_raw = str(sources.get("events_file") or "").strip()
    events_file = Path(events_file_raw) if events_file_raw else Path("")
    event_rows = _ops_read_event_rows(events_file, limit=max(100, int(events_limit)))
    event_database = _ops_build_event_database_summary(events_file)

    critical_event_types = {
        "SubAgentRuntimeFailOpen",
        "SubAgentRuntimeFailOpenBlocked",
        "SubAgentRuntimeAutoDegraded",
        "LeaseLost",
        "IncidentOpened",
        "VisionMultimodalQAError",
    }
    event_counters = {name: 0 for name in sorted(critical_event_types)}
    recent_critical_events: List[Dict[str, Any]] = []
    for row in event_rows:
        event_type = str(row.get("event_type") or "").strip()
        if event_type not in critical_event_types:
            continue
        event_counters[event_type] = int(event_counters.get(event_type, 0)) + 1
        recent_critical_events.append({
            "timestamp": str(row.get("timestamp") or ""),
            "event_type": event_type,
            "payload_excerpt": _ops_compact_event_payload(row.get("payload")),
        })
    recent_critical_events = recent_critical_events[-max(1, int(recent_critical_limit)) :]

    queue_depth = metrics.get("queue_depth") if isinstance(metrics.get("queue_depth"), dict) else {}
    lock_status = metrics.get("lock_status") if isinstance(metrics.get("lock_status"), dict) else {}
    runtime_lease = metrics.get("runtime_lease") if isinstance(metrics.get("runtime_lease"), dict) else {}

    queue_status = _ops_status_to_severity(str(queue_depth.get("status") or "unknown"))
    if queue_status == "critical":
        severity = "critical"
    elif queue_status == "warning" and severity != "critical":
        severity = "warning"
    elif sum(event_counters.values()) > 0 and severity == "ok":
        severity = "warning"

    # Lazy import to avoid circular dependency — these are api_server singletons
    from apiserver.api_server import message_manager as _mm, _tool_status_store as _tss
    context_stats = _mm.get_context_statistics(max(1, int(context_days)))
    tool_status = _tss.get("current", {"message": "", "visible": False})

    reason_code: Optional[str] = None
    reason_text: Optional[str] = None
    if severity == "critical":
        reason_code = "WORKFLOW_RISK_CRITICAL"
        reason_text = "Critical workflow pressure or high-risk runtime events detected."
    elif severity == "unknown":
        reason_code = "WORKFLOW_SIGNAL_UNKNOWN"
        reason_text = "Workflow signal coverage is insufficient; verify events/workflow data sources."

    source_reports: List[str] = []
    for key in ("events_file", "events_db", "workflow_db", "global_mutex_state"):
        value = sources.get(key)
        if isinstance(value, str) and value.strip():
            source_reports.append(value.replace("\\", "/"))
    db_path = str(event_database.get("db_path") or "").strip()
    if db_path:
        source_reports.append(db_path.replace("\\", "/"))

    response_data = {
        "summary": {
            "overall_status": str(summary.get("overall_status") or "unknown"),
            "events_scanned": _ops_safe_int(sources.get("events_scanned"), default=0),
            "outbox_pending": queue_depth.get("value"),
            "oldest_pending_age_seconds": queue_depth.get("oldest_pending_age_seconds"),
            "critical_events_total": sum(event_counters.values()),
            "event_db_rows": _ops_safe_int(event_database.get("total_rows"), default=0),
            "event_db_partitions": _ops_safe_int(event_database.get("partition_count"), default=0),
            "event_db_latest_at": str(event_database.get("latest_timestamp") or ""),
            "event_db_status": str(event_database.get("status") or "unknown"),
        },
        "queue_depth": queue_depth,
        "lock_status": lock_status,
        "runtime_lease": runtime_lease,
        "event_counters": event_counters,
        "recent_critical_events": recent_critical_events,
        "event_database": event_database,
        "log_context_statistics": context_stats,
        "tool_status": tool_status,
    }

    return _ops_build_response(
        data=response_data,
        severity=severity,
        source_reports=sorted(set(source_reports)),
        source_endpoints=["/logs/context/statistics", "/tool_status"],
        reason_code=reason_code,
        reason_text=reason_text,
    )


async def _ops_build_memory_graph_payload(*, sample_limit: int = 200) -> Dict[str, Any]:
    stats_response = await get_memory_stats()
    memory_stats = stats_response.get("memory_stats") if isinstance(stats_response, dict) else {}
    if not isinstance(memory_stats, dict):
        memory_stats = {}

    quintuples_response = await get_quintuples()
    quintuples = quintuples_response.get("quintuples") if isinstance(quintuples_response, dict) else []
    if not isinstance(quintuples, list):
        quintuples = []

    task_manager = memory_stats.get("task_manager") if isinstance(memory_stats.get("task_manager"), dict) else {}
    pending_tasks = _ops_safe_int(task_manager.get("pending_tasks"), default=0)
    running_tasks = _ops_safe_int(task_manager.get("running_tasks"), default=0)
    failed_tasks = _ops_safe_int(task_manager.get("failed_tasks"), default=0)

    from collections import Counter

    relation_counter: Counter[str] = Counter()
    entity_counter: Counter[str] = Counter()
    graph_sample: List[Dict[str, str]] = []
    for row in quintuples[: max(20, min(1000, int(sample_limit)))]:
        if not isinstance(row, dict):
            continue
        subject = str(row.get("subject") or "")
        subject_type = str(row.get("subject_type") or "")
        predicate = str(row.get("predicate") or "")
        obj = str(row.get("object") or "")
        object_type = str(row.get("object_type") or "")
        if subject:
            entity_counter[subject] += 1
        if obj:
            entity_counter[obj] += 1
        if predicate:
            relation_counter[predicate] += 1
        graph_sample.append({
            "subject": subject,
            "subject_type": subject_type,
            "predicate": predicate,
            "object": obj,
            "object_type": object_type,
        })

    total_quintuples = _ops_safe_int(
        memory_stats.get("total_quintuples"),
        default=_ops_safe_int(quintuples_response.get("count"), default=len(quintuples)),
    )
    active_tasks = _ops_safe_int(memory_stats.get("active_tasks"), default=0)
    vector_index = memory_stats.get("vector_index") if isinstance(memory_stats.get("vector_index"), dict) else {}
    enabled = bool(memory_stats.get("enabled"))
    error_text = str(memory_stats.get("error") or "").strip()

    if error_text:
        severity = "critical"
        reason_code = "MEMORY_BACKEND_ERROR"
        reason_text = error_text
    elif not enabled:
        severity = "unknown"
        reason_code = "MEMORY_DISABLED"
        reason_text = str(memory_stats.get("message") or "Memory subsystem is disabled.")
    elif failed_tasks > 0:
        severity = "warning"
        reason_code = "MEMORY_TASK_FAILURE"
        reason_text = "Memory extraction task failures detected."
    elif total_quintuples <= 0:
        severity = "unknown"
        reason_code = "MEMORY_EMPTY_GRAPH"
        reason_text = "Memory graph currently has no extracted quintuples."
    else:
        severity = "ok"
        reason_code = None
        reason_text = None

    response_data = {
        "summary": {
            "enabled": enabled,
            "total_quintuples": total_quintuples,
            "active_tasks": active_tasks,
            "pending_tasks": pending_tasks,
            "running_tasks": running_tasks,
            "failed_tasks": failed_tasks,
            "graph_sample_size": len(graph_sample),
            "vector_index_state": str(vector_index.get("state") or "unknown"),
            "vector_index_ready": bool(vector_index.get("ready", False)),
        },
        "task_manager": task_manager,
        "vector_index": vector_index,
        "relation_hotspots": [
            {"relation": relation, "count": count} for relation, count in relation_counter.most_common(12)
        ],
        "entity_hotspots": [
            {"entity": entity, "count": count} for entity, count in entity_counter.most_common(12)
        ],
        "graph_sample": graph_sample,
    }

    return _ops_build_response(
        data=response_data,
        severity=severity,
        source_reports=[],
        source_endpoints=["/memory/stats", "/memory/quintuples"],
        reason_code=reason_code,
        reason_text=reason_text,
    )


def _ops_build_evidence_index_payload(*, max_reports: int = 100) -> Dict[str, Any]:
    repo_root = _ops_repo_root()
    reports_dir = repo_root / "scratch" / "reports"
    required_reports = _ops_collect_required_reports(repo_root)

    hard_missing = sum(1 for item in required_reports if item["gate_level"] == "hard" and item["status"] == "missing")
    hard_failed = sum(1 for item in required_reports if item["gate_level"] == "hard" and item["status"] == "failed")
    soft_missing = sum(1 for item in required_reports if item["gate_level"] == "soft" and item["status"] == "missing")
    soft_failed = sum(1 for item in required_reports if item["gate_level"] == "soft" and item["status"] == "failed")
    required_present = sum(1 for item in required_reports if bool(item["exists"]))
    required_passed = sum(1 for item in required_reports if item["status"] == "passed")
    required_unknown = sum(1 for item in required_reports if item["status"] == "unknown")

    reason_code: Optional[str] = None
    reason_text: Optional[str] = None
    if hard_missing > 0:
        severity = "critical"
        reason_code = "EVIDENCE_HARD_REPORT_MISSING"
        reason_text = "One or more hard-gate reports are missing."
    elif hard_failed > 0:
        severity = "critical"
        reason_code = "EVIDENCE_HARD_REPORT_FAILED"
        reason_text = "One or more hard-gate reports are in failed state."
    elif soft_missing > 0 or soft_failed > 0 or required_unknown > 0:
        severity = "warning"
        reason_code = "EVIDENCE_SOFT_GATE_PENDING"
        reason_text = "Soft-gate evidence is pending or not passed yet."
    elif required_passed > 0:
        severity = "ok"
    else:
        severity = "unknown"
        reason_code = "EVIDENCE_REPORTS_UNAVAILABLE"
        reason_text = "No required evidence report has been discovered."

    recent_reports: List[Dict[str, Any]] = []
    if reports_dir.exists():
        all_reports = sorted(
            reports_dir.glob("*.json"),
            key=lambda path: path.stat().st_mtime if path.exists() else 0,
            reverse=True,
        )
        from datetime import datetime, timezone

        for path in all_reports[: max(1, int(max_reports))]:
            try:
                stat = path.stat()
            except OSError:
                continue
            recent_reports.append(
                {
                    "name": path.name,
                    "path": _ops_unix_path(path),
                    "size_bytes": int(stat.st_size),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                }
            )

    source_reports = sorted(
        {
            item["path"]
            for item in required_reports
            if bool(item["exists"]) and isinstance(item.get("path"), str) and item["path"]
        }
    )

    response_data = {
        "summary": {
            "required_total": len(required_reports),
            "required_present": required_present,
            "required_passed": required_passed,
            "required_missing": len(required_reports) - required_present,
            "required_failed": sum(1 for item in required_reports if item["status"] == "failed"),
            "hard_missing": hard_missing,
            "hard_failed": hard_failed,
            "soft_missing": soft_missing,
            "soft_failed": soft_failed,
        },
        "required_reports": required_reports,
        "recent_reports": recent_reports,
    }

    return _ops_build_response(
        data=response_data,
        severity=severity,
        source_reports=source_reports,
        source_endpoints=[],
        reason_code=reason_code,
        reason_text=reason_text,
    )


def _ops_build_incidents_latest_payload(*, limit: int = 50) -> Dict[str, Any]:
    repo_root = _ops_repo_root()
    events_file = repo_root / "logs" / "autonomous" / "events.jsonl"
    events_db = _ops_resolve_event_db_path(events_file)
    event_rows = _ops_read_event_rows(events_file, limit=max(200, int(limit) * 10))
    route_quality_trend = _ops_build_route_quality_trend(events_file, window_size=20, max_windows=6)
    execution_bridge_governance = _ops_build_execution_bridge_governance_summary(
        events_file=events_file,
        limit=max(200, int(limit) * 10),
        issues_limit=max(10, int(limit)),
    )
    process_guard = _ops_build_process_guard_summary(repo_root)
    killswitch_guard = _ops_build_killswitch_guard_summary(repo_root)
    budget_guard = _ops_build_budget_guard_summary(repo_root)
    agentic_loop_completion = _ops_build_agentic_loop_completion_summary(
        events_file=events_file,
        limit=max(200, int(limit) * 10),
    )
    vision_multimodal = _ops_build_vision_multimodal_summary(
        events_file=events_file,
        limit=max(200, int(limit) * 10),
    )
    prompt_safety_summary: Dict[str, Any] = {}
    try:
        from scripts.export_slo_snapshot import build_snapshot

        snapshot = build_snapshot(repo_root=repo_root, events_limit=max(200, int(limit) * 10))
        snapshot_metrics = snapshot.get("metrics") if isinstance(snapshot.get("metrics"), dict) else {}
        outer_readonly_hit = (
            snapshot_metrics.get("outer_readonly_hit_rate")
            if isinstance(snapshot_metrics.get("outer_readonly_hit_rate"), dict)
            else {}
        )
        readonly_write_exposure = (
            snapshot_metrics.get("readonly_write_tool_exposure_rate")
            if isinstance(snapshot_metrics.get("readonly_write_tool_exposure_rate"), dict)
            else {}
        )
        chat_route_distribution = (
            snapshot_metrics.get("chat_route_path_distribution")
            if isinstance(snapshot_metrics.get("chat_route_path_distribution"), dict)
            else {}
        )
        path_b_budget_escalation = (
            snapshot_metrics.get("path_b_budget_escalation_rate")
            if isinstance(snapshot_metrics.get("path_b_budget_escalation_rate"), dict)
            else {}
        )
        core_session_creation = (
            snapshot_metrics.get("core_session_creation_rate")
            if isinstance(snapshot_metrics.get("core_session_creation_rate"), dict)
            else {}
        )
        prompt_safety_summary = {
            "outer_readonly_hit_rate": outer_readonly_hit,
            "readonly_write_tool_exposure_rate": readonly_write_exposure,
            "chat_route_path_distribution": chat_route_distribution,
            "path_b_budget_escalation_rate": path_b_budget_escalation,
            "core_session_creation_rate": core_session_creation,
            "route_quality": _ops_build_route_quality_summary(snapshot_metrics, trend=route_quality_trend),
            "execution_bridge_governance": execution_bridge_governance,
            "agentic_loop_completion": agentic_loop_completion,
            "vision_multimodal": vision_multimodal,
            "process_guard": process_guard,
            "killswitch_guard": killswitch_guard,
            "budget_guard": budget_guard,
        }
    except Exception as exc:
        logger.warning(f"构建 incidents prompt safety 摘要失败（降级为空）: {exc}")
    if "execution_bridge_governance" not in prompt_safety_summary:
        prompt_safety_summary["execution_bridge_governance"] = execution_bridge_governance
    if "agentic_loop_completion" not in prompt_safety_summary:
        prompt_safety_summary["agentic_loop_completion"] = agentic_loop_completion
    if "vision_multimodal" not in prompt_safety_summary:
        prompt_safety_summary["vision_multimodal"] = vision_multimodal
    if "process_guard" not in prompt_safety_summary:
        prompt_safety_summary["process_guard"] = process_guard
    if "killswitch_guard" not in prompt_safety_summary:
        prompt_safety_summary["killswitch_guard"] = killswitch_guard
    if "budget_guard" not in prompt_safety_summary:
        prompt_safety_summary["budget_guard"] = budget_guard

    incidents: List[Dict[str, Any]] = []
    event_counters: Dict[str, int] = {key: 0 for key in sorted(_OPS_INCIDENT_EVENT_SEVERITY.keys())}
    event_counters["ExecutionBridgeGovernanceIssue"] = 0
    event_counters["AuditLedgerChainInvalid"] = 0

    for row in event_rows:
        event_type = str(row.get("event_type") or "").strip()
        severity = _OPS_INCIDENT_EVENT_SEVERITY.get(event_type)
        if not severity:
            continue
        event_counters[event_type] = int(event_counters.get(event_type, 0)) + 1
        incidents.append(
            {
                "source": "events",
                "severity": severity,
                "timestamp": str(row.get("timestamp") or ""),
                "event_type": event_type,
                "summary": f"{event_type} detected in runtime event stream",
                "payload_excerpt": _ops_compact_event_payload(row.get("payload")),
                "report_path": "",
                "gate_level": "n/a",
            }
        )

    required_reports = _ops_collect_required_reports(repo_root)
    for report in required_reports:
        status = str(report.get("status") or "")
        gate_level = str(report.get("gate_level") or "soft")
        if status not in {"missing", "failed"}:
            continue
        severity = "critical" if gate_level == "hard" else "warning"
        summary = (
            f"{report['label']} missing"
            if status == "missing"
            else f"{report['label']} failed checks: {', '.join(report.get('failed_checks') or ['unknown'])}"
        )
        incidents.append(
            {
                "source": "report",
                "severity": severity,
                "timestamp": str(report.get("generated_at") or report.get("modified_at") or ""),
                "event_type": "EvidenceGateIssue",
                "summary": summary,
                "payload_excerpt": {"status": status, "report_id": report["id"]},
                "report_path": str(report.get("path") or ""),
                "gate_level": gate_level,
            }
        )

    brainstem_summary = _ops_build_brainstem_control_plane_summary(repo_root)
    brainstem_status = str(brainstem_summary.get("status") or "")
    if brainstem_status in {"warning", "critical"}:
        reason_code = str(brainstem_summary.get("reason_code") or "")
        brainstem_event_type = "BrainstemControlPlaneIssue"
        if reason_code == "BRAINSTEM_HEARTBEAT_MISSING":
            brainstem_event_type = "BrainstemHeartbeatMissing"
        elif reason_code in {"BRAINSTEM_HEARTBEAT_STALE_WARNING", "BRAINSTEM_HEARTBEAT_STALE_CRITICAL"}:
            brainstem_event_type = "BrainstemHeartbeatStale"
        elif reason_code == "BRAINSTEM_HEALTH_UNHEALTHY":
            brainstem_event_type = "BrainstemDaemonUnhealthy"
        elif reason_code in {"BRAINSTEM_HEARTBEAT_TIMESTAMP_INVALID", "BRAINSTEM_HEARTBEAT_NO_SIGNAL"}:
            brainstem_event_type = "BrainstemHeartbeatInvalid"
        incidents.append(
            {
                "source": "report",
                "severity": brainstem_status,
                "timestamp": str(brainstem_summary.get("generated_at") or ""),
                "event_type": brainstem_event_type,
                "summary": str(brainstem_summary.get("reason_text") or "Brainstem control-plane issue detected."),
                "payload_excerpt": {
                    "reason_code": reason_code,
                    "healthy": brainstem_summary.get("healthy"),
                    "heartbeat_age_seconds": brainstem_summary.get("heartbeat_age_seconds"),
                    "stale_warning_seconds": brainstem_summary.get("stale_warning_seconds"),
                    "stale_critical_seconds": brainstem_summary.get("stale_critical_seconds"),
                    "unhealthy_services": list(brainstem_summary.get("unhealthy_services") or []),
                    "tick": brainstem_summary.get("tick"),
                },
                "report_path": str(brainstem_summary.get("heartbeat_file") or ""),
                "gate_level": "hard",
            }
        )

    watchdog_summary = _ops_build_watchdog_daemon_summary(repo_root)
    watchdog_status = str(watchdog_summary.get("status") or "")
    if watchdog_status in {"warning", "critical"}:
        reason_code = str(watchdog_summary.get("reason_code") or "")
        watchdog_event_type = "WatchdogDaemonIssue"
        if reason_code == "WATCHDOG_DAEMON_STATE_MISSING":
            watchdog_event_type = "WatchdogDaemonStateMissing"
        elif reason_code in {"WATCHDOG_DAEMON_STALE_WARNING", "WATCHDOG_DAEMON_STALE_CRITICAL"}:
            watchdog_event_type = "WatchdogDaemonStateStale"
        elif reason_code in {"WATCHDOG_DAEMON_THRESHOLD_WARNING", "WATCHDOG_DAEMON_THRESHOLD_CRITICAL"}:
            watchdog_event_type = "WatchdogDaemonThresholdExceeded"
        incidents.append(
            {
                "source": "report",
                "severity": watchdog_status,
                "timestamp": str(watchdog_summary.get("generated_at") or ""),
                "event_type": watchdog_event_type,
                "summary": str(watchdog_summary.get("reason_text") or "Watchdog daemon issue detected."),
                "payload_excerpt": {
                    "reason_code": reason_code,
                    "heartbeat_age_seconds": watchdog_summary.get("heartbeat_age_seconds"),
                    "stale_warning_seconds": watchdog_summary.get("stale_warning_seconds"),
                    "stale_critical_seconds": watchdog_summary.get("stale_critical_seconds"),
                    "tick": watchdog_summary.get("tick"),
                    "threshold_hit": watchdog_summary.get("threshold_hit"),
                    "action": watchdog_summary.get("action"),
                },
                "report_path": str(watchdog_summary.get("state_file") or ""),
                "gate_level": "hard",
            }
        )

    process_guard_status = str(process_guard.get("status") or "")
    if process_guard_status in {"warning", "critical"}:
        process_event_type = "ProcessGuardOrphanReaped"
        reason_code = str(process_guard.get("reason_code") or "")
        if process_guard_status == "critical":
            process_event_type = "ProcessGuardZombieDetected"
        event_counters[process_event_type] = int(event_counters.get(process_event_type, 0)) + 1
        incidents.append(
            {
                "source": "report",
                "severity": process_guard_status,
                "timestamp": str(process_guard.get("generated_at") or ""),
                "event_type": process_event_type,
                "summary": str(process_guard.get("reason_text") or "Process guard detected runtime process risk."),
                "payload_excerpt": {
                    "reason_code": reason_code,
                    "running_jobs": process_guard.get("running_jobs"),
                    "orphan_jobs": process_guard.get("orphan_jobs"),
                    "stale_jobs": process_guard.get("stale_jobs"),
                    "orphan_reaped_count": process_guard.get("orphan_reaped_count"),
                },
                "report_path": str(process_guard.get("state_file") or ""),
                "gate_level": "hard",
            }
        )

    killswitch_status = str(killswitch_guard.get("status") or "")
    if killswitch_status in {"warning", "critical"} and bool(killswitch_guard.get("active")):
        event_counters["KillSwitchEngaged"] = int(event_counters.get("KillSwitchEngaged", 0)) + 1
        incidents.append(
            {
                "source": "report",
                "severity": "critical" if killswitch_status == "critical" else "warning",
                "timestamp": str(killswitch_guard.get("generated_at") or ""),
                "event_type": "KillSwitchEngaged",
                "summary": str(killswitch_guard.get("reason_text") or "KillSwitch guard is active."),
                "payload_excerpt": {
                    "reason_code": str(killswitch_guard.get("reason_code") or ""),
                    "mode": str(killswitch_guard.get("mode") or ""),
                    "approval_ticket": str(killswitch_guard.get("approval_ticket") or ""),
                    "requested_by": str(killswitch_guard.get("requested_by") or ""),
                },
                "report_path": str(killswitch_guard.get("state_file") or ""),
                "gate_level": "hard",
            }
        )

    budget_guard_status = str(budget_guard.get("status") or "")
    if budget_guard_status in {"warning", "critical"}:
        event_counters["BudgetGuardTriggered"] = int(event_counters.get("BudgetGuardTriggered", 0)) + 1
        incidents.append(
            {
                "source": "report",
                "severity": budget_guard_status,
                "timestamp": str(budget_guard.get("generated_at") or ""),
                "event_type": "BudgetGuardTriggered",
                "summary": str(budget_guard.get("reason_text") or "Budget guard threshold triggered."),
                "payload_excerpt": {
                    "reason_code": str(budget_guard.get("reason_code") or ""),
                    "action": str(budget_guard.get("action") or ""),
                    "task_id": str(budget_guard.get("task_id") or ""),
                    "tool_name": str(budget_guard.get("tool_name") or ""),
                },
                "report_path": str(budget_guard.get("state_file") or ""),
                "gate_level": "hard",
            }
        )

    immutable_dna_summary = _ops_build_immutable_dna_summary()
    immutable_dna_status = str(immutable_dna_summary.get("status") or "")
    immutable_dna_reason_code = str(immutable_dna_summary.get("reason_code") or "")
    if immutable_dna_status in {"warning", "critical"}:
        immutable_event_type = "ImmutableDNAIntegrityIssue"
        if immutable_dna_reason_code in {
            "IMMUTABLE_DNA_TAMPER_DETECTED",
            "IMMUTABLE_DNA_MANIFEST_HASH_CHANGED",
            "IMMUTABLE_DNA_MONITOR_CRITICAL",
        }:
            immutable_event_type = "ImmutableDNATamperDetected"
        event_counters[immutable_event_type] = int(event_counters.get(immutable_event_type, 0)) + 1
        immutable_monitor = (
            immutable_dna_summary.get("monitor")
            if isinstance(immutable_dna_summary.get("monitor"), dict)
            else {}
        )
        incidents.append(
            {
                "source": "report",
                "severity": immutable_dna_status,
                "timestamp": str(
                    immutable_monitor.get("generated_at")
                    or immutable_dna_summary.get("generated_at")
                    or ""
                ),
                "event_type": immutable_event_type,
                "summary": str(
                    immutable_dna_summary.get("reason_text")
                    or "Immutable DNA integrity monitor reports issue."
                ),
                "payload_excerpt": {
                    "reason_code": immutable_dna_reason_code,
                    "monitor_reason_code": str(immutable_monitor.get("reason_code") or ""),
                    "monitor_status": str(immutable_dna_summary.get("monitor_status") or ""),
                    "manifest_hash": str(immutable_dna_summary.get("manifest_hash") or ""),
                },
                "report_path": str(immutable_monitor.get("state_file") or immutable_dna_summary.get("manifest_path") or ""),
                "gate_level": "hard",
            }
        )

    audit_ledger_summary = _ops_build_audit_ledger_summary(repo_root)
    audit_ledger_status = str(audit_ledger_summary.get("status") or "")
    audit_reason_code = str(audit_ledger_summary.get("reason_code") or "")
    if audit_ledger_status == "critical" and audit_reason_code in {"AUDIT_LEDGER_CHAIN_INVALID", "AUDIT_LEDGER_READ_FAILED"}:
        event_counters["AuditLedgerChainInvalid"] = int(event_counters.get("AuditLedgerChainInvalid", 0)) + 1
        incidents.append(
            {
                "source": "report",
                "severity": "critical",
                "timestamp": str(audit_ledger_summary.get("latest_generated_at") or ""),
                "event_type": "AuditLedgerChainInvalid",
                "summary": str(audit_ledger_summary.get("reason_text") or "Audit ledger hash chain is invalid."),
                "payload_excerpt": {
                    "reason_code": audit_reason_code,
                    "checked_count": audit_ledger_summary.get("checked_count"),
                    "error_count": audit_ledger_summary.get("error_count"),
                    "errors": list(audit_ledger_summary.get("errors") or []),
                },
                "report_path": str(audit_ledger_summary.get("ledger_file") or ""),
                "gate_level": "hard",
            }
        )

    governance_issues = execution_bridge_governance.get("recent_issues")
    if isinstance(governance_issues, list):
        for issue in governance_issues:
            if not isinstance(issue, dict):
                continue
            issue_severity = _ops_status_to_severity(str(issue.get("severity") or "unknown"))
            if issue_severity not in {"warning", "critical"}:
                continue
            event_counters["ExecutionBridgeGovernanceIssue"] = int(event_counters.get("ExecutionBridgeGovernanceIssue", 0)) + 1
            reason_code = str(issue.get("reason_code") or "EXECUTION_BRIDGE_GOVERNANCE_ISSUE")
            incidents.append(
                {
                    "source": "events",
                    "severity": issue_severity,
                    "timestamp": str(issue.get("timestamp") or ""),
                    "event_type": "ExecutionBridgeGovernanceIssue",
                    "summary": str(
                        issue.get("reason")
                        or f"Execution bridge governance issue detected: {reason_code}"
                    ),
                    "payload_excerpt": {
                        "reason_code": reason_code,
                        "category": str(issue.get("category") or ""),
                        "executor": str(issue.get("executor") or ""),
                        "policy_source": str(issue.get("policy_source") or ""),
                        "violation_count": _ops_safe_int(issue.get("violation_count"), default=0),
                        "task_id": str(issue.get("task_id") or ""),
                        "subtask_id": str(issue.get("subtask_id") or ""),
                    },
                    "report_path": _ops_unix_path(events_db if events_db.exists() else events_file),
                    "gate_level": "runtime",
                }
            )

    incidents.sort(
        key=lambda row: _ops_parse_iso_datetime(row.get("timestamp")) or 0.0,
        reverse=True,
    )
    incidents = incidents[: max(1, int(limit))]

    critical_count = sum(1 for item in incidents if str(item.get("severity")) == "critical")
    warning_count = sum(1 for item in incidents if str(item.get("severity")) == "warning")
    latest_incident_at = ""
    if incidents:
        latest_incident_at = str(incidents[0].get("timestamp") or "")

    source_reports: List[str] = []
    if events_db.exists():
        source_reports.append(_ops_unix_path(events_db))
    elif events_file.exists():
        source_reports.append(_ops_unix_path(events_file))
    for item in incidents:
        report_path = str(item.get("report_path") or "")
        if report_path:
            source_reports.append(report_path)

    reason_code: Optional[str] = None
    reason_text: Optional[str] = None
    if critical_count > 0:
        severity = "critical"
        reason_code = "INCIDENTS_CRITICAL_PRESENT"
        reason_text = "Critical incidents are present in runtime signals."
    elif warning_count > 0:
        severity = "warning"
        reason_code = "INCIDENTS_WARNING_PRESENT"
        reason_text = "Warning-level incidents are present in runtime signals."
    elif len(event_rows) > 0:
        severity = "ok"
    else:
        severity = "unknown"
        reason_code = "INCIDENTS_SIGNAL_EMPTY"
        reason_text = "No incident signal source was discovered."

    response_data = {
        "summary": {
            "total_incidents": len(incidents),
            "critical_incidents": critical_count,
            "warning_incidents": warning_count,
            "latest_incident_at": latest_incident_at,
            "runtime_prompt_safety": prompt_safety_summary,
            "execution_bridge_governance": execution_bridge_governance,
        },
        "event_counters": event_counters,
        "events_scanned": len(event_rows),
        "incidents": incidents,
    }

    return _ops_build_response(
        data=response_data,
        severity=severity,
        source_reports=sorted(set(source_reports)),
        source_endpoints=[],
        reason_code=reason_code,
        reason_text=reason_text,
    )


@router.get("/mcp/status")
async def get_mcp_status_offline():
    """返回 MCP 运行态快照，兼容前端 status/tasks 字段。"""
    return _build_mcp_runtime_snapshot()


@router.get("/mcp/tasks")
async def get_mcp_tasks_offline(status: Optional[str] = None):
    """返回 MCP 任务（服务）快照，避免离线模式 503。"""
    return _build_mcp_task_snapshot(status)


# ============ MCP 服务列表 & 导入 ============


def _load_mcporter_config() -> Dict[str, Any]:
    """读取 ~/.mcporter/config.json，不存在或格式错误时返回空 dict"""
    if not MCPORTER_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(MCPORTER_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_mcporter_config(mcporter_config: Dict[str, Any]) -> Path:
    MCPORTER_DIR.mkdir(parents=True, exist_ok=True)
    MCPORTER_CONFIG_PATH.write_text(
        json.dumps(mcporter_config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return MCPORTER_CONFIG_PATH


def _check_agent_available(manifest: Dict[str, Any]) -> bool:
    """检查内置 agent 模块是否可导入"""
    entry = manifest.get("entryPoint", {})
    module_path = entry.get("module", "")
    if not module_path:
        return False
    try:
        __import__(module_path)
        return True
    except Exception:
        return False


@router.get("/mcp/services")
def get_mcp_services():
    """列出所有 MCP 服务并检查可用性（同步端点，由 FastAPI 在线程池中执行）"""
    services: List[Dict[str, Any]] = []

    # 1. 内置 agent（扫描 mcpserver/**/agent-manifest.json）
    mcpserver_dir = Path(__file__).resolve().parent.parent / "mcpserver"
    for manifest_path in mcpserver_dir.glob("*/agent-manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if manifest.get("agentType") != "mcp":
            continue
        available = _check_agent_available(manifest)
        services.append({
            "name": manifest.get("name", manifest_path.parent.name),
            "display_name": manifest.get("displayName", manifest.get("name", "")),
            "description": manifest.get("description", ""),
            "source": "builtin",
            "available": available,
        })

    # 2. mcporter 外部配置（~/.mcporter/config.json 中的 mcpServers）
    mcporter_config = _load_mcporter_config()
    for name, cfg in mcporter_config.get("mcpServers", {}).items():
        cmd = cfg.get("command", "")
        available = shutil.which(cmd) is not None if cmd else False
        services.append({
            "name": name,
            "display_name": name,
            "description": f"{cmd} {' '.join(cfg.get('args', []))}" if cmd else "",
            "source": "mcporter",
            "available": available,
        })

    return {"status": "success", "services": services}


@router.get("/v1/ops/runtime/posture")
async def get_ops_runtime_posture(events_limit: int = 5000):
    """聚合运行态势：rollout/fail-open/lease/queue/lock/disk/error/latency。"""
    try:
        return _ops_build_runtime_posture_payload(events_limit=events_limit)
    except Exception as exc:
        logger.error(f"获取 /v1/ops/runtime/posture 失败: {exc}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取 runtime posture 失败: {str(exc)}")


@router.get("/v1/ops/mcp/fabric")
async def get_ops_mcp_fabric():
    """聚合 MCP 织网状态：registry、services、task snapshot。"""
    try:
        return _ops_build_mcp_fabric_payload()
    except Exception as exc:
        logger.error(f"获取 /v1/ops/mcp/fabric 失败: {exc}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取 mcp fabric 失败: {str(exc)}")


@router.get("/v1/ops/memory/graph")
async def get_ops_memory_graph(sample_limit: int = 200):
    """聚合记忆图谱运行态：统计、热点关系与样本图数据。"""
    try:
        return await _ops_build_memory_graph_payload(sample_limit=sample_limit)
    except Exception as exc:
        logger.error(f"获取 /v1/ops/memory/graph 失败: {exc}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取 memory graph 失败: {str(exc)}")


@router.get("/v1/ops/workflow/events")
async def get_ops_workflow_events(events_limit: int = 5000, context_days: int = 7, recent_critical_limit: int = 50):
    """聚合工作流与事件态势：队列、锁、关键事件与日志上下文。"""
    try:
        return _ops_build_workflow_events_payload(
            events_limit=events_limit,
            context_days=context_days,
            recent_critical_limit=recent_critical_limit,
        )
    except Exception as exc:
        logger.error(f"获取 /v1/ops/workflow/events 失败: {exc}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取 workflow events 失败: {str(exc)}")


@router.get("/v1/ops/incidents/latest")
async def get_ops_incidents_latest(limit: int = 50):
    """聚合近期事故态势：关键事件 + 关键报告门禁异常。"""
    try:
        return _ops_build_incidents_latest_payload(limit=limit)
    except Exception as exc:
        logger.error(f"获取 /v1/ops/incidents/latest 失败: {exc}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取 incidents latest 失败: {str(exc)}")


@router.get("/v1/ops/evidence/index")
async def get_ops_evidence_index(max_reports: int = 100):
    """聚合证据索引：M12 关键报告可见性与门禁状态。"""
    try:
        return _ops_build_evidence_index_payload(max_reports=max_reports)
    except Exception as exc:
        logger.error(f"获取 /v1/ops/evidence/index 失败: {exc}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取 evidence index 失败: {str(exc)}")


# ── Backward-compat delegation (recursion-safe) ──────────────
# Tests/scripts may `from apiserver import routes_ops as api_server`,
# then access api_server.app, api_server.time, etc.
# Use sys.modules to avoid triggering circular import.
import sys as _sys
_GETATTR_GUARD = False

def __getattr__(name: str):  # noqa: N807
    global _GETATTR_GUARD
    if _GETATTR_GUARD:
        raise AttributeError(f"module 'apiserver.routes_ops' has no attribute {name!r}")
    _GETATTR_GUARD = True
    try:
        _real = _sys.modules.get("apiserver.api_server")
        if _real is not None:
            return getattr(_real, name)
        raise AttributeError(f"module 'apiserver.routes_ops' has no attribute {name!r}")
    except AttributeError:
        raise AttributeError(f"module 'apiserver.routes_ops' has no attribute {name!r}") from None
    finally:
        _GETATTR_GUARD = False
