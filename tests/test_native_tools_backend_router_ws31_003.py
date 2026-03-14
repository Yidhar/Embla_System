from __future__ import annotations

import asyncio
from types import SimpleNamespace

from pathlib import Path

from agents.runtime.agent_session import AgentSessionStore
from apiserver.native_tools import NativeToolExecutor


def test_native_executor_routes_boxlite_session_and_falls_back_to_os_sandbox(monkeypatch):
    store = AgentSessionStore(db_path=":memory:")
    try:
        workspace_root = str((Path("scratch") / "agent_worktrees" / "agent-box").resolve())
        workspace_path = Path(workspace_root)
        workspace_path.mkdir(parents=True, exist_ok=True)
        (workspace_path / "README.md").write_text("boxlite fallback smoke\n", encoding="utf-8")
        store.create(
            role="dev",
            session_id="agent-box",
            metadata={
                "workspace_mode": "worktree",
                "workspace_root": workspace_root,
                "workspace_origin_root": str(Path(".").resolve()),
                "execution_backend": "boxlite",
                "execution_root": "/workspace",
            },
        )
        executor = NativeToolExecutor()
        executor.set_agent_session_store(store)

        monkeypatch.setattr(
            "system.execution_backend.registry.probe_boxlite_runtime_readiness",
            lambda *args, **kwargs: SimpleNamespace(available=False, reason="boxlite_sdk_import_failed", provider="sdk", working_dir="/workspace", image="python:slim"),
        )

        result = asyncio.run(
            executor.execute({"tool_name": "read_file", "path": "README.md"}, session_id="agent-box")
        )

        session = store.get("agent-box")
        assert result["status"] == "success"
        assert result["execution_backend"] == "os_sandbox"
        assert result["box_fallback_reason"] == "boxlite_sdk_import_failed"
        assert session is not None
        assert session.metadata["execution_backend"] == "os_sandbox"
    finally:
        store.close()


def test_native_executor_blocks_network_command_under_default_os_sandbox():
    store = AgentSessionStore(db_path=":memory:")
    try:
        workspace_root = str((Path("scratch") / "agent_worktrees" / "agent-os-sandbox").resolve())
        workspace_path = Path(workspace_root)
        workspace_path.mkdir(parents=True, exist_ok=True)
        store.create(
            role="dev",
            session_id="agent-os-sandbox",
            metadata={
                "workspace_mode": "worktree",
                "workspace_root": workspace_root,
                "workspace_origin_root": str(Path(".").resolve()),
                "execution_backend": "os_sandbox",
                "execution_backend_requested": "os_sandbox",
                "execution_root": workspace_root,
                "execution_profile": "default",
                "sandbox_policy": "default",
                "network_policy": "disabled",
                "resource_profile": "standard",
            },
        )
        executor = NativeToolExecutor()
        executor.set_agent_session_store(store)

        result = asyncio.run(
            executor.execute({"tool_name": "run_cmd", "command": "curl https://example.com"}, session_id="agent-os-sandbox")
        )

        assert result["status"] == "error"
        assert result["execution_backend"] == "os_sandbox"
        assert result["network_policy"] == "disabled"
        assert "network-disabled policy blocked command" in str(result["result"]).lower()
    finally:
        store.close()
