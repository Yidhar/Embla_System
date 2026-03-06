from __future__ import annotations

from pathlib import Path

import pytest

from agents.core_agent import CoreAgent
from agents.runtime.agent_session import AgentSessionStore
from agents.runtime.mailbox import AgentMailbox
from agents.runtime.parent_tools import handle_parent_tool_call
from system.git_worktree_sandbox import apply_workspace_path_overrides


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


def test_apply_workspace_path_overrides_rewrites_file_and_command_paths() -> None:
    workspace_root = Path("/repo/scratch/agent_worktrees/agent-1")

    read_args = apply_workspace_path_overrides("read_file", {"path": "system/config.py"}, workspace_root)
    assert read_args["path"] == str((workspace_root / "system/config.py").resolve())

    cmd_args = apply_workspace_path_overrides("run_cmd", {"command": "pwd"}, workspace_root)
    assert cmd_args["cwd"] == str(workspace_root.resolve())

    git_args = apply_workspace_path_overrides("git_status", {}, workspace_root)
    assert git_args["repo_path"] == str(workspace_root.resolve())
    assert git_args["cwd"] == str(workspace_root.resolve())

    txn_args = apply_workspace_path_overrides(
        "workspace_txn_apply",
        {"changes": [{"path": "agents/demo.py", "content": "print(1)"}]},
        workspace_root,
    )
    assert txn_args["changes"][0]["path"] == str((workspace_root / "agents/demo.py").resolve())


def test_spawn_child_agent_creates_worktree_metadata(monkeypatch, store, mailbox):
    store.create(role="core", session_id="core-1")

    def _fake_create_git_worktree_sandbox(*, owner_session_id: str, ref: str = "HEAD", repo_root=None, git_runner=None):
        del git_runner
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
                "workspace_created_at": "2026-03-07T00:00:00+00:00",
            }
        })()

    monkeypatch.setattr("agents.runtime.parent_tools.create_git_worktree_sandbox", _fake_create_git_worktree_sandbox)

    result = handle_parent_tool_call(
        "spawn_child_agent",
        {
            "role": "expert",
            "task_description": "self maintenance",
            "workspace_mode": "worktree",
        },
        parent_session_id="core-1",
        store=store,
        mailbox=mailbox,
    )

    session = store.get(result["agent_id"])
    assert session is not None
    assert session.metadata["workspace_mode"] == "worktree"
    assert session.metadata["workspace_root"].endswith(result["agent_id"])
    assert result["workspace_mode"] == "worktree"


def test_spawn_child_agent_inherits_parent_workspace(store, mailbox):
    store.create(
        role="expert",
        session_id="expert-1",
        metadata={
            "workspace_mode": "worktree",
            "workspace_sandbox_type": "git_worktree",
            "workspace_origin_root": "/repo",
            "workspace_root": "/repo/scratch/agent_worktrees/expert-1",
            "workspace_ref": "HEAD",
            "workspace_owner_session_id": "expert-1",
            "workspace_cleanup_on_destroy": True,
        },
    )

    result = handle_parent_tool_call(
        "spawn_child_agent",
        {
            "role": "dev",
            "task_description": "fix bug",
        },
        parent_session_id="expert-1",
        store=store,
        mailbox=mailbox,
    )

    session = store.get(result["agent_id"])
    assert session is not None
    assert session.metadata["workspace_mode"] == "inherit"
    assert session.metadata["workspace_root"] == "/repo/scratch/agent_worktrees/expert-1"
    assert session.metadata["workspace_owner_session_id"] == "expert-1"


def test_destroy_cleans_owned_worktree(monkeypatch, store):
    calls = []

    def _fake_cleanup_git_worktree_sandbox(*, worktree_root, repo_root=None, git_runner=None):
        del git_runner
        calls.append((str(worktree_root), str(repo_root or "")))
        return True, ""

    monkeypatch.setattr("agents.runtime.agent_session.cleanup_git_worktree_sandbox", _fake_cleanup_git_worktree_sandbox)

    session = store.create(
        role="expert",
        session_id="expert-2",
        metadata={
            "workspace_root": "/repo/scratch/agent_worktrees/expert-2",
            "workspace_origin_root": "/repo",
            "workspace_owner_session_id": "expert-2",
            "workspace_cleanup_on_destroy": True,
        },
    )

    store.destroy(session.session_id, reason="done")

    assert calls == [('/repo/scratch/agent_worktrees/expert-2', '/repo')]


def test_core_spawn_experts_self_repo_requests_worktree(monkeypatch, store, mailbox):
    store.create(role="core", session_id="core-2")

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
                "workspace_created_at": "2026-03-07T00:00:00+00:00",
            }
        })()

    monkeypatch.setattr("agents.runtime.parent_tools.create_git_worktree_sandbox", _fake_create_git_worktree_sandbox)

    core = CoreAgent(store=store, mailbox=mailbox)
    result = core.spawn_experts(
        {
            "target_repo": "self",
            "expert_assignments": [
                {
                    "expert_type": "backend",
                    "scope": "[BACKEND]\n- refactor runtime",
                    "prompt_blocks": ["roles/backend_expert.md"],
                    "tool_subset": ["read_file"],
                    "model_tier": "primary",
                }
            ],
        },
        core_execution_session_id="core-2",
        pipeline_id="pipe_test",
    )

    assert len(result) == 1
    expert_session = store.get(result[0]["agent_id"])
    assert expert_session is not None
    assert expert_session.metadata["workspace_mode"] == "worktree"
    assert expert_session.metadata["workspace_owner_session_id"] == expert_session.session_id
