from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

from system.boxlite.manager import (
    BoxLiteManager,
    BoxLiteRuntimeStatus,
    _resolve_boxlite_network_mode,
    build_box_session_name,
    build_boxlite_volume_mounts,
    teardown_box_session,
)


def test_build_box_session_name_uses_embla_prefix() -> None:
    assert build_box_session_name("agent-123") == "embla-agent-123"
    assert build_box_session_name("") == "embla-session"


def test_teardown_box_session_prefers_box_id(monkeypatch) -> None:
    calls = []

    class _FakeManager:
        async def teardown_box(self, box_ref: str):
            calls.append(box_ref)
            return True, ""

    monkeypatch.setattr("system.boxlite.manager.BoxLiteManager", _FakeManager)

    ok, error = teardown_box_session({"box_id": "box-123", "box_name": "embla-agent-123"})

    assert ok is True
    assert error == ""
    assert calls == ["box-123"]


def test_teardown_box_session_falls_back_to_box_name(monkeypatch) -> None:
    calls = []

    class _FakeManager:
        async def teardown_box(self, box_ref: str):
            calls.append(box_ref)
            return True, ""

    monkeypatch.setattr("system.boxlite.manager.BoxLiteManager", _FakeManager)

    ok, error = teardown_box_session({"box_name": "embla-agent-456"})

    assert ok is True
    assert error == ""
    assert calls == ["embla-agent-456"]


def test_build_boxlite_volume_mounts_includes_workspace_project_and_venv(tmp_path) -> None:
    project_root = tmp_path / "repo"
    workspace_root = project_root / "scratch" / "agent_worktrees" / "agent-123"
    workspace_root.mkdir(parents=True)
    (project_root / ".venv" / "bin").mkdir(parents=True)

    mounts = build_boxlite_volume_mounts(
        workspace_host_root=str(workspace_root),
        working_dir="/workspace",
        project_root=str(project_root),
    )

    assert (str(workspace_root.resolve()), "/workspace", False) in mounts
    assert (str(project_root.resolve()), str(project_root.resolve()), True) in mounts
    assert (str((project_root / ".venv").resolve()), "/workspace/.venv", True) in mounts


def test_build_boxlite_volume_mounts_match_sdk_tuple_contract(tmp_path) -> None:
    boxlite = importlib.import_module("boxlite")
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    mounts = build_boxlite_volume_mounts(
        workspace_host_root=str(workspace_root),
        working_dir="/workspace",
    )

    options = boxlite.BoxOptions(
        image="python:slim",
        working_dir="/workspace",
        volumes=mounts,
    )

    assert options is not None


def test_boxlite_network_mode_matches_sdk_contract() -> None:
    boxlite = importlib.import_module("boxlite")

    disabled = boxlite.BoxOptions(network=_resolve_boxlite_network_mode(False))
    enabled = boxlite.BoxOptions(network=_resolve_boxlite_network_mode(True))

    assert disabled is not None
    assert enabled is not None


def test_teardown_box_skips_runtime_init_when_disallowed(monkeypatch) -> None:
    default_called = {"value": False}

    def _default():
        default_called["value"] = True
        raise AssertionError("should not initialize runtime")

    monkeypatch.setitem(sys.modules, "boxlite", SimpleNamespace(Boxlite=SimpleNamespace(default=staticmethod(_default))))

    ok, error = asyncio.run(BoxLiteManager().teardown_box("box-123", allow_runtime_init=False))

    assert ok is True
    assert error == ""
    assert default_called["value"] is False


def test_teardown_box_classifies_runtime_init_panic(monkeypatch) -> None:
    class _Panic(BaseException):
        pass

    def _default():
        raise _Panic("PoisonError")

    monkeypatch.setattr(
        "system.boxlite.manager.BoxLiteManager.availability",
        lambda self, execution_profile=None: BoxLiteRuntimeStatus(
            available=True,
            reason="",
            mode="required",
            provider="sdk",
            working_dir="/workspace",
            image="embla/boxlite-runtime:py311",
        ),
    )
    monkeypatch.setitem(sys.modules, "boxlite", SimpleNamespace(Boxlite=SimpleNamespace(default=staticmethod(_default))))

    ok, error = asyncio.run(BoxLiteManager().teardown_box("box-123"))

    assert ok is False
    assert error.startswith("boxlite_runtime_panic")
