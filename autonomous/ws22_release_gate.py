"""WS22 phase3 release gate evaluation helpers."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass(frozen=True)
class WS22ReleaseGateThresholds:
    min_virtual_elapsed_seconds: float = 600.0
    max_task_rejected_count: int = 0
    max_event_mismatch_count: int = 0
    max_unhandled_exception_count: int = 0
    max_failed_workflow_state_count: int = 0


@dataclass(frozen=True)
class WS22ReleaseGateResult:
    passed: bool
    reasons: List[str] = field(default_factory=list)
    checks: Dict[str, bool] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def load_ws22_longrun_report(path: str | Path) -> Dict[str, Any]:
    report_path = Path(path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid report payload type: {type(payload).__name__}")
    return payload


def evaluate_ws22_longrun_report(
    report: Dict[str, Any],
    *,
    thresholds: WS22ReleaseGateThresholds = WS22ReleaseGateThresholds(),
) -> WS22ReleaseGateResult:
    metrics = report.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}

    rounds = _as_int(metrics.get("rounds"))
    task_approved_count = _as_int(metrics.get("task_approved_count"))
    task_rejected_count = _as_int(metrics.get("task_rejected_count"))
    subtask_dispatching_count = _as_int(metrics.get("subtask_dispatching_count"))
    runtime_completed_count = _as_int(metrics.get("runtime_completed_count"))
    fail_open_count = _as_int(metrics.get("fail_open_count"))
    planned_fail_open_rounds = _as_int(metrics.get("planned_fail_open_rounds"))
    event_mismatch_count = _as_int(metrics.get("event_mismatch_count"))
    unhandled_exception_count = _as_int(metrics.get("unhandled_exception_count"))
    failed_workflow_state_count = _as_int(metrics.get("failed_workflow_state_count"))
    virtual_elapsed_seconds = _as_float(metrics.get("virtual_elapsed_seconds"))
    service_value_matches_expected = bool(metrics.get("service_value_matches_expected"))

    checks: Dict[str, bool] = {
        "report_passed_flag": bool(report.get("passed")),
        "virtual_elapsed_window": virtual_elapsed_seconds >= thresholds.min_virtual_elapsed_seconds,
        "task_approved_matches_rounds": rounds > 0 and task_approved_count == rounds,
        "task_rejected_within_threshold": task_rejected_count <= thresholds.max_task_rejected_count,
        "subtask_dispatching_matches_rounds": rounds > 0 and subtask_dispatching_count == rounds,
        "runtime_completed_matches_rounds": rounds > 0 and runtime_completed_count == rounds,
        "fail_open_matches_planned": fail_open_count == planned_fail_open_rounds,
        "event_mismatch_within_threshold": event_mismatch_count <= thresholds.max_event_mismatch_count,
        "unhandled_exception_within_threshold": unhandled_exception_count <= thresholds.max_unhandled_exception_count,
        "failed_workflow_states_within_threshold": failed_workflow_state_count <= thresholds.max_failed_workflow_state_count,
        "service_value_matches_expected": service_value_matches_expected,
    }

    reasons = [name for name, passed in checks.items() if not passed]
    return WS22ReleaseGateResult(
        passed=not reasons,
        reasons=reasons,
        checks=checks,
        metrics=dict(metrics),
    )


def evaluate_ws22_doc_closure(ws22_doc_path: str | Path) -> Dict[str, Any]:
    doc_path = Path(ws22_doc_path)
    text = doc_path.read_text(encoding="utf-8")

    ws22_004_done = bool(
        re.search(
            r"###\s+NGA-WS22-004[^\n]*\n(?:.*\n){0,20}?\-\s+status:\s+done\b",
            text,
            flags=re.IGNORECASE,
        )
    )
    summary_done = "已完成：4/4" in text
    passed = ws22_004_done and summary_done
    reasons: List[str] = []
    if not ws22_004_done:
        reasons.append("ws22_004_status_not_done")
    if not summary_done:
        reasons.append("ws22_progress_summary_not_4_of_4")

    return {
        "passed": passed,
        "reasons": reasons,
        "checks": {
            "ws22_004_status_done": ws22_004_done,
            "ws22_progress_summary_4_of_4": summary_done,
        },
        "path": str(doc_path).replace("\\", "/"),
    }


def evaluate_ws22_phase3_closure_gate(
    *,
    report_path: str | Path,
    ws22_doc_path: str | Path,
    thresholds: WS22ReleaseGateThresholds = WS22ReleaseGateThresholds(),
) -> Dict[str, Any]:
    report = load_ws22_longrun_report(report_path)
    report_result = evaluate_ws22_longrun_report(report, thresholds=thresholds)
    doc_result = evaluate_ws22_doc_closure(ws22_doc_path)

    checks = {
        "report_gate": report_result.passed,
        "doc_gate": bool(doc_result.get("passed")),
    }
    passed = all(checks.values())
    reasons: List[str] = []
    if not checks["report_gate"]:
        reasons.extend([f"report:{item}" for item in report_result.reasons])
    if not checks["doc_gate"]:
        reasons.extend([f"doc:{item}" for item in list(doc_result.get("reasons") or [])])

    return {
        "passed": passed,
        "reasons": reasons,
        "checks": checks,
        "report_result": report_result.to_dict(),
        "doc_result": doc_result,
        "inputs": {
            "report_path": str(Path(report_path)).replace("\\", "/"),
            "ws22_doc_path": str(Path(ws22_doc_path)).replace("\\", "/"),
        },
    }


__all__ = [
    "WS22ReleaseGateThresholds",
    "WS22ReleaseGateResult",
    "load_ws22_longrun_report",
    "evaluate_ws22_longrun_report",
    "evaluate_ws22_doc_closure",
    "evaluate_ws22_phase3_closure_gate",
]
