from __future__ import annotations

import asyncio
from types import SimpleNamespace

from pathlib import Path

from agents.runtime.agent_session import AgentSessionStore
from apiserver.native_tools import NativeToolExecutor


def test_native_executor_routes_boxlite_session_and_surfaces_backend_unavailable(monkeypatch):
    store = AgentSessionStore(db_path=":memory:")
    try:
        workspace_root = str((Path("scratch") / "agent_worktrees" / "agent-box").resolve())
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
            "system.execution_backend.registry.probe_boxlite_runtime",
            lambda: SimpleNamespace(available=False, reason="boxlite_sdk_import_failed", provider="sdk", working_dir="/workspace", image="python:slim"),
        )

        result = asyncio.run(
            executor.execute({"tool_name": "read_file", "path": "README.md"}, session_id="agent-box")
        )

        assert result["status"] == "error"
        assert "boxlite" in str(result["result"]).lower()
    finally:
        store.close()
