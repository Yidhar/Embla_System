from __future__ import annotations

from pathlib import Path

import apiserver.api_server as api_server


def test_brainstem_bootstrap_startup_skips_by_default_under_pytest(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv(api_server._BRAINSTEM_AUTOSTART_ENV, raising=False)  # noqa: SLF001
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "yes")
    called = {"value": False}

    def _manager(**kwargs):  # type: ignore[no-untyped-def]
        called["value"] = True
        return {"passed": True}

    report = api_server._bootstrap_brainstem_control_plane_startup(  # noqa: SLF001
        manager=_manager,
        repo_root=tmp_path,
    )
    assert report["enabled"] is False
    assert report["reason"] == "pytest_default_skip"
    assert called["value"] is False


def test_brainstem_bootstrap_startup_runs_when_enabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(api_server._BRAINSTEM_AUTOSTART_ENV, "1")  # noqa: SLF001
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    captured = {"action": ""}

    def _manager(**kwargs):  # type: ignore[no-untyped-def]
        captured["action"] = str(kwargs.get("action") or "")
        return {"passed": True, "action": kwargs.get("action"), "output_file": str(kwargs.get("output_file"))}

    report = api_server._bootstrap_brainstem_control_plane_startup(  # noqa: SLF001
        manager=_manager,
        repo_root=tmp_path,
    )
    assert report["enabled"] is True
    assert report["passed"] is True
    assert captured["action"] == "start"
    startup_report = report.get("startup_report")
    assert isinstance(startup_report, dict)
    assert startup_report.get("action") == "start"


def test_brainstem_bootstrap_startup_skips_when_owned_by_main(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(api_server._BRAINSTEM_AUTOSTART_ENV, "1")  # noqa: SLF001
    monkeypatch.setenv(api_server._BRAINSTEM_BOOTSTRAP_OWNER_ENV, "main")  # noqa: SLF001
    called = {"value": False}

    def _manager(**kwargs):  # type: ignore[no-untyped-def]
        called["value"] = True
        return {"passed": True}

    report = api_server._bootstrap_brainstem_control_plane_startup(  # noqa: SLF001
        manager=_manager,
        repo_root=tmp_path,
    )
    assert report["enabled"] is False
    assert report["reason"] == "owned_by_main"
    assert called["value"] is False


def test_brainstem_bootstrap_shutdown_runs_only_when_enabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(api_server._BRAINSTEM_AUTOSTOP_ENV, "true")  # noqa: SLF001
    captured = {"action": ""}

    def _manager(**kwargs):  # type: ignore[no-untyped-def]
        captured["action"] = str(kwargs.get("action") or "")
        return {"passed": True, "action": kwargs.get("action")}

    report = api_server._bootstrap_brainstem_control_plane_shutdown(  # noqa: SLF001
        manager=_manager,
        repo_root=tmp_path,
    )
    assert report["enabled"] is True
    assert report["passed"] is True
    assert captured["action"] == "stop"


def test_brainstem_bootstrap_shutdown_skips_when_owned_by_main(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(api_server._BRAINSTEM_AUTOSTOP_ENV, "true")  # noqa: SLF001
    monkeypatch.setenv(api_server._BRAINSTEM_BOOTSTRAP_OWNER_ENV, "main")  # noqa: SLF001
    called = {"value": False}

    def _manager(**kwargs):  # type: ignore[no-untyped-def]
        called["value"] = True
        return {"passed": True}

    report = api_server._bootstrap_brainstem_control_plane_shutdown(  # noqa: SLF001
        manager=_manager,
        repo_root=tmp_path,
    )
    assert report["enabled"] is False
    assert report["reason"] == "owned_by_main"
    assert called["value"] is False


def test_global_mutex_bootstrap_initializes_idle_state(tmp_path: Path) -> None:
    class _DummyManager:
        def __init__(self, state_file: Path) -> None:
            self.state_file = state_file

        def ensure_initialized(self, *, ttl_seconds: float):  # noqa: ARG002
            payload = {
                "lease_state": "idle",
                "fencing_epoch": 0,
            }
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text("{}", encoding="utf-8")
            return payload

    state_file = tmp_path / "logs" / "runtime" / "global_mutex_lease.json"
    report = api_server._bootstrap_global_mutex_lease_state(  # noqa: SLF001
        manager_factory=lambda: _DummyManager(state_file),
    )
    assert report["enabled"] is True
    assert report["passed"] is True
    assert report["state"] == "idle"
    assert report["fencing_epoch"] == 0
    assert report["state_file"].endswith("global_mutex_lease.json")


def test_budget_guard_bootstrap_initializes_baseline_state(tmp_path: Path) -> None:
    report = api_server._bootstrap_budget_guard_state(  # noqa: SLF001
        repo_root=tmp_path,
    )
    assert report["enabled"] is True
    assert report["passed"] is True
    assert report["baseline_written"] is True
    assert report["status"] == "ok"
    assert report["reason_code"] == "BUDGET_GUARD_BASELINE_READY"
    assert report["state_file"].endswith("budget_guard_state_ws28_028.json")

    second = api_server._bootstrap_budget_guard_state(  # noqa: SLF001
        repo_root=tmp_path,
    )
    assert second["passed"] is True
    assert second["baseline_written"] is False
