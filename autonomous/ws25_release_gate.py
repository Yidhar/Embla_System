"""WS25-006 M10 closure gate evaluation helpers."""

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


def evaluate_ws25_doc_closure(ws25_doc_path: str | Path) -> Dict[str, Any]:
    doc_path = Path(ws25_doc_path)
    text = doc_path.read_text(encoding="utf-8")
    checks = {
        "ws25_003_snapshot_entry": _has_snapshot_task_entry(text, "NGA-WS25-003"),
        "ws25_004_snapshot_entry": _has_snapshot_task_entry(text, "NGA-WS25-004"),
        "ws25_005_snapshot_entry": _has_snapshot_task_entry(text, "NGA-WS25-005"),
        "ws25_006_snapshot_entry": _has_snapshot_task_entry(text, "NGA-WS25-006"),
    }
    reasons = [name for name, passed in checks.items() if not passed]
    return {
        "passed": not reasons,
        "reasons": reasons,
        "checks": checks,
        "path": str(doc_path).replace("\\", "/"),
    }


def evaluate_ws25_runbook_closure(runbook_path: str | Path) -> Dict[str, Any]:
    path = Path(runbook_path)
    if not path.exists():
        return {
            "passed": False,
            "reasons": ["runbook_missing"],
            "checks": {
                "runbook_exists": False,
                "contains_ws25_005_command": False,
                "contains_m10_gate_command": False,
                "contains_m10_chain_command": False,
                "contains_full_chain_command": False,
            },
            "path": str(path).replace("\\", "/"),
        }

    text = path.read_text(encoding="utf-8")
    checks = {
        "runbook_exists": True,
        "contains_ws25_005_command": "run_event_gc_quality_baseline_ws25_005.py" in text,
        "contains_m10_gate_command": "validate_m10_closure_gate_ws25_006.py" in text,
        "contains_m10_chain_command": "release_closure_chain_m10_ws25_006.py" in text,
        "contains_full_chain_command": "release_closure_chain_full_m0_m7.py" in text,
    }
    reasons = [name for name, passed in checks.items() if not passed]
    return {
        "passed": not reasons,
        "reasons": reasons,
        "checks": checks,
        "path": str(path).replace("\\", "/"),
    }


def evaluate_ws25_m10_closure_gate(
    *,
    ws25_doc_path: str | Path,
    runbook_path: str | Path,
    event_gc_quality_report_path: str | Path,
) -> Dict[str, Any]:
    quality_result = _evaluate_report_gate(
        name="ws25_005",
        path=event_gc_quality_report_path,
        expected_task_id="NGA-WS25-005",
        expected_scenario="event_gc_quality_baseline",
    )
    doc_result = evaluate_ws25_doc_closure(ws25_doc_path)
    runbook_result = evaluate_ws25_runbook_closure(runbook_path)

    checks = {
        "event_gc_quality_gate": bool(quality_result.get("passed")),
        "doc_gate": bool(doc_result.get("passed")),
        "runbook_gate": bool(runbook_result.get("passed")),
    }
    passed = all(checks.values())
    reasons: List[str] = []
    if not checks["event_gc_quality_gate"]:
        reasons.extend([f"ws25_005:{item}" for item in list(quality_result.get("reasons") or [])])
    if not checks["doc_gate"]:
        reasons.extend([f"doc:{item}" for item in list(doc_result.get("reasons") or [])])
    if not checks["runbook_gate"]:
        reasons.extend([f"runbook:{item}" for item in list(runbook_result.get("reasons") or [])])

    return {
        "passed": passed,
        "reasons": reasons,
        "checks": checks,
        "report_results": {"ws25_005": quality_result},
        "doc_result": doc_result,
        "runbook_result": runbook_result,
        "inputs": {
            "ws25_doc_path": str(Path(ws25_doc_path)).replace("\\", "/"),
            "runbook_path": str(Path(runbook_path)).replace("\\", "/"),
            "event_gc_quality_report_path": str(Path(event_gc_quality_report_path)).replace("\\", "/"),
        },
    }


__all__ = [
    "evaluate_ws25_doc_closure",
    "evaluate_ws25_runbook_closure",
    "evaluate_ws25_m10_closure_gate",
]
