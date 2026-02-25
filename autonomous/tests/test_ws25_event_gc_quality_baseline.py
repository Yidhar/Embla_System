from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from autonomous.ws25_event_gc_quality_baseline import WS25EventGCQualityConfig, run_ws25_event_gc_quality_baseline


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_ws25_event_gc_quality_baseline_report_is_green() -> None:
    case_root = _make_case_root("test_ws25_event_gc_quality_baseline")
    try:
        report_path = case_root / "report.json"
        report = run_ws25_event_gc_quality_baseline(
            scratch_root=case_root / "runtime",
            report_file=report_path,
            config=WS25EventGCQualityConfig(replay_event_count=3, gc_iterations=2),
        )
        assert report["task_id"] == "NGA-WS25-005"
        assert report["scenario"] == "event_gc_quality_baseline"
        assert report["passed"] is True
        assert report["checks"]["replay_idempotency"] is True
        assert report["checks"]["critical_evidence_preservation"] is True
        assert report["checks"]["gc_quality_thresholds"] is True
        assert report_path.exists() is True
    finally:
        _cleanup_case_root(case_root)
