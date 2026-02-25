from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from autonomous.ws26_release_gate import evaluate_ws26_m11_closure_gate


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


def _write_ws26_doc(path: Path, *, include_ws26_006: bool = True) -> None:
    lines = [
        "- `NGA-WS26-003` 已落地 fail-open 预算超限自动降级：",
        "- `NGA-WS26-004` 已落地锁泄漏清道夫与 fencing 联动：",
        "- `NGA-WS26-005` 已落地 double-fork/脱离进程树回收链：",
    ]
    if include_ws26_006:
        lines.append("- `NGA-WS26-006` 已落地 M11 混沌门禁：")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_runbook(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "python scripts/export_ws26_runtime_snapshot_ws26_002.py --output scratch/reports/ws26_runtime_snapshot_ws26_002.json",
                "python scripts/run_ws26_m11_runtime_chaos_suite_ws26_006.py --output scratch/reports/ws26_m11_runtime_chaos_ws26_006.json",
                "python scripts/validate_m11_closure_gate_ws26_006.py --runtime-snapshot-report scratch/reports/ws26_runtime_snapshot_ws26_002.json --m11-chaos-report scratch/reports/ws26_m11_runtime_chaos_ws26_006.json",
                "python scripts/release_closure_chain_m11_ws26_006.py",
                "python scripts/release_closure_chain_full_m0_m7.py --m11-output scratch/reports/release_closure_chain_m11_ws26_006_result.json",
            ]
        ),
        encoding="utf-8",
    )


def test_ws26_m11_closure_gate_passes_with_green_inputs() -> None:
    case_root = _make_case_root("test_ws26_release_gate")
    try:
        reports = case_root / "reports"
        _write_report(
            reports / "ws26_002.json",
            task_id="NGA-WS26-002",
            scenario="runtime_rollout_fail_open_lease_unified_snapshot",
            passed=True,
        )
        _write_report(
            reports / "ws26_006.json",
            task_id="NGA-WS26-006",
            scenario="m11_lock_logrotate_double_fork_chaos_suite",
            passed=True,
        )
        ws26_doc = case_root / "ws26.md"
        _write_ws26_doc(ws26_doc, include_ws26_006=True)
        runbook = case_root / "runbook.md"
        _write_runbook(runbook)

        result = evaluate_ws26_m11_closure_gate(
            ws26_doc_path=ws26_doc,
            runbook_path=runbook,
            runtime_snapshot_report_path=reports / "ws26_002.json",
            m11_chaos_report_path=reports / "ws26_006.json",
        )
        assert result["passed"] is True
        assert result["reasons"] == []
        assert result["checks"]["runtime_snapshot_gate"] is True
        assert result["checks"]["m11_chaos_gate"] is True
        assert result["checks"]["doc_gate"] is True
        assert result["checks"]["runbook_gate"] is True
    finally:
        _cleanup_case_root(case_root)


def test_ws26_m11_closure_gate_fails_when_doc_missing_ws26_006_snapshot() -> None:
    case_root = _make_case_root("test_ws26_release_gate")
    try:
        reports = case_root / "reports"
        _write_report(
            reports / "ws26_002.json",
            task_id="NGA-WS26-002",
            scenario="runtime_rollout_fail_open_lease_unified_snapshot",
            passed=True,
        )
        _write_report(
            reports / "ws26_006.json",
            task_id="NGA-WS26-006",
            scenario="m11_lock_logrotate_double_fork_chaos_suite",
            passed=True,
        )
        ws26_doc = case_root / "ws26.md"
        _write_ws26_doc(ws26_doc, include_ws26_006=False)
        runbook = case_root / "runbook.md"
        _write_runbook(runbook)

        result = evaluate_ws26_m11_closure_gate(
            ws26_doc_path=ws26_doc,
            runbook_path=runbook,
            runtime_snapshot_report_path=reports / "ws26_002.json",
            m11_chaos_report_path=reports / "ws26_006.json",
        )
        assert result["passed"] is False
        reasons = list(result["reasons"])
        assert any("doc:ws26_006_snapshot_entry" in item for item in reasons)
    finally:
        _cleanup_case_root(case_root)
