"""WS22-004 long-run equivalent baseline and metrics report."""

from __future__ import annotations

from pathlib import Path

from autonomous.ws22_longrun_baseline import WS22LongRunConfig, run_ws22_longrun_baseline


def test_ws22_longrun_equivalent_baseline_report() -> None:
    report_path = Path("scratch/reports/ws22_scheduler_longrun_baseline.json")
    report = run_ws22_longrun_baseline(
        scratch_root=Path("scratch/test_ws22_longrun_baseline"),
        report_file=report_path,
        config=WS22LongRunConfig(
            rounds=120,
            virtual_round_seconds=5.0,
            fail_open_every=15,
            lease_renew_every=20,
        ),
    )

    metrics = report["metrics"]
    assert report["passed"] is True
    assert metrics["virtual_elapsed_seconds"] >= 600
    assert metrics["task_approved_count"] == 112
    assert metrics["task_rejected_count"] == 8
    assert metrics["failed_exhausted_count"] == 8
    assert metrics["event_mismatch_count"] == 0
    assert metrics["unhandled_exception_count"] == 0
    assert metrics["service_value_matches_expected"] is True
    assert report_path.exists()
