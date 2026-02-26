from __future__ import annotations

import shutil
import uuid
import json
from pathlib import Path

from scripts.release_closure_prompt_routing_ws28_006 import main


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_release_closure_prompt_routing_cli_main_smoke(monkeypatch) -> None:
    case_root = _make_case_root("test_release_closure_prompt_routing_ws28_006")
    try:
        output = case_root / "release_closure_prompt_routing_ws28_006.json"
        monkeypatch.setattr(
            "sys.argv",
            [
                "release_closure_prompt_routing_ws28_006.py",
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
        payload = json.loads(output.read_text(encoding="utf-8"))
        groups = {str(item.get("group_id")) for item in payload.get("group_results", [])}
        assert {
            "ws28_001",
            "ws28_002",
            "ws28_003",
            "ws28_004",
            "ws28_005",
            "ws28_007",
            "ws28_008",
            "ws28_009",
            "ws28_010",
            "ws28_011",
            "ws28_012",
        } <= groups
    finally:
        _cleanup_case_root(case_root)
