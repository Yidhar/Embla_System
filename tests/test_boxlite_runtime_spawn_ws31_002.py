from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.runtime.agent_session import AgentSessionStore
from agents.runtime.mailbox import AgentMailbox
from agents.runtime.parent_tools import handle_parent_tool_call


@pytest.fixture
def store():
    s = AgentSessionStore(db_path=":memory:")
    yield s
    s.close()


@pytest.fixture
def mailbox():
    m = AgentMailbox(db_path=":memory:")
    yield m
    m.close()


def test_spawn_child_agent_self_repo_prefers_boxlite_when_runtime_available(monkeypatch, store, mailbox):
    store.create(role="core", session_id="core-1")

    def _fake_create_git_worktree_sandbox(*, owner_session_id: str, ref: str = "HEAD", repo_root=None, git_runner=None):
        del git_runner, repo_root
        return type("Sandbox", (), {
            "to_metadata": lambda self: {
                "workspace_mode": "worktree",
                "workspace_sandbox_type": "git_worktree",
                "workspace_origin_root": "/repo",
                "workspace_root": f"/repo/scratch/agent_worktrees/{owner_session_id}",
                "workspace_ref": ref,
                "workspace_head_sha": "abc123",
                "workspace_owner_session_id": owner_session_id,
                "workspace_cleanup_on_destroy": True,
                "workspace_created_at": "2026-03-10T00:00:00+00:00",
            }
        })()

    monkeypatch.setattr("agents.runtime.parent_tools.create_git_worktree_sandbox", _fake_create_git_worktree_sandbox)
    monkeypatch.setattr(
        "agents.runtime.parent_tools.resolve_execution_runtime_metadata",
        lambda **kwargs: {
            "execution_backend_requested": "boxlite",
            "execution_backend": "boxlite",
            "execution_root": "/workspace",
            "execution_profile": "default",
            "box_profile": "default",
            "box_provider": "sdk",
            "box_mount_mode": "rw",
            "box_fallback_reason": "",
        },
    )

    result = handle_parent_tool_call(
        "spawn_child_agent",
        {
            "role": "dev",
            "task_description": "self maintenance",
            "workspace_mode": "worktree",
            "execution_backend": "boxlite",
        },
        parent_session_id="core-1",
        store=store,
        mailbox=mailbox,
    )

    session = store.get(result["agent_id"])
    assert session is not None
    assert session.metadata["execution_backend"] == "boxlite"
    assert session.metadata["execution_root"] == "/workspace"
    assert result["execution_backend"] == "boxlite"


def test_spawn_child_agent_falls_back_to_native_when_boxlite_unready(monkeypatch, store, mailbox):
    store.create(role="core", session_id="core-1")

    monkeypatch.setattr(
        "agents.runtime.parent_tools.resolve_execution_runtime_metadata",
        lambda **kwargs: {
            "execution_backend_requested": "boxlite",
            "execution_backend": "native",
            "execution_root": "/repo",
            "execution_profile": "default",
            "box_profile": "default",
            "box_provider": "sdk",
            "box_mount_mode": "rw",
            "box_fallback_reason": "boxlite_sdk_import_failed",
        },
    )

    result = handle_parent_tool_call(
        "spawn_child_agent",
        {
            "role": "dev",
            "task_description": "self maintenance",
            "workspace_mode": "project",
            "execution_backend": "boxlite",
        },
        parent_session_id="core-1",
        store=store,
        mailbox=mailbox,
    )

    assert result["status"] == "running"
    assert result["execution_backend"] == "native"


def test_resolve_execution_runtime_metadata_falls_back_to_native_when_boxlite_preferred_unavailable(monkeypatch):
    from system.boxlite.manager import resolve_execution_runtime_metadata

    monkeypatch.setattr(
        "system.boxlite.manager.get_config",
        lambda: type("Cfg", (), {
            "sandbox": type("Sandbox", (), {
                "default_execution_backend": "native",
                "self_repo_execution_backend": "boxlite",
                "boxlite": type("BoxLite", (), {
                    "enabled": True,
                    "mode": "preferred",
                    "provider": "sdk",
                    "base_url": "",
                    "image": "python:slim",
                    "working_dir": "/workspace",
                    "cpus": 2,
                    "memory_mib": 1024,
                    "auto_remove": True,
                    "security_preset": "maximum",
                    "network_enabled": False,
                })(),
            })(),
        })(),
    )
    monkeypatch.setattr(
        "system.boxlite.manager.probe_boxlite_runtime_readiness",
        lambda settings=None, **kwargs: type("Status", (), {
            "available": False,
            "reason": "boxlite_sdk_import_failed",
            "mode": "preferred",
            "provider": "sdk",
            "working_dir": "/workspace",
            "image": "python:slim",
        })(),
    )

    result = resolve_execution_runtime_metadata(
        requested_backend="boxlite",
        workspace_mode="worktree",
        workspace_root="/repo/scratch/agent_worktrees/agent-1",
        parent_metadata={},
    )

    assert result["execution_backend_requested"] == "boxlite"
    assert result["execution_backend"] == "native"
    assert result["box_fallback_reason"] == "boxlite_sdk_import_failed"


def test_resolve_execution_runtime_metadata_ensures_boxlite_readiness_inside_running_loop(monkeypatch):
    import system.boxlite.manager as manager

    monkeypatch.setattr(
        "system.boxlite.manager.get_config",
        lambda: type("Cfg", (), {
            "sandbox": type("Sandbox", (), {
                "default_execution_backend": "native",
                "self_repo_execution_backend": "boxlite",
                "boxlite": type("BoxLite", (), {
                    "enabled": True,
                    "mode": "required",
                    "provider": "sdk",
                    "base_url": "",
                    "image": "embla/boxlite-runtime:py311",
                    "working_dir": "/workspace",
                    "cpus": 2,
                    "memory_mib": 1024,
                    "auto_remove": True,
                    "security_preset": "maximum",
                    "network_enabled": False,
                    "runtime_profile": "default",
                    "core_ensure_before_spawn_enabled": True,
                })(),
            })(),
        })(),
    )
    ensure_calls = {"count": 0}

    def _fake_ensure(*args, **kwargs):
        del args, kwargs
        ensure_calls["count"] += 1
        return manager.BoxLiteRuntimeStatus(
            available=True,
            reason="",
            mode="required",
            provider="sdk",
            working_dir="/workspace",
            image="embla/boxlite-runtime:py311",
            runtime_profile="default",
            asset_name="embla_py311_default",
        )

    monkeypatch.setattr("system.boxlite.manager.ensure_boxlite_runtime_profile", _fake_ensure)
    monkeypatch.setattr(
        "system.boxlite.manager.probe_boxlite_runtime_readiness",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("spawn path should ensure before using BoxLite")),
    )

    async def _invoke():
        return manager.resolve_execution_runtime_metadata(
            requested_backend="boxlite",
            workspace_mode="worktree",
            workspace_root="/repo/scratch/agent_worktrees/agent-1",
            parent_metadata={},
            execution_profile="default",
        )

    result = asyncio.run(_invoke())

    assert result["execution_backend_requested"] == "boxlite"
    assert result["execution_backend"] == "boxlite"
    assert result["execution_root"] == "/workspace"
    assert result["box_provider"] == "sdk"
    assert ensure_calls["count"] == 1


def test_resolve_execution_runtime_metadata_falls_back_to_native_when_boxlite_unready_inside_running_loop(monkeypatch):
    import system.boxlite.manager as manager

    monkeypatch.setattr(
        "system.boxlite.manager.get_config",
        lambda: type("Cfg", (), {
            "sandbox": type("Sandbox", (), {
                "default_execution_backend": "native",
                "self_repo_execution_backend": "boxlite",
            })(),
        })(),
    )
    monkeypatch.setattr(
        "system.boxlite.manager.ensure_boxlite_runtime_profile",
        lambda *args, **kwargs: manager.BoxLiteRuntimeStatus(
            available=False,
            reason="boxlite_runtime_not_ready",
            mode="required",
            provider="sdk",
            working_dir="/workspace",
            image="embla/boxlite-runtime:py311",
            runtime_profile="default",
            asset_name="embla_py311_default",
        ),
    )

    async def _invoke():
        return manager.resolve_execution_runtime_metadata(
            requested_backend="boxlite",
            workspace_mode="worktree",
            workspace_root="/repo/scratch/agent_worktrees/agent-1",
            parent_metadata={},
            execution_profile="default",
        )

    result = asyncio.run(_invoke())

    assert result["execution_backend_requested"] == "boxlite"
    assert result["execution_backend"] == "native"
    assert result["execution_root"] == "/repo/scratch/agent_worktrees/agent-1"
    assert result["box_fallback_reason"] == "boxlite_runtime_not_ready"


def test_probe_boxlite_runtime_readiness_reports_image_pull_failure(monkeypatch):
    import system.boxlite.manager as manager

    manager.clear_boxlite_runtime_readiness_cache()
    monkeypatch.setattr(
        "system.boxlite.manager.probe_boxlite_runtime",
        lambda settings=None: manager.BoxLiteRuntimeStatus(
            available=True,
            reason="",
            mode="preferred",
            provider="sdk",
            working_dir="/workspace",
            image="python:slim",
        ),
    )
    monkeypatch.setattr(
        "system.boxlite.manager._run_async_sync",
        lambda coro: (coro.close(), (False, "boxlite_image_pull_failed:docker.io/library/python:slim"))[1],
    )

    status = manager.probe_boxlite_runtime_readiness(
        manager.BoxLiteRuntimeSettings(
            enabled=True,
            mode="preferred",
            provider="sdk",
            image="python:slim",
        ),
        force=True,
    )

    assert status.available is False
    assert status.reason.startswith("boxlite_image_pull_failed")


def test_probe_boxlite_runtime_readiness_uses_cache(monkeypatch):
    import system.boxlite.manager as manager

    manager.clear_boxlite_runtime_readiness_cache()
    monkeypatch.setattr(
        "system.boxlite.manager.probe_boxlite_runtime",
        lambda settings=None: manager.BoxLiteRuntimeStatus(
            available=True,
            reason="",
            mode="preferred",
            provider="sdk",
            working_dir="/workspace",
            image="python:slim",
        ),
    )
    calls = {"count": 0}

    def _fake_run_async_sync(coro):
        coro.close()
        calls["count"] += 1
        return True, ""

    monkeypatch.setattr("system.boxlite.manager._run_async_sync", _fake_run_async_sync)

    settings = manager.BoxLiteRuntimeSettings(enabled=True, mode="preferred", provider="sdk", image="python:slim")
    first = manager.probe_boxlite_runtime_readiness(settings, force=False)
    second = manager.probe_boxlite_runtime_readiness(settings, force=False)

    assert first.available is True
    assert second.available is True
    assert calls["count"] == 1


def test_run_async_sync_catches_baseexception_inside_running_loop():
    import system.boxlite.manager as manager

    class _Panic(BaseException):
        pass

    async def _explode():
        raise _Panic("PoisonError")

    async def _invoke():
        return manager._run_async_sync(_explode())

    ok, reason = asyncio.run(_invoke())

    assert ok is False
    assert reason.startswith("boxlite_runtime_panic")


def test_run_async_sync_closes_coro_when_thread_start_fails(monkeypatch):
    import system.boxlite.manager as manager

    closed = {"value": False}

    class _FakeCoroutine:
        def close(self):
            closed["value"] = True

    class _ExplodingThread:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def start(self):
            raise RuntimeError("thread spawn failed")

    monkeypatch.setattr("system.boxlite.manager.asyncio.get_running_loop", lambda: object())
    monkeypatch.setattr("system.boxlite.manager.threading.Thread", _ExplodingThread)

    ok, reason = manager._run_async_sync(_FakeCoroutine())

    assert ok is False
    assert closed["value"] is True
    assert "thread spawn failed" in reason


def test_classify_boxlite_runtime_error_treats_thread_exhaustion_as_panic():
    import system.boxlite.manager as manager

    reason = manager._classify_boxlite_runtime_error("can't start new thread")

    assert reason.startswith("boxlite_runtime_panic")


def test_probe_boxlite_runtime_auto_installs_missing_sdk(monkeypatch):
    import system.boxlite.manager as manager

    manager._BOXLITE_INSTALL_CACHE.clear()
    monkeypatch.setenv("EMBLA_BOXLITE_SKIP_KVM_CHECK", "1")

    installed = {"value": False}
    calls = []

    def _fake_import_module(name: str):
        if name != "boxlite":
            raise AssertionError(f"unexpected import: {name}")
        if not installed["value"]:
            raise ModuleNotFoundError("No module named 'boxlite'")
        return SimpleNamespace(__name__="boxlite")

    def _fake_run(cmd, capture_output=False, text=False, timeout=None, check=False):
        del capture_output, text, check
        calls.append({"cmd": list(cmd), "timeout": timeout})
        installed["value"] = True
        return SimpleNamespace(returncode=0, stdout="installed", stderr="")

    monkeypatch.setattr("system.boxlite.manager.importlib.import_module", _fake_import_module)
    monkeypatch.setattr("system.boxlite.manager.subprocess.run", _fake_run)
    monkeypatch.setattr("system.boxlite.manager._resolve_boxlite_python_executable", lambda: Path("/repo/.venv/bin/python"))

    status = manager.probe_boxlite_runtime(
        manager.BoxLiteRuntimeSettings(
            enabled=True,
            mode="required",
            provider="sdk",
            working_dir="/workspace",
            auto_install_sdk=True,
            install_timeout_seconds=42,
            sdk_package_spec="boxlite",
        )
    )

    assert status.available is True
    assert len(calls) == 1
    assert calls[0]["cmd"] == [
        "/repo/.venv/bin/python",
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "boxlite",
    ]
    assert calls[0]["timeout"] == 42


def test_probe_boxlite_runtime_reports_bootstrap_failure(monkeypatch):
    import system.boxlite.manager as manager

    manager._BOXLITE_INSTALL_CACHE.clear()

    def _fake_import_module(name: str):
        if name != "boxlite":
            raise AssertionError(f"unexpected import: {name}")
        raise ModuleNotFoundError("No module named 'boxlite'")

    def _fake_run(cmd, capture_output=False, text=False, timeout=None, check=False):
        del cmd, capture_output, text, timeout, check
        return SimpleNamespace(returncode=1, stdout="", stderr="network down")

    monkeypatch.setattr("system.boxlite.manager.importlib.import_module", _fake_import_module)
    monkeypatch.setattr("system.boxlite.manager.subprocess.run", _fake_run)
    monkeypatch.setattr("system.boxlite.manager._resolve_boxlite_python_executable", lambda: Path("/repo/.venv/bin/python"))

    status = manager.probe_boxlite_runtime(
        manager.BoxLiteRuntimeSettings(
            enabled=True,
            mode="required",
            provider="sdk",
            working_dir="/workspace",
            auto_install_sdk=True,
            install_timeout_seconds=30,
            sdk_package_spec="boxlite",
        )
    )

    assert status.available is False
    assert "boxlite_sdk_auto_install_failed" in status.reason


def test_probe_boxlite_runtime_rejects_inaccessible_kvm(monkeypatch):
    import system.boxlite.manager as manager

    manager._BOXLITE_INSTALL_CACHE.clear()
    monkeypatch.delenv("EMBLA_BOXLITE_SKIP_KVM_CHECK", raising=False)
    monkeypatch.setattr("system.boxlite.manager.importlib.import_module", lambda name: SimpleNamespace(__name__=name))

    class _FakePath:
        def __init__(self, value: str):
            self.value = str(value)

        def exists(self) -> bool:
            return self.value == "/dev/kvm"

        def __str__(self) -> str:
            return self.value

    monkeypatch.setattr("system.boxlite.manager.Path", _FakePath)
    monkeypatch.setattr("system.boxlite.manager.os.open", lambda path, flags: (_ for _ in ()).throw(PermissionError("permission denied")))

    status = manager.probe_boxlite_runtime(
        manager.BoxLiteRuntimeSettings(
            enabled=True,
            mode="required",
            provider="sdk",
            working_dir="/workspace",
            auto_install_sdk=False,
        )
    )

    assert status.available is False
    assert status.reason.startswith("boxlite_kvm_inaccessible")


def test_ensure_boxlite_runtime_profile_records_runtime_state(tmp_path, monkeypatch):
    import system.boxlite.manager as manager

    settings = manager.BoxLiteRuntimeSettings(
        enabled=True,
        mode="required",
        provider="sdk",
        runtime_profile="default",
        runtime_state_file=str(tmp_path / "scratch" / "runtime" / "boxlite_runtime_assets.json"),
        image="embla/runtime:py311",
        working_dir="/workspace",
        runtime_profiles={
            "default": manager.BoxLiteRuntimeProfile(
                name="default",
                image="embla/runtime:py311",
                working_dir="/workspace",
                prewarm_command=("python", "-V"),
            )
        },
    )

    monkeypatch.setattr(
        "system.boxlite.manager.probe_boxlite_runtime_readiness",
        lambda settings=None, **kwargs: manager.BoxLiteRuntimeStatus(
            available=True,
            reason="",
            mode=str(getattr(settings, "mode", "required") or "required"),
            provider=str(getattr(settings, "provider", "sdk") or "sdk"),
            working_dir=str(getattr(settings, "working_dir", "/workspace") or "/workspace"),
            image=str(getattr(settings, "image", "embla/runtime:py311") or "embla/runtime:py311"),
            runtime_profile=str(getattr(settings, "runtime_profile", "default") or "default"),
        ),
    )

    status = manager.ensure_boxlite_runtime_profile(settings, project_root=tmp_path, reason="unit_test")
    summary = manager.get_boxlite_runtime_assets_summary(settings, project_root=tmp_path)

    assert status.available is True
    assert summary["status"] == "ready"
    assert summary["active_profile"] == "default"
    assert summary["runtime_state_file"].endswith("boxlite_runtime_assets.json")
    assert summary["profiles"][0]["status"] == "ready"
    assert summary["profiles"][0]["last_action"] == "unit_test"


def test_probe_boxlite_runtime_readiness_falls_back_to_public_image_candidate(monkeypatch):
    import system.boxlite.manager as manager

    manager.clear_boxlite_runtime_readiness_cache()
    monkeypatch.setenv("EMBLA_BOXLITE_SKIP_KVM_CHECK", "1")
    monkeypatch.setattr("system.boxlite.manager.importlib.import_module", lambda name: SimpleNamespace(__name__=name))

    async def _fake_prewarm(runtime, **kwargs):
        del kwargs
        if str(getattr(runtime, "image", "") or "") == "embla/boxlite-runtime:py311":
            return False, "boxlite_image_pull_failed:embla/boxlite-runtime:py311"
        return True, ""

    monkeypatch.setattr("system.boxlite.manager._prewarm_boxlite_runtime", _fake_prewarm)

    status = manager.probe_boxlite_runtime_readiness(
        manager.BoxLiteRuntimeSettings(
            enabled=True,
            mode="required",
            provider="sdk",
            asset_name="embla_py311_default",
            image="embla/boxlite-runtime:py311",
            image_candidates=("embla/boxlite-runtime:py311", "python:slim"),
        ),
        force=True,
    )

    assert status.available is True
    assert status.asset_name == "embla_py311_default"
    assert status.image == "python:slim"


def test_build_local_boxlite_runtime_image_invokes_container_builder(tmp_path, monkeypatch):
    import system.boxlite.manager as manager

    context_dir = tmp_path / "system" / "boxlite" / "runtime_image"
    context_dir.mkdir(parents=True, exist_ok=True)
    (context_dir / "Dockerfile").write_text("FROM python:3.11-slim\n", encoding="utf-8")
    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if list(cmd)[1] == "version":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="built", stderr="")

    monkeypatch.setattr("system.boxlite.manager.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("system.boxlite.manager.subprocess.run", _fake_run)

    settings = manager.BoxLiteRuntimeSettings(
        enabled=True,
        provider="sdk",
        local_image_build_enabled=True,
        local_image_builder="docker",
        local_image_context_dir=str(context_dir.relative_to(tmp_path)),
        local_image_dockerfile="Dockerfile",
        runtime_profiles={
            "default": manager.BoxLiteRuntimeProfile(
                name="default",
                asset_name="embla_py311_default",
                image="embla/boxlite-runtime:py311",
            )
        },
    )

    result = manager.build_local_boxlite_runtime_image(settings, profile_name="default", project_root=tmp_path)

    assert result["ok"] is True
    assert result["builder"].endswith("docker")
    assert any(cmd[1] == "build" and "embla/boxlite-runtime:py311" in cmd for cmd in calls)


def test_prepare_boxlite_runtime_installation_builds_local_image_after_pull_failure(monkeypatch, tmp_path):
    import system.boxlite.manager as manager

    calls = {"ensure": 0}

    def _fake_ensure(settings=None, **kwargs):
        calls["ensure"] += 1
        if calls["ensure"] == 1:
            return manager.BoxLiteRuntimeStatus(
                available=False,
                reason="boxlite_image_pull_failed:embla/boxlite-runtime:py311",
                mode="required",
                provider="sdk",
                working_dir="/workspace",
                image="embla/boxlite-runtime:py311",
                runtime_profile="default",
                asset_name="embla_py311_default",
            )
        return manager.BoxLiteRuntimeStatus(
            available=True,
            reason="",
            mode="required",
            provider="sdk",
            working_dir="/workspace",
            image="embla/boxlite-runtime:py311",
            runtime_profile="default",
            asset_name="embla_py311_default",
        )

    monkeypatch.setattr("system.boxlite.manager.ensure_boxlite_runtime_profile", _fake_ensure)
    monkeypatch.setattr(
        "system.boxlite.manager.build_local_boxlite_runtime_image",
        lambda *args, **kwargs: {"ok": True, "builder": "docker", "image": "embla/boxlite-runtime:py311"},
    )
    monkeypatch.setattr(
        "system.boxlite.manager.get_boxlite_runtime_assets_summary",
        lambda *args, **kwargs: {"status": "ready", "profiles": [], "active_profile": "default"},
    )

    settings = manager.BoxLiteRuntimeSettings(
        enabled=True,
        provider="sdk",
        runtime_profiles={
            "default": manager.BoxLiteRuntimeProfile(
                name="default",
                asset_name="embla_py311_default",
                image="embla/boxlite-runtime:py311",
            )
        },
    )

    result = manager.prepare_boxlite_runtime_installation(settings, project_root=tmp_path)

    assert result["ok"] is True
    assert result["prepared_profiles"][0]["local_build"]["builder"] == "docker"
    assert calls["ensure"] == 2


def test_prewarm_boxlite_runtime_skips_teardown_when_box_never_opened(monkeypatch, tmp_path):
    import system.boxlite.manager as manager

    teardown_calls = []
    settings = manager.BoxLiteRuntimeSettings(
        enabled=True,
        mode="required",
        provider="sdk",
        runtime_profile="default",
        image="embla/boxlite-runtime:py311",
    )

    class _FakeManager:
        def __init__(self, settings=None):
            del settings
            self._boxes = {}

        def runtime_settings_for_profile(self, execution_profile: str | None = None):
            del execution_profile
            return settings

        async def exec_in_box(self, **kwargs):
            del kwargs
            raise RuntimeError("boxlite_runtime_error:ensure failed")

        async def teardown_box(self, box_ref: str, *, allow_runtime_init: bool = True):
            teardown_calls.append((box_ref, allow_runtime_init))
            return True, ""

    monkeypatch.setattr("system.boxlite.manager.BoxLiteManager", _FakeManager)

    ok, reason = asyncio.run(manager._prewarm_boxlite_runtime(settings, project_root=tmp_path))

    assert ok is False
    assert "ensure failed" in reason
    assert teardown_calls == []
