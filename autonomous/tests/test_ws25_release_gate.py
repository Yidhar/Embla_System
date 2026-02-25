from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from autonomous.ws25_release_gate import evaluate_ws25_m10_closure_gate


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _write_doc(path: Path, *, include_ws25_006: bool) -> None:
    lines = [
        "- `NGA-WS25-003` 已落地 Replay 幂等锚点与去重强化：",
        "- `NGA-WS25-004` 已落地关键证据字段保真策略：",
        "- `NGA-WS25-005` 已落地 Event/GC 质量评测基线脚本：",
    ]
    if include_ws25_006:
        lines.append("- `NGA-WS25-006` 已落地 M10 综合门禁脚本链：")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_runbook(path: Path) -> None:
    text = "\n".join(
        [
            "python scripts/run_event_gc_quality_baseline_ws25_005.py --output scratch/reports/ws25_event_gc_quality_baseline.json",
            "python scripts/validate_m10_closure_gate_ws25_006.py --event-gc-quality-report scratch/reports/ws25_event_gc_quality_baseline.json",
            "python scripts/release_closure_chain_m10_ws25_006.py",
            "python scripts/release_closure_chain_full_m0_m7.py",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_quality_report(path: Path, *, passed: bool) -> None:
    payload = {
        "task_id": "NGA-WS25-005",
        "scenario": "event_gc_quality_baseline",
        "passed": passed,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_ws25_m10_closure_gate_passes_with_green_inputs() -> None:
    case_root = _make_case_root("test_ws25_release_gate")
    try:
        doc_path = case_root / "doc.md"
        runbook_path = case_root / "runbook.md"
        quality_report = case_root / "quality.json"
        _write_doc(doc_path, include_ws25_006=True)
        _write_runbook(runbook_path)
        _write_quality_report(quality_report, passed=True)

        result = evaluate_ws25_m10_closure_gate(
            ws25_doc_path=doc_path,
            runbook_path=runbook_path,
            event_gc_quality_report_path=quality_report,
        )
        assert result["passed"] is True
        assert result["reasons"] == []
        assert result["checks"]["event_gc_quality_gate"] is True
        assert result["checks"]["doc_gate"] is True
        assert result["checks"]["runbook_gate"] is True
    finally:
        _cleanup_case_root(case_root)


def test_ws25_m10_closure_gate_fails_when_doc_missing_ws25_006_snapshot() -> None:
    case_root = _make_case_root("test_ws25_release_gate")
    try:
        doc_path = case_root / "doc.md"
        runbook_path = case_root / "runbook.md"
        quality_report = case_root / "quality.json"
        _write_doc(doc_path, include_ws25_006=False)
        _write_runbook(runbook_path)
        _write_quality_report(quality_report, passed=True)

        result = evaluate_ws25_m10_closure_gate(
            ws25_doc_path=doc_path,
            runbook_path=runbook_path,
            event_gc_quality_report_path=quality_report,
        )
        assert result["passed"] is False
        reasons = list(result["reasons"])
        assert any("doc:ws25_006_snapshot_entry" in item for item in reasons)
    finally:
        _cleanup_case_root(case_root)
