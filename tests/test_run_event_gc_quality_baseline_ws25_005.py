from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from scripts.run_event_gc_quality_baseline_ws25_005 import main


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_run_event_gc_quality_baseline_cli_main_smoke(monkeypatch) -> None:
    case_root = _make_case_root("test_run_event_gc_quality_baseline_ws25_005")
    try:
        output = case_root / "report.json"
        monkeypatch.setattr(
            "sys.argv",
            [
                "run_event_gc_quality_baseline_ws25_005.py",
                "--scratch-root",
                str(case_root / "runtime"),
                "--output",
                str(output),
                "--replay-event-count",
                "3",
                "--gc-iterations",
                "1",
            ],
        )
        exit_code = main()
        assert exit_code == 0
        assert output.exists() is True
    finally:
        _cleanup_case_root(case_root)
