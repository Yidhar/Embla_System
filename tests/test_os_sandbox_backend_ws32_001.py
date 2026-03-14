from __future__ import annotations

from pathlib import Path

import pytest

from system.execution_backend.os_sandbox_backend import OsSandboxExecutionBackend
from system.execution_backend.registry import ExecutionBackendRegistry
from system.sandbox_context import SandboxContext, normalize_execution_backend


def test_normalize_execution_backend_supports_os_sandbox_aliases() -> None:
    assert normalize_execution_backend("os_sandbox") == "os_sandbox"
    assert normalize_execution_backend("sandbox") == "os_sandbox"
    assert normalize_execution_backend("worktree") == "os_sandbox"
    assert normalize_execution_backend("os_sandbox_worktree") == "os_sandbox"


def test_registry_resolves_os_sandbox_backend() -> None:
    registry = ExecutionBackendRegistry()
    context = SandboxContext(
        session_id="dev-1",
        workspace_mode="worktree",
        workspace_host_root="/repo/scratch/agent_worktrees/dev-1",
        execution_backend="os_sandbox",
        execution_backend_requested="os_sandbox",
        execution_root="/repo/scratch/agent_worktrees/dev-1",
    )

    backend = registry.resolve(context)

    assert isinstance(backend, OsSandboxExecutionBackend)
    assert backend.name == "os_sandbox"


def test_os_sandbox_backend_rewrites_into_worktree_root() -> None:
    backend = OsSandboxExecutionBackend()
    workspace_root = str((Path("/repo") / "scratch" / "agent_worktrees" / "dev-1").resolve())
    context = SandboxContext(
        session_id="dev-1",
        workspace_mode="worktree",
        workspace_host_root=workspace_root,
        execution_backend="os_sandbox",
        execution_backend_requested="os_sandbox",
        execution_root=workspace_root,
    )
    native_tool_executor = type("Executor", (), {"project_root": "/repo"})()

    call = backend.prepare_call(
        "run_cmd",
        {"command": "pytest -q", "cwd": "."},
        context=context,
        native_tool_executor=native_tool_executor,
    )

    assert call["_execution_backend"] == "os_sandbox"
    assert call["_execution_root"] == workspace_root
    assert call["_session_workspace_root"] == workspace_root
    assert call["_sandbox_policy"] == "default"
    assert call["_network_policy"] == "disabled"
    assert call["_resource_profile"] == "standard"
    assert call["cwd"] == workspace_root
    assert call["timeout_seconds"] == 120
    assert call["_sandbox_network_enabled"] is False
    assert call["_execution_env"]["NO_PROXY"] == "*"
    assert call["_execution_env"]["UV_OFFLINE"] == "1"


def test_os_sandbox_backend_applies_profile_specific_limits(monkeypatch) -> None:
    backend = OsSandboxExecutionBackend()
    workspace_root = str((Path("/repo") / "scratch" / "agent_worktrees" / "dev-1").resolve())
    context = SandboxContext(
        session_id="dev-1",
        workspace_mode="worktree",
        workspace_host_root=workspace_root,
        execution_backend="os_sandbox",
        execution_backend_requested="os_sandbox",
        execution_root=workspace_root,
        execution_profile="heavy",
        sandbox_policy="heavy",
        network_policy="disabled",
        resource_profile="heavy",
    )
    native_tool_executor = type("Executor", (), {"project_root": "/repo"})()

    monkeypatch.setattr(
        "system.execution_backend.runtime_policy.get_config",
        lambda: type("Cfg", (), {
            "sandbox": type("Sandbox", (), {
                "os_sandbox": type("OsSandbox", (), {
                    "runtime_profile": "default",
                    "enforce_network_guard": True,
                    "runtime_profiles": {
                        "heavy": type("Profile", (), {
                            "resource_profile": "heavy",
                            "network_enabled": False,
                            "inject_offline_env": True,
                            "default_command_timeout_seconds": 300,
                            "max_command_timeout_seconds": 1800,
                            "default_python_timeout_seconds": 60,
                            "max_python_timeout_seconds": 600,
                            "default_watch_timeout_seconds": 1800,
                            "max_watch_timeout_seconds": 86400,
                        })(),
                    },
                })(),
            })(),
        })(),
    )

    run_call = backend.prepare_call(
        "run_cmd",
        {"command": "pytest -q", "timeout_seconds": 99999},
        context=context,
        native_tool_executor=native_tool_executor,
    )
    py_call = backend.prepare_call(
        "python_repl",
        {"expression": "1 + 1", "timeout_seconds": 99999},
        context=context,
        native_tool_executor=native_tool_executor,
    )

    assert run_call["timeout_seconds"] == 1800
    assert py_call["timeout_seconds"] == 600
    assert run_call["_resource_profile"] == "heavy"


def test_os_sandbox_backend_rejects_absolute_escape() -> None:
    backend = OsSandboxExecutionBackend()
    workspace_root = str((Path("/repo") / "scratch" / "agent_worktrees" / "dev-1").resolve())
    context = SandboxContext(
        session_id="dev-1",
        workspace_mode="worktree",
        workspace_host_root=workspace_root,
        execution_backend="os_sandbox",
        execution_backend_requested="os_sandbox",
        execution_root=workspace_root,
    )
    native_tool_executor = type("Executor", (), {"project_root": "/repo"})()

    with pytest.raises(ValueError, match="path escapes worktree root"):
        backend.prepare_call(
            "read_file",
            {"path": "/repo/system/config.py"},
            context=context,
            native_tool_executor=native_tool_executor,
        )
