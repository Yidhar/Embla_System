from __future__ import annotations

import os
from pathlib import Path

import main as main_module


def test_main_bootstrap_brainstem_sets_owner_and_disables_api_lifespan(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv(main_module._BRAINSTEM_BOOTSTRAP_OWNER_ENV, raising=False)  # noqa: SLF001
    monkeypatch.delenv(main_module._BRAINSTEM_API_AUTOSTART_ENV, raising=False)  # noqa: SLF001
    monkeypatch.setenv(main_module._BRAINSTEM_MAIN_BOOTSTRAP_ENV, "1")  # noqa: SLF001

    manager = main_module.ServiceManager()

    def _manager(**kwargs):  # type: ignore[no-untyped-def]
        return {"passed": True, "action": kwargs.get("action"), "status": "already_running"}

    report = manager._bootstrap_brainstem_control_plane_main_startup(  # noqa: SLF001
        manager=_manager,
        api_autostart_enabled=True,
        repo_root=tmp_path,
    )
    assert report["enabled"] is True
    assert report["passed"] is True
    assert report["reason"] == "main_startup_managed"
    assert report["api_lifespan_autostart_disabled"] is True
    assert os.environ.get(main_module._BRAINSTEM_BOOTSTRAP_OWNER_ENV) == "main"  # noqa: SLF001
    assert os.environ.get(main_module._BRAINSTEM_API_AUTOSTART_ENV) == "0"  # noqa: SLF001


def test_main_bootstrap_brainstem_keeps_api_fallback_when_startup_failed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(main_module._BRAINSTEM_MAIN_BOOTSTRAP_ENV, "1")  # noqa: SLF001
    monkeypatch.delenv(main_module._BRAINSTEM_BOOTSTRAP_OWNER_ENV, raising=False)  # noqa: SLF001
    monkeypatch.setenv(main_module._BRAINSTEM_API_AUTOSTART_ENV, "1")  # noqa: SLF001

    manager = main_module.ServiceManager()

    def _manager(**kwargs):  # type: ignore[no-untyped-def]
        return {"passed": False, "action": kwargs.get("action"), "status": "start_failed"}

    report = manager._bootstrap_brainstem_control_plane_main_startup(  # noqa: SLF001
        manager=_manager,
        api_autostart_enabled=True,
        repo_root=tmp_path,
    )
    assert report["enabled"] is True
    assert report["passed"] is False
    assert report["reason"] == "main_startup_failed"
    assert report["api_lifespan_autostart_disabled"] is False
    assert os.environ.get(main_module._BRAINSTEM_BOOTSTRAP_OWNER_ENV) is None  # noqa: SLF001
    assert os.environ.get(main_module._BRAINSTEM_API_AUTOSTART_ENV) == "1"  # noqa: SLF001


def test_parse_main_args_supports_lightweight_mode() -> None:
    options = main_module.parse_main_args(["--lightweight"])
    assert options.lightweight is True
    assert options.effective_headless is True
