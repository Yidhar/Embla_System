"""WS26-006 M11 closure gate evaluation helpers."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

_WS26_BRAINSTEM_HEARTBEAT_DEFAULT_PATH = Path("scratch/runtime/brainstem_control_plane_heartbeat_ws23_001.json")
_WS26_BRAINSTEM_HEARTBEAT_STALE_WARNING_SECONDS = 120.0
_WS26_BRAINSTEM_HEARTBEAT_STALE_CRITICAL_SECONDS = 300.0


def _load_json_report(path: str | Path) -> Dict[str, Any]:
    report_path = Path(path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid report payload type: {type(payload).__name__}")
    return payload


def _evaluate_report_gate(
    *,
    name: str,
    path: str | Path,
    expected_task_id: str,
    expected_scenario: str,
) -> Dict[str, Any]:
    report_path = Path(path)
    if not report_path.exists():
        return {
            "passed": False,
            "reasons": [f"{name}_report_missing"],
            "checks": {
                "report_exists": False,
                "report_passed": False,
                "task_id_match": False,
                "scenario_match": False,
            },
            "path": str(report_path).replace("\\", "/"),
            "report": {},
        }

    report = _load_json_report(report_path)
    report_passed = bool(report.get("passed"))
    task_id_match = str(report.get("task_id") or "") == expected_task_id
    scenario_match = str(report.get("scenario") or "") == expected_scenario
    checks = {
        "report_exists": True,
        "report_passed": report_passed,
        "task_id_match": task_id_match,
        "scenario_match": scenario_match,
    }
    reasons = [f"{name}:{key}" for key, passed in checks.items() if not passed]
    return {
        "passed": not reasons,
        "reasons": reasons,
        "checks": checks,
        "path": str(report_path).replace("\\", "/"),
        "report": report,
    }


def _has_snapshot_task_entry(text: str, task_id: str) -> bool:
    pattern = rf"`{re.escape(task_id)}`\s+已"
    return bool(re.search(pattern, text))


def _parse_iso_datetime(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def evaluate_ws26_brainstem_control_plane_gate(
    heartbeat_path: str | Path = _WS26_BRAINSTEM_HEARTBEAT_DEFAULT_PATH,
) -> Dict[str, Any]:
    heartbeat_file = Path(heartbeat_path)
    checks = {
        "heartbeat_exists": heartbeat_file.exists(),
        "heartbeat_payload_object": False,
        "generated_at_valid": False,
        "heartbeat_not_stale_critical": False,
        "healthy_flag_true": False,
        "unhealthy_services_empty": False,
    }
    reasons: List[str] = []
    heartbeat_payload: Dict[str, Any] = {}
    heartbeat_age_seconds: float | None = None

    if not checks["heartbeat_exists"]:
        reasons.append("heartbeat_missing")
    else:
        try:
            loaded = json.loads(heartbeat_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        if isinstance(loaded, dict):
            heartbeat_payload = loaded
            checks["heartbeat_payload_object"] = True
        else:
            reasons.append("heartbeat_payload_invalid")

    generated_ts = _parse_iso_datetime(heartbeat_payload.get("generated_at"))
    if generated_ts is not None:
        checks["generated_at_valid"] = True
        heartbeat_age_seconds = max(0.0, round(float(time.time()) - generated_ts, 3))
        checks["heartbeat_not_stale_critical"] = heartbeat_age_seconds <= float(
            _WS26_BRAINSTEM_HEARTBEAT_STALE_CRITICAL_SECONDS
        )
    elif checks["heartbeat_exists"] and checks["heartbeat_payload_object"]:
        reasons.append("heartbeat_generated_at_invalid")

    healthy = heartbeat_payload.get("healthy")
    checks["healthy_flag_true"] = healthy is True
    if checks["heartbeat_exists"] and checks["heartbeat_payload_object"] and not checks["healthy_flag_true"]:
        reasons.append("healthy_flag_false_or_missing")

    unhealthy_raw = heartbeat_payload.get("unhealthy_services")
    unhealthy_services = (
        [str(item) for item in unhealthy_raw if str(item).strip()] if isinstance(unhealthy_raw, list) else []
    )
    checks["unhealthy_services_empty"] = len(unhealthy_services) == 0
    if checks["heartbeat_exists"] and checks["heartbeat_payload_object"] and not checks["unhealthy_services_empty"]:
        reasons.append("unhealthy_services_present")

    if checks["generated_at_valid"] and not checks["heartbeat_not_stale_critical"]:
        reasons.append("heartbeat_stale_critical")

    passed = all(checks.values())
    if not checks["heartbeat_exists"]:
        passed = False

    return {
        "passed": passed,
        "reasons": sorted(set(reasons)),
        "checks": checks,
        "path": str(heartbeat_file).replace("\\", "/"),
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "stale_warning_seconds": float(_WS26_BRAINSTEM_HEARTBEAT_STALE_WARNING_SECONDS),
        "stale_critical_seconds": float(_WS26_BRAINSTEM_HEARTBEAT_STALE_CRITICAL_SECONDS),
        "heartbeat": {
            "generated_at": str(heartbeat_payload.get("generated_at") or ""),
            "healthy": heartbeat_payload.get("healthy"),
            "service_count": heartbeat_payload.get("service_count"),
            "tick": heartbeat_payload.get("tick"),
            "unhealthy_services": unhealthy_services,
        },
    }


def evaluate_ws26_doc_closure(ws26_doc_path: str | Path) -> Dict[str, Any]:
    doc_path = Path(ws26_doc_path)
    text = doc_path.read_text(encoding="utf-8")
    checks = {
        "ws26_003_snapshot_entry": _has_snapshot_task_entry(text, "NGA-WS26-003"),
        "ws26_004_snapshot_entry": _has_snapshot_task_entry(text, "NGA-WS26-004"),
        "ws26_005_snapshot_entry": _has_snapshot_task_entry(text, "NGA-WS26-005"),
        "ws26_006_snapshot_entry": _has_snapshot_task_entry(text, "NGA-WS26-006"),
    }
    reasons = [name for name, passed in checks.items() if not passed]
    return {
        "passed": not reasons,
        "reasons": reasons,
        "checks": checks,
        "path": str(doc_path).replace("\\", "/"),
    }


def evaluate_ws26_runbook_closure(runbook_path: str | Path) -> Dict[str, Any]:
    path = Path(runbook_path)
    if not path.exists():
        return {
            "passed": False,
            "reasons": ["runbook_missing"],
            "checks": {
                "runbook_exists": False,
                "contains_runtime_snapshot_export_command": False,
                "contains_runtime_chaos_suite_command": False,
                "contains_m11_gate_command": False,
                "contains_m11_chain_command": False,
                "contains_full_chain_command": False,
            },
            "path": str(path).replace("\\", "/"),
        }

    text = path.read_text(encoding="utf-8")
    checks = {
        "runbook_exists": True,
        "contains_runtime_snapshot_export_command": "export_ws26_runtime_snapshot_ws26_002.py" in text,
        "contains_runtime_chaos_suite_command": "run_ws26_m11_runtime_chaos_suite_ws26_006.py" in text,
        "contains_m11_gate_command": "validate_m11_closure_gate_ws26_006.py" in text,
        "contains_m11_chain_command": "release_closure_chain_m11_ws26_006.py" in text,
        "contains_full_chain_command": "release_closure_chain_full_m0_m7.py" in text,
    }
    reasons = [name for name, passed in checks.items() if not passed]
    return {
        "passed": not reasons,
        "reasons": reasons,
        "checks": checks,
        "path": str(path).replace("\\", "/"),
    }


def evaluate_ws26_m11_closure_gate(
    *,
    ws26_doc_path: str | Path,
    runbook_path: str | Path,
    runtime_snapshot_report_path: str | Path,
    m11_chaos_report_path: str | Path,
    brainstem_heartbeat_path: str | Path = _WS26_BRAINSTEM_HEARTBEAT_DEFAULT_PATH,
) -> Dict[str, Any]:
    runtime_snapshot_result = _evaluate_report_gate(
        name="ws26_002",
        path=runtime_snapshot_report_path,
        expected_task_id="NGA-WS26-002",
        expected_scenario="runtime_rollout_fail_open_lease_unified_snapshot",
    )
    m11_chaos_result = _evaluate_report_gate(
        name="ws26_006",
        path=m11_chaos_report_path,
        expected_task_id="NGA-WS26-006",
        expected_scenario="m11_lock_logrotate_double_fork_chaos_suite",
    )
    doc_result = evaluate_ws26_doc_closure(ws26_doc_path)
    runbook_result = evaluate_ws26_runbook_closure(runbook_path)
    brainstem_gate_result = evaluate_ws26_brainstem_control_plane_gate(brainstem_heartbeat_path)

    checks = {
        "runtime_snapshot_gate": bool(runtime_snapshot_result.get("passed")),
        "m11_chaos_gate": bool(m11_chaos_result.get("passed")),
        "doc_gate": bool(doc_result.get("passed")),
        "runbook_gate": bool(runbook_result.get("passed")),
        "brainstem_control_plane_gate": bool(brainstem_gate_result.get("passed")),
    }
    passed = all(checks.values())
    reasons: List[str] = []
    if not checks["runtime_snapshot_gate"]:
        reasons.extend([f"ws26_002:{item}" for item in list(runtime_snapshot_result.get("reasons") or [])])
    if not checks["m11_chaos_gate"]:
        reasons.extend([f"ws26_006:{item}" for item in list(m11_chaos_result.get("reasons") or [])])
    if not checks["doc_gate"]:
        reasons.extend([f"doc:{item}" for item in list(doc_result.get("reasons") or [])])
    if not checks["runbook_gate"]:
        reasons.extend([f"runbook:{item}" for item in list(runbook_result.get("reasons") or [])])
    if not checks["brainstem_control_plane_gate"]:
        reasons.extend([f"brainstem:{item}" for item in list(brainstem_gate_result.get("reasons") or [])])

    return {
        "passed": passed,
        "reasons": reasons,
        "checks": checks,
        "report_results": {
            "ws26_002": runtime_snapshot_result,
            "ws26_006": m11_chaos_result,
        },
        "doc_result": doc_result,
        "runbook_result": runbook_result,
        "brainstem_gate_result": brainstem_gate_result,
        "inputs": {
            "ws26_doc_path": str(Path(ws26_doc_path)).replace("\\", "/"),
            "runbook_path": str(Path(runbook_path)).replace("\\", "/"),
            "runtime_snapshot_report_path": str(Path(runtime_snapshot_report_path)).replace("\\", "/"),
            "m11_chaos_report_path": str(Path(m11_chaos_report_path)).replace("\\", "/"),
            "brainstem_heartbeat_path": str(Path(brainstem_heartbeat_path)).replace("\\", "/"),
        },
    }


__all__ = [
    "evaluate_ws26_doc_closure",
    "evaluate_ws26_runbook_closure",
    "evaluate_ws26_brainstem_control_plane_gate",
    "evaluate_ws26_m11_closure_gate",
]
