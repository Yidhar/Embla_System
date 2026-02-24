from __future__ import annotations

import json
from pathlib import Path

from scripts.desktop_release_compat_ws20_006 import build_release_compat_report, write_report


def test_ws20_006_release_compat_report_is_green() -> None:
    report = build_release_compat_report()
    assert report["task_id"] == "NGA-WS20-006"
    assert report["all_passed"] is True

    checks = {item["check_id"]: item for item in report["checks"]}
    assert "ws20-006-dist-scripts" in checks
    assert "ws20-006-builder-targets" in checks
    assert "ws20-006-network-offline-fallback" in checks
    assert "ws20-006-screen-capture-permission-fallback" in checks

    scenarios = {item["scenario_id"]: item for item in report["scenario_matrix"]}
    assert "net-offline-startup" in scenarios
    assert "permission-screen-capture-denied" in scenarios
    assert len(scenarios) >= 5


def test_ws20_006_report_can_be_written() -> None:
    report = build_release_compat_report()
    output_path = Path("scratch/test_ws20_006/ws20_006_release_compat_report_test.json")
    written = write_report(report, output_path)
    assert written == output_path
    assert written.exists()

    saved = json.loads(written.read_text(encoding="utf-8"))
    assert saved["task_id"] == "NGA-WS20-006"
    assert isinstance(saved["checks"], list)
    written.unlink(missing_ok=True)
