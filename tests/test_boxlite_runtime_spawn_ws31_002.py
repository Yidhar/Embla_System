from __future__ import annotations

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


def test_spawn_child_agent_blocks_when_boxlite_required_but_unavailable(monkeypatch, store, mailbox):
    store.create(role="core", session_id="core-1")

    monkeypatch.setattr(
        "agents.runtime.parent_tools.resolve_execution_runtime_metadata",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boxlite runtime required but unavailable: boxlite_sdk_import_failed")),
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

    assert result["status"] == "blocked"
    assert "boxlite runtime required" in result["error"]


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
        "system.boxlite.manager.probe_boxlite_runtime",
        lambda settings=None: type("Status", (), {
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
