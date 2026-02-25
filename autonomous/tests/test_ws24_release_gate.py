from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from autonomous.ws24_release_gate import evaluate_ws24_m9_closure_gate


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


def _write_ws24_doc(path: Path) -> None:
    path.write_text(
        """
## 8. 本轮推进快照（2026-02-25）
- `NGA-WS24-002` 已落地签名/清单/schema 校验：
- `NGA-WS24-003` 已落地资源限制与超时熔断：
- `NGA-WS24-004` 已落地生命周期与僵尸回收：
- `NGA-WS24-005` 已落地插件隔离混沌演练集：
- `NGA-WS24-006` 已落地 M9 门禁脚本 + Runbook：
""".strip(),
        encoding="utf-8",
    )


def _write_runbook(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
M9 chain:
python scripts/release_closure_chain_m9_ws24_006.py
gate:
python scripts/validate_m9_closure_gate_ws24_006.py
full chain:
python scripts/release_closure_chain_full_m0_m7.py
""".strip(),
        encoding="utf-8",
    )


def test_ws24_m9_gate_passes_with_valid_reports_and_doc() -> None:
    case_root = _make_case_root("test_ws24_release_gate")
    try:
        reports = case_root / "reports"
        _write_report(reports / "ws24_005.json", task_id="NGA-WS24-005", scenario="plugin_isolation_chaos_suite")
        ws24_doc = case_root / "ws24.md"
        _write_ws24_doc(ws24_doc)
        runbook = case_root / "runbook.md"
        _write_runbook(runbook)

        result = evaluate_ws24_m9_closure_gate(
            ws24_doc_path=ws24_doc,
            runbook_path=runbook,
            plugin_chaos_report_path=reports / "ws24_005.json",
        )
        assert result["passed"] is True
        assert result["reasons"] == []
    finally:
        _cleanup_case_root(case_root)


def test_ws24_m9_gate_fails_when_chaos_report_missing() -> None:
    case_root = _make_case_root("test_ws24_release_gate")
    try:
        ws24_doc = case_root / "ws24.md"
        _write_ws24_doc(ws24_doc)
        runbook = case_root / "runbook.md"
        _write_runbook(runbook)

        result = evaluate_ws24_m9_closure_gate(
            ws24_doc_path=ws24_doc,
            runbook_path=runbook,
            plugin_chaos_report_path=case_root / "reports" / "missing_ws24_005.json",
        )
        assert result["passed"] is False
        assert any(item.startswith("ws24_005:") for item in result["reasons"])
    finally:
        _cleanup_case_root(case_root)
