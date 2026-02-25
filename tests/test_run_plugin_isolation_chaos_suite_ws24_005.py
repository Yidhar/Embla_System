from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from scripts.run_plugin_isolation_chaos_suite_ws24_005 import run_plugin_isolation_chaos_suite_ws24_005


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_ws24_005_plugin_isolation_chaos_suite_blocks_attack_samples() -> None:
    case_root = _make_case_root("test_run_plugin_isolation_chaos_suite_ws24_005")
    try:
        report = run_plugin_isolation_chaos_suite_ws24_005(
            output_file=case_root / "report.json",
            keep_temp=False,
            scratch_root=case_root / "runtime",
        )
        assert report["task_id"] == "NGA-WS24-005"
        assert report["scenario"] == "plugin_isolation_chaos_suite"
        assert report["passed"] is True
        assert report["failed_cases"] == []
        assert len(report["case_results"]) >= 4
    finally:
        _cleanup_case_root(case_root)
