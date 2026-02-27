from __future__ import annotations

import json
from pathlib import Path

from scripts.embla_core_release_compat_gate import build_release_compat_report, write_report


def test_embla_core_release_compat_report_is_green() -> None:
    report = build_release_compat_report()
    assert report["task_id"] == "NGA-WS20-006-EMBLA-CORE"
    assert report["gate_mode"] == "embla_core_web_frontend"
    assert report["all_passed"] is True

    checks = {item["check_id"]: item for item in report["checks"]}
    assert checks["embla-core-root-present"]["passed"] is True
    assert checks["embla-core-next-scripts"]["passed"] is True
    assert checks["embla-core-runtime-routes"]["passed"] is True
    assert checks["embla-core-ops-api-wiring"]["passed"] is True


def test_embla_core_release_compat_report_can_be_written() -> None:
    report = build_release_compat_report()
    output_path = Path("scratch/test_embla_core_gate/embla_core_release_compat_report_test.json")
    written = write_report(report, output_path)
    assert written == output_path
    assert written.exists()

    saved = json.loads(written.read_text(encoding="utf-8"))
    assert saved["task_id"] == "NGA-WS20-006-EMBLA-CORE"
    assert isinstance(saved["checks"], list)
    written.unlink(missing_ok=True)
