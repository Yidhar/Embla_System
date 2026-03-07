from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import apiserver.native_tools as native_tools_module
from agents.runtime.agent_session import AgentSessionStore
from apiserver.native_tools import NativeToolExecutor


@pytest.fixture
def store() -> AgentSessionStore:
    session_store = AgentSessionStore(db_path=":memory:")
    yield session_store
    session_store.close()


@pytest.fixture
def cleanup_paths() -> list[Path]:
    paths: list[Path] = []
    yield paths
    for path in reversed(paths):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)


def _register_workspace_session(store: AgentSessionStore, *, session_id: str, workspace_root: Path) -> None:
    store.create(
        role="dev",
        session_id=session_id,
        metadata={
            "workspace_mode": "worktree",
            "workspace_root": str(workspace_root.resolve()),
            "workspace_origin_root": str(Path('.').resolve()),
        },
    )


def test_read_file_uses_session_workspace_root(store: AgentSessionStore, cleanup_paths: list[Path]) -> None:
    workspace_root = Path("scratch/agent_worktrees/ws30_009_read")
    shutil.rmtree(workspace_root, ignore_errors=True)
    cleanup_paths.append(workspace_root)
    target = workspace_root / "system" / "config.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("session-root-read\n", encoding="utf-8")

    _register_workspace_session(store, session_id="agent-read", workspace_root=workspace_root)
    executor = NativeToolExecutor()
    executor.set_agent_session_store(store)

    result = asyncio.run(
        executor.execute(
            {"tool_name": "read_file", "path": "system/config.txt"},
            session_id="agent-read",
        )
    )

    assert result["status"] == "success"
    assert "session-root-read" in str(result["result"])


def test_write_file_uses_session_workspace_root_and_tolerates_public_session_id(
    store: AgentSessionStore,
    cleanup_paths: list[Path],
) -> None:
    workspace_root = Path("scratch/agent_worktrees/ws30_009_write")
    project_leak = Path("ws30_009_write")
    shutil.rmtree(workspace_root, ignore_errors=True)
    shutil.rmtree(project_leak, ignore_errors=True)
    cleanup_paths.extend([project_leak, workspace_root])

    _register_workspace_session(store, session_id="agent-write", workspace_root=workspace_root)
    executor = NativeToolExecutor()
    executor.set_agent_session_store(store)

    result = asyncio.run(
        executor.execute(
            {
                "tool_name": "write_file",
                "path": "ws30_009_write/output.txt",
                "content": "session-root-write\n",
                "session_id": "agent-write",
            },
            session_id="agent-write",
        )
    )

    written = workspace_root / "ws30_009_write" / "output.txt"
    assert result["status"] == "success"
    assert written.read_text(encoding="utf-8") == "session-root-write\n"
    assert not project_leak.exists()


def test_search_keyword_defaults_to_session_workspace_root(
    monkeypatch: pytest.MonkeyPatch,
    store: AgentSessionStore,
    cleanup_paths: list[Path],
) -> None:
    workspace_root = Path("scratch/agent_worktrees/ws30_009_search")
    shutil.rmtree(workspace_root, ignore_errors=True)
    cleanup_paths.append(workspace_root)
    target = workspace_root / "docs" / "needle.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("SESSION_ROOT_NEEDLE\n", encoding="utf-8")

    _register_workspace_session(store, session_id="agent-search", workspace_root=workspace_root)
    executor = NativeToolExecutor()
    executor.set_agent_session_store(store)

    seen: dict[str, str] = {}
    original_walk = native_tools_module.os.walk

    def _wrapped_walk(base, *args, **kwargs):
        seen["base"] = str(base)
        return original_walk(base, *args, **kwargs)

    monkeypatch.setattr(native_tools_module.os, "walk", _wrapped_walk)

    result = asyncio.run(
        executor.execute(
            {"tool_name": "search_keyword", "keyword": "SESSION_ROOT_NEEDLE", "max_results": 5},
            session_id="agent-search",
        )
    )

    expected_base = str(workspace_root.resolve())
    assert result["status"] == "success"
    assert seen["base"] == expected_base
    assert "scratch/agent_worktrees/ws30_009_search/docs/needle.txt:1:" in str(result["result"]).replace("\\", "/")


def test_workspace_txn_apply_rewrites_relative_changes_against_session_workspace_root(
    monkeypatch: pytest.MonkeyPatch,
    store: AgentSessionStore,
    cleanup_paths: list[Path],
) -> None:
    workspace_root = Path("scratch/agent_worktrees/ws30_009_txn")
    shutil.rmtree(workspace_root, ignore_errors=True)
    cleanup_paths.append(workspace_root)

    _register_workspace_session(store, session_id="agent-txn", workspace_root=workspace_root)
    executor = NativeToolExecutor()
    executor.set_agent_session_store(store)

    monkeypatch.setattr(
        native_tools_module.TestBaselineGuard,
        "check_modification_allowed",
        lambda self, safe_path, requester=None: (True, ""),
    )

    captured: dict[str, list[str]] = {}

    def _fake_apply_all(changes, verify_fn=None, conflict_backoff=None):
        del verify_fn, conflict_backoff
        captured["paths"] = [change.path.replace("\\", "/") for change in changes]
        return SimpleNamespace(
            transaction_id="txn_ws30_009",
            committed=True,
            clean_state=True,
            recovery_ticket="recovery_ws30_009",
            changed_files=list(captured["paths"]),
            semantic_rebased_files=[],
            verify_message="verify ok",
        )

    monkeypatch.setattr(executor.workspace_txn, "apply_all", _fake_apply_all)

    result = asyncio.run(
        executor.execute(
            {
                "tool_name": "workspace_txn_apply",
                "changes": [{"path": "patches/demo.txt", "content": "patched", "mode": "overwrite"}],
                "session_id": "agent-txn",
            },
            session_id="agent-txn",
        )
    )

    expected = "scratch/agent_worktrees/ws30_009_txn/patches/demo.txt"
    assert result["status"] == "success"
    assert captured["paths"] == [expected]
    assert expected in str(result["result"]).replace("\\", "/")
