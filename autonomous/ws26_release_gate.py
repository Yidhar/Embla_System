"""WS26-006 M11 closure gate evaluation helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List


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

    checks = {
        "runtime_snapshot_gate": bool(runtime_snapshot_result.get("passed")),
        "m11_chaos_gate": bool(m11_chaos_result.get("passed")),
        "doc_gate": bool(doc_result.get("passed")),
        "runbook_gate": bool(runbook_result.get("passed")),
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
        "inputs": {
            "ws26_doc_path": str(Path(ws26_doc_path)).replace("\\", "/"),
            "runbook_path": str(Path(runbook_path)).replace("\\", "/"),
            "runtime_snapshot_report_path": str(Path(runtime_snapshot_report_path)).replace("\\", "/"),
            "m11_chaos_report_path": str(Path(m11_chaos_report_path)).replace("\\", "/"),
        },
    }


__all__ = [
    "evaluate_ws26_doc_closure",
    "evaluate_ws26_runbook_closure",
    "evaluate_ws26_m11_closure_gate",
]
