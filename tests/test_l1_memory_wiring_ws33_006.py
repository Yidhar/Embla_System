"""Tests for L1 memory singleton wiring and L2 hook registration.

Workstream: ws33  Sequence: 006
"""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. get_default_l1_manager() returns a singleton
# ---------------------------------------------------------------------------

def test_get_default_l1_manager_returns_singleton(tmp_path):
    """Calling get_default_l1_manager() twice yields the same object."""
    import agents.memory.l1_memory as mod

    # Reset module-level singleton so this test is hermetic
    original = mod._DEFAULT_L1_MANAGER
    try:
        mod._DEFAULT_L1_MANAGER = None
        with patch.object(mod, "_DEFAULT_MEMORY_ROOT", tmp_path):
            mgr1 = mod.get_default_l1_manager()
            mgr2 = mod.get_default_l1_manager()
            assert mgr1 is mgr2
    finally:
        mod._DEFAULT_L1_MANAGER = original


# ---------------------------------------------------------------------------
# 2. Singleton auto-creates episodic/ directory and _index.md
# ---------------------------------------------------------------------------

def test_episodic_dir_auto_created(tmp_path):
    """The singleton factory must create memory/episodic/ and its _index.md."""
    import agents.memory.l1_memory as mod

    original = mod._DEFAULT_L1_MANAGER
    try:
        mod._DEFAULT_L1_MANAGER = None
        with patch.object(mod, "_DEFAULT_MEMORY_ROOT", tmp_path):
            mgr = mod.get_default_l1_manager()
            episodic_dir = mgr._episodic_dir
            assert episodic_dir.is_dir()
            index_file = episodic_dir / "_index.md"
            assert index_file.exists()
            assert "auto-generated" in index_file.read_text(encoding="utf-8")
    finally:
        mod._DEFAULT_L1_MANAGER = original


# ---------------------------------------------------------------------------
# 3. register_l1_to_l2_hooks registers the hook
# ---------------------------------------------------------------------------

def test_register_l1_to_l2_hooks_adds_hook(tmp_path):
    """register_l1_to_l2_hooks() should append a post-write hook."""
    from agents.memory.l1_memory import L1MemoryManager
    from agents.memory.l1_to_l2_sync import register_l1_to_l2_hooks

    mgr = L1MemoryManager(memory_root=str(tmp_path))
    assert len(mgr._post_write_hooks) == 0
    register_l1_to_l2_hooks(mgr)
    assert len(mgr._post_write_hooks) == 1


def test_register_l1_to_l2_hook_callable(tmp_path):
    """The registered hook must be callable with (episodic_dir, tags)."""
    from agents.memory.l1_memory import L1MemoryManager
    from agents.memory.l1_to_l2_sync import register_l1_to_l2_hooks

    mgr = L1MemoryManager(memory_root=str(tmp_path))
    register_l1_to_l2_hooks(mgr)
    hook = mgr._post_write_hooks[0]
    # Should not raise even when episodic dir doesn't exist
    hook(tmp_path / "episodic", ["test_tag"])


# ---------------------------------------------------------------------------
# 4. handle_memory_tool uses the singleton (no fresh L1MemoryManager)
# ---------------------------------------------------------------------------

def test_handle_memory_tool_uses_singleton(tmp_path):
    """handle_memory_tool() without explicit manager must use get_default_l1_manager()."""
    import agents.memory.l1_memory as l1_mod
    import agents.memory.memory_tools as mt_mod

    original = l1_mod._DEFAULT_L1_MANAGER
    try:
        l1_mod._DEFAULT_L1_MANAGER = None
        with patch.object(l1_mod, "_DEFAULT_MEMORY_ROOT", tmp_path):
            # Ensure episodic dir exists for list operation
            (tmp_path / "episodic").mkdir(parents=True, exist_ok=True)
            (tmp_path / "working").mkdir(parents=True, exist_ok=True)
            (tmp_path / "domain").mkdir(parents=True, exist_ok=True)

            result = mt_mod.handle_memory_tool("memory_list", {"scope": "all"})
            assert result["status"] == "success"

            # The singleton should now be set
            assert l1_mod._DEFAULT_L1_MANAGER is not None
    finally:
        l1_mod._DEFAULT_L1_MANAGER = original


def test_handle_memory_tool_explicit_manager_skips_singleton(tmp_path):
    """Passing an explicit manager should bypass the singleton."""
    from agents.memory.l1_memory import L1MemoryManager
    from agents.memory.memory_tools import handle_memory_tool

    mgr = L1MemoryManager(memory_root=str(tmp_path))
    (tmp_path / "episodic").mkdir(parents=True, exist_ok=True)
    (tmp_path / "working").mkdir(parents=True, exist_ok=True)
    (tmp_path / "domain").mkdir(parents=True, exist_ok=True)

    result = handle_memory_tool("memory_list", {"scope": "all"}, manager=mgr)
    assert result["status"] == "success"
