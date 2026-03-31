from __future__ import annotations

from pathlib import Path


def test_tool_loop_shim_file_is_removed_ws28_033() -> None:
    assert not Path("apiserver/agentic_tool_loop.py").exists()


def test_immutable_dna_shim_file_is_removed_ws28_033() -> None:
    assert not Path("system/immutable_dna.py").exists()
