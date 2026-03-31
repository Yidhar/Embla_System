from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from scripts.export_killswitch_oob_bundle_ws23_004 import export_killswitch_oob_bundle


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_export_killswitch_oob_bundle_outputs_freeze_and_probe_plan() -> None:
    case_root = _make_case_root("test_export_killswitch_oob_bundle_ws23_004")
    try:
        report = export_killswitch_oob_bundle(
            oob_allowlist=["10.0.0.0/24", "bastion.example.com"],
            probe_targets=["10.0.0.10", "bastion.example.com"],
            output_file=case_root / "bundle.json",
            dns_allow=True,
            tcp_port=22,
            ping_timeout_seconds=2,
        )
        assert report["passed"] is True
        assert report["freeze_plan"]["validation_ok"] is True
        assert report["probe_plan"]["validation_ok"] is True
        assert (case_root / "bundle.json").exists()
    finally:
        _cleanup_case_root(case_root)


def test_export_killswitch_oob_bundle_rejects_probe_target_outside_allowlist() -> None:
    case_root = _make_case_root("test_export_killswitch_oob_bundle_ws23_004")
    try:
        with pytest.raises(ValueError, match="not covered by oob_allowlist"):
            export_killswitch_oob_bundle(
                oob_allowlist=["10.0.0.0/24"],
                probe_targets=["198.51.100.10"],
                output_file=case_root / "bundle.json",
            )
    finally:
        _cleanup_case_root(case_root)
