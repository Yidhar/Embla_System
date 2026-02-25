"""WS27-001 72h endurance and disk quota pressure baseline report."""

from __future__ import annotations

from pathlib import Path

from autonomous.ws27_longrun_endurance import WS27LongRunConfig, run_ws27_72h_endurance_baseline


def test_ws27_longrun_endurance_baseline_report() -> None:
    report_path = Path("scratch/reports/ws27_72h_endurance_ws27_001.test.json")
    report = run_ws27_72h_endurance_baseline(
        scratch_root=Path("scratch/test_ws27_72h_endurance"),
        report_file=report_path,
        config=WS27LongRunConfig(
            target_hours=0.02,
            virtual_round_seconds=6.0,
            artifact_payload_kb=256,
            max_total_size_mb=1,
            max_single_artifact_mb=1,
            max_artifact_count=256,
            high_watermark_ratio=0.8,
            low_watermark_ratio=0.5,
            critical_reserve_ratio=0.1,
            normal_priority_every=3,
            high_priority_every=8,
        ),
    )

    metrics = report["metrics"]
    checks = report["checks"]
    assert report["passed"] is True
    assert checks["virtual_72h_target_reached"] is True
    assert checks["no_enospc"] is True
    assert checks["no_unhandled_exceptions"] is True
    assert checks["no_event_loss"] is True
    assert checks["disk_quota_pressure_exercised"] is True
    assert metrics["virtual_elapsed_seconds"] >= metrics["virtual_target_seconds"]
    assert metrics["pressure_signal_total"] > 0
    assert metrics["event_loss_count"] == 0
    assert report_path.exists()
