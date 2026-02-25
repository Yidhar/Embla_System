from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from scripts.run_ws27_longrun_endurance_ws27_001 import main


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_run_ws27_longrun_endurance_cli_main_smoke(monkeypatch) -> None:
    case_root = _make_case_root("test_run_ws27_longrun_endurance_ws27_001")
    try:
        output = case_root / "report.json"
        monkeypatch.setattr(
            "sys.argv",
            [
                "run_ws27_longrun_endurance_ws27_001.py",
                "--scratch-root",
                str(case_root / "runtime"),
                "--output",
                str(output),
                "--target-hours",
                "0.02",
                "--virtual-round-seconds",
                "6",
                "--artifact-payload-kb",
                "256",
                "--max-total-size-mb",
                "1",
                "--max-single-artifact-mb",
                "1",
                "--max-artifact-count",
                "256",
                "--high-watermark-ratio",
                "0.8",
                "--low-watermark-ratio",
                "0.5",
                "--critical-reserve-ratio",
                "0.1",
                "--normal-priority-every",
                "3",
                "--high-priority-every",
                "8",
            ],
        )
        exit_code = main()
        assert exit_code == 0
        assert output.exists() is True
    finally:
        _cleanup_case_root(case_root)
