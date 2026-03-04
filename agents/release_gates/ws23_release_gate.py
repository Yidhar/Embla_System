"""WS23-006 M8 closure gate evaluation helpers."""

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


def evaluate_ws23_doc_closure(ws23_doc_path: str | Path) -> Dict[str, Any]:
    doc_path = Path(ws23_doc_path)
    text = doc_path.read_text(encoding="utf-8")
    checks = {
        "ws23_002_snapshot_entry": _has_snapshot_task_entry(text, "NGA-WS23-002"),
        "ws23_003_snapshot_entry": _has_snapshot_task_entry(text, "NGA-WS23-003"),
        "ws23_004_snapshot_entry": _has_snapshot_task_entry(text, "NGA-WS23-004"),
        "ws23_005_snapshot_entry": _has_snapshot_task_entry(text, "NGA-WS23-005"),
        "ws23_006_snapshot_entry": _has_snapshot_task_entry(text, "NGA-WS23-006"),
    }
    reasons = [name for name, passed in checks.items() if not passed]
    return {
        "passed": not reasons,
        "reasons": reasons,
        "checks": checks,
        "path": str(doc_path).replace("\\", "/"),
    }


def evaluate_ws23_runbook_closure(runbook_path: str | Path) -> Dict[str, Any]:
    path = Path(runbook_path)
    if not path.exists():
        return {
            "passed": False,
            "reasons": ["runbook_missing"],
            "checks": {
                "runbook_exists": False,
                "contains_m8_chain_command": False,
                "contains_m8_gate_command": False,
                "contains_full_chain_command": False,
            },
            "path": str(path).replace("\\", "/"),
        }

    text = path.read_text(encoding="utf-8")
    checks = {
        "runbook_exists": True,
        "contains_m8_chain_command": "release_closure_chain_m8_ws23_006.py" in text,
        "contains_m8_gate_command": "validate_m8_closure_gate_ws23_006.py" in text,
        "contains_full_chain_command": "release_closure_chain_full_m0_m7.py" in text,
    }
    reasons = [name for name, passed in checks.items() if not passed]
    return {
        "passed": not reasons,
        "reasons": reasons,
        "checks": checks,
        "path": str(path).replace("\\", "/"),
    }


def evaluate_ws23_m8_closure_gate(
    *,
    ws23_doc_path: str | Path,
    runbook_path: str | Path,
    brainstem_report_path: str | Path,
    dna_gate_report_path: str | Path,
    killswitch_bundle_report_path: str | Path,
    outbox_bridge_report_path: str | Path,
) -> Dict[str, Any]:
    brainstem_result = _evaluate_report_gate(
        name="ws23_001",
        path=brainstem_report_path,
        expected_task_id="NGA-WS23-001",
        expected_scenario="brainstem_supervisor_entry",
    )
    dna_result = _evaluate_report_gate(
        name="ws23_003",
        path=dna_gate_report_path,
        expected_task_id="NGA-WS23-003",
        expected_scenario="immutable_dna_gate_validation",
    )
    killswitch_result = _evaluate_report_gate(
        name="ws23_004",
        path=killswitch_bundle_report_path,
        expected_task_id="NGA-WS23-004",
        expected_scenario="export_killswitch_oob_bundle",
    )
    outbox_result = _evaluate_report_gate(
        name="ws23_005",
        path=outbox_bridge_report_path,
        expected_task_id="NGA-WS23-005",
        expected_scenario="outbox_brainstem_bridge_smoke",
    )
    doc_result = evaluate_ws23_doc_closure(ws23_doc_path)
    runbook_result = evaluate_ws23_runbook_closure(runbook_path)

    checks = {
        "brainstem_report_gate": bool(brainstem_result.get("passed")),
        "dna_gate_report_gate": bool(dna_result.get("passed")),
        "killswitch_report_gate": bool(killswitch_result.get("passed")),
        "outbox_bridge_report_gate": bool(outbox_result.get("passed")),
        "doc_gate": bool(doc_result.get("passed")),
        "runbook_gate": bool(runbook_result.get("passed")),
    }
    passed = all(checks.values())
    reasons: List[str] = []
    if not checks["brainstem_report_gate"]:
        reasons.extend([f"ws23_001:{item}" for item in list(brainstem_result.get("reasons") or [])])
    if not checks["dna_gate_report_gate"]:
        reasons.extend([f"ws23_003:{item}" for item in list(dna_result.get("reasons") or [])])
    if not checks["killswitch_report_gate"]:
        reasons.extend([f"ws23_004:{item}" for item in list(killswitch_result.get("reasons") or [])])
    if not checks["outbox_bridge_report_gate"]:
        reasons.extend([f"ws23_005:{item}" for item in list(outbox_result.get("reasons") or [])])
    if not checks["doc_gate"]:
        reasons.extend([f"doc:{item}" for item in list(doc_result.get("reasons") or [])])
    if not checks["runbook_gate"]:
        reasons.extend([f"runbook:{item}" for item in list(runbook_result.get("reasons") or [])])

    return {
        "passed": passed,
        "reasons": reasons,
        "checks": checks,
        "report_results": {
            "ws23_001": brainstem_result,
            "ws23_003": dna_result,
            "ws23_004": killswitch_result,
            "ws23_005": outbox_result,
        },
        "doc_result": doc_result,
        "runbook_result": runbook_result,
        "inputs": {
            "ws23_doc_path": str(Path(ws23_doc_path)).replace("\\", "/"),
            "runbook_path": str(Path(runbook_path)).replace("\\", "/"),
            "brainstem_report_path": str(Path(brainstem_report_path)).replace("\\", "/"),
            "dna_gate_report_path": str(Path(dna_gate_report_path)).replace("\\", "/"),
            "killswitch_bundle_report_path": str(Path(killswitch_bundle_report_path)).replace("\\", "/"),
            "outbox_bridge_report_path": str(Path(outbox_bridge_report_path)).replace("\\", "/"),
        },
    }


__all__ = [
    "evaluate_ws23_doc_closure",
    "evaluate_ws23_runbook_closure",
    "evaluate_ws23_m8_closure_gate",
]

