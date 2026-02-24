from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from autonomous.ws22_release_gate import (
    evaluate_ws22_doc_closure,
    evaluate_ws22_longrun_report,
    evaluate_ws22_phase3_closure_gate,
)


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _good_report_payload() -> dict:
    return {
        "passed": True,
        "metrics": {
            "rounds": 120,
            "virtual_elapsed_seconds": 600.0,
            "task_approved_count": 120,
            "task_rejected_count": 0,
            "subtask_dispatching_count": 120,
            "runtime_completed_count": 120,
            "fail_open_count": 8,
            "planned_fail_open_rounds": 8,
            "event_mismatch_count": 0,
            "unhandled_exception_count": 0,
            "failed_workflow_state_count": 0,
            "service_value_matches_expected": True,
        },
    }


def test_ws22_release_gate_passes_for_valid_report() -> None:
    result = evaluate_ws22_longrun_report(_good_report_payload())
    assert result.passed is True
    assert result.reasons == []


def test_ws22_release_gate_rejects_on_event_mismatch() -> None:
    payload = _good_report_payload()
    payload["metrics"]["event_mismatch_count"] = 2
    result = evaluate_ws22_longrun_report(payload)
    assert result.passed is False
    assert "event_mismatch_within_threshold" in result.reasons


def test_ws22_doc_closure_requires_ws22_004_done_and_4_of_4_summary() -> None:
    case_root = _make_case_root("test_ws22_release_gate")
    try:
        doc_file = case_root / "ws22.md"
        doc_file.write_text(
            """
### NGA-WS22-004 调度层混沌与 Lease 守护
- status: done

## 当前进度快照（2026-02-24）
- 已完成：4/4（NGA-WS22-001, NGA-WS22-002, NGA-WS22-003, NGA-WS22-004）
""".strip(),
            encoding="utf-8",
        )
        result = evaluate_ws22_doc_closure(doc_file)
        assert result["passed"] is True
    finally:
        _cleanup_case_root(case_root)


def test_ws22_phase3_closure_gate_fails_when_doc_not_closed() -> None:
    case_root = _make_case_root("test_ws22_release_gate")
    try:
        report_file = case_root / "report.json"
        report_file.write_text(json.dumps(_good_report_payload(), ensure_ascii=False), encoding="utf-8")
        doc_file = case_root / "ws22.md"
        doc_file.write_text(
            """
### NGA-WS22-004 调度层混沌与 Lease 守护
- status: in_progress
""".strip(),
            encoding="utf-8",
        )

        result = evaluate_ws22_phase3_closure_gate(
            report_path=report_file,
            ws22_doc_path=doc_file,
        )
        assert result["passed"] is False
        assert any(item.startswith("doc:") for item in result["reasons"])
    finally:
        _cleanup_case_root(case_root)
