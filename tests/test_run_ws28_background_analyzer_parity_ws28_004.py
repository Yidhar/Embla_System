from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from scripts.run_ws28_background_analyzer_parity_ws28_004 import main


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_run_ws28_background_analyzer_parity_cli_main_smoke(monkeypatch) -> None:
    case_root = _make_case_root("test_run_ws28_background_analyzer_parity_ws28_004")
    try:
        output = case_root / "ws28_004_analyzer_parity.json"
        monkeypatch.setattr(
            "sys.argv",
            [
                "run_ws28_background_analyzer_parity_ws28_004.py",
                "--repo-root",
                ".",
                "--output",
                str(output),
                "--strict",
            ],
        )
        exit_code = main()
        assert exit_code == 0
        assert output.exists() is True
    finally:
        _cleanup_case_root(case_root)
