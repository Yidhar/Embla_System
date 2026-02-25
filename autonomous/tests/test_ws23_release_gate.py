from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from autonomous.ws23_release_gate import evaluate_ws23_m8_closure_gate


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _write_report(path: Path, *, task_id: str, scenario: str, passed: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "task_id": task_id,
                "scenario": scenario,
                "passed": passed,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_ws23_doc(path: Path) -> None:
    path.write_text(
        """
## 8. 本轮推进快照（2026-02-25）
- `NGA-WS23-002` 已落地调度阻断桥接：
- `NGA-WS23-003` 已接入发布预检：
- `NGA-WS23-004` 已落地可执行导出链路：
- `NGA-WS23-005` 已落地 Workflow outbox -> Brainstem 事件桥接：
- `NGA-WS23-006` 已落地 M8 门禁脚本 + Runbook：
""".strip(),
        encoding="utf-8",
    )


def _write_runbook(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
M8 chain:
python scripts/release_closure_chain_m8_ws23_006.py
gate:
python scripts/validate_m8_closure_gate_ws23_006.py
full chain:
python scripts/release_closure_chain_full_m0_m7.py
""".strip(),
        encoding="utf-8",
    )


def test_ws23_m8_gate_passes_with_valid_reports_and_doc() -> None:
    case_root = _make_case_root("test_ws23_release_gate")
    try:
        reports = case_root / "reports"
        _write_report(reports / "ws23_001.json", task_id="NGA-WS23-001", scenario="brainstem_supervisor_entry")
        _write_report(reports / "ws23_003.json", task_id="NGA-WS23-003", scenario="immutable_dna_gate_validation")
        _write_report(reports / "ws23_004.json", task_id="NGA-WS23-004", scenario="export_killswitch_oob_bundle")
        _write_report(reports / "ws23_005.json", task_id="NGA-WS23-005", scenario="outbox_brainstem_bridge_smoke")

        ws23_doc = case_root / "ws23.md"
        _write_ws23_doc(ws23_doc)
        runbook = case_root / "runbook.md"
        _write_runbook(runbook)

        result = evaluate_ws23_m8_closure_gate(
            ws23_doc_path=ws23_doc,
            runbook_path=runbook,
            brainstem_report_path=reports / "ws23_001.json",
            dna_gate_report_path=reports / "ws23_003.json",
            killswitch_bundle_report_path=reports / "ws23_004.json",
            outbox_bridge_report_path=reports / "ws23_005.json",
        )
        assert result["passed"] is True
        assert result["reasons"] == []
    finally:
        _cleanup_case_root(case_root)


def test_ws23_m8_gate_fails_when_outbox_bridge_report_missing() -> None:
    case_root = _make_case_root("test_ws23_release_gate")
    try:
        reports = case_root / "reports"
        _write_report(reports / "ws23_001.json", task_id="NGA-WS23-001", scenario="brainstem_supervisor_entry")
        _write_report(reports / "ws23_003.json", task_id="NGA-WS23-003", scenario="immutable_dna_gate_validation")
        _write_report(reports / "ws23_004.json", task_id="NGA-WS23-004", scenario="export_killswitch_oob_bundle")

        ws23_doc = case_root / "ws23.md"
        _write_ws23_doc(ws23_doc)
        runbook = case_root / "runbook.md"
        _write_runbook(runbook)

        result = evaluate_ws23_m8_closure_gate(
            ws23_doc_path=ws23_doc,
            runbook_path=runbook,
            brainstem_report_path=reports / "ws23_001.json",
            dna_gate_report_path=reports / "ws23_003.json",
            killswitch_bundle_report_path=reports / "ws23_004.json",
            outbox_bridge_report_path=reports / "missing_ws23_005.json",
        )
        assert result["passed"] is False
        assert any(item.startswith("ws23_005:") for item in result["reasons"])
    finally:
        _cleanup_case_root(case_root)

